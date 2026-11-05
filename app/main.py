import csv
import io
import json
import os
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import analytics, auth, config, db, importer, ingest, llm, ml, simulator
from .i18n import norm, tr

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, "..", "frontend", "dist")


def seed_from_file(path):
    """Import an Excel/CSV file at start-up when the database is empty (SEED_FILE in .env).
    Free hosts wipe the disk on every restart, so this gives the demo its data back. Never raises."""
    if not path:
        return False
    full = path if os.path.isabs(path) else os.path.join(BASE, "..", path)
    try:
        with open(full, "rb") as f:
            data = f.read()
        _, readings, names, fields = importer.process(os.path.basename(full), data, "en")
        for lid, nm in names.items():
            db.upsert_lift(lid, nm)
            if nm and nm != lid:
                db.rename_lift(lid, nm)
        db.merge_readings(readings, fields)
        return True
    except Exception as e:  # a bad seed file must not stop the server
        print(f"SEED_FILE {path!r} could not be imported: {e}")
        return False


@asynccontextmanager
async def lifespan(app):
    db.init()
    if db.is_empty():
        seeded = seed_from_file(config.env("SEED_FILE"))   # hosted demo: always start with sample data
        if not seeded and not config.LIVE_MODE:
            simulator.generate()  # demo data only when no live source is configured
    handles = ingest.start_all()
    yield
    ingest.stop_all(handles)


app = FastAPI(title="Lift Energy AI", lifespan=lifespan)
Days = Query(14, ge=1, le=60)
Method = Query("stat", pattern="^(stat|ml)$")
Lang = Query("ru", pattern="^(ru|en)$")
MAX_UPLOAD = 60 * 1024 * 1024


@app.middleware("http")
async def login_guard(request: Request, call_next):
    if auth.needs_login(request.url.path, request.cookies.get(auth.COOKIE)):
        return JSONResponse({"detail": "Login required"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def api_health():
    return {"ok": True}


@app.get("/api/auth/status")
def api_auth_status(request: Request):
    tok = request.cookies.get(auth.COOKIE)
    return {"required": auth.required(), "authenticated": (not auth.required()) or auth.valid_token(tok or ""),
            "user": auth.user() if auth.required() else None}


@app.post("/api/login")
def api_login(request: Request, body: dict = Body(...)):
    if not auth.required():
        return {"ok": True}
    ip = request.client.host if request.client else "?"
    wait = auth.blocked_for(ip)
    if wait:
        raise HTTPException(429, f"Too many attempts. Try again in {wait} s.")
    if not auth.check_credentials(body.get("user", ""), body.get("password", "")):
        auth.record_failure(ip)
        raise HTTPException(401, "Wrong user name or password")
    auth.clear_failures(ip)
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.MAX_AGE, httponly=True,
                    samesite="lax", secure=secure, path="/")
    return resp


@app.post("/api/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.get("/api/lifts")
def api_lifts():
    return db.lifts()


@app.patch("/api/lifts/{lift_id}")
def api_lift_rename(lift_id: str, body: dict = Body(...)):
    name = str(body.get("name", "")).strip()
    if not name or len(name) > 80:
        raise HTTPException(400, "name must be 1-80 characters")
    if not db.rename_lift(lift_id, name):
        raise HTTPException(404, "lift not found")
    return {"id": lift_id, "name": name}


@app.delete("/api/lifts/{lift_id}")
def api_lift_delete(lift_id: str):
    if not db.delete_lift(lift_id):
        raise HTTPException(404, "lift not found")
    return {"deleted": lift_id}


@app.get("/api/overview")
def api_overview(days: int = Days):
    return analytics.overview(days)


@app.get("/api/series")
def api_series(days: int = Days):
    return analytics.series(days)


@app.get("/api/hourly/{lift_id}")
def api_hourly(lift_id: str, days: int = Query(7, ge=1, le=30), method: str = Method):
    return analytics.hourly(lift_id, days, method)


@app.get("/api/anomalies")
def api_anomalies(days: int = Days, method: str = Method, lang: str = Lang):
    return analytics.anomalies(days, method, lang)


@app.get("/api/compare")
def api_compare(days: int = Days):
    return analytics.compare(days)


@app.get("/api/forecast/{lift_id}")
def api_forecast(lift_id: str, model: str = Query("ml", pattern="^(ml|stat)$"), lang: str = Lang):
    if model == "ml":
        f = ml.forecast(lift_id, lang=lang)
        if f is not None:
            return f
    return analytics.forecast(lift_id, lang=lang)


@app.get("/api/recommendations")
def api_recommendations(days: int = Days, tariff: float = Query(8.0, gt=0, le=100), method: str = Method,
                        lang: str = Lang):
    return analytics.recommendations(days, tariff, method, lang)


# ------------------------------------------------------------------ LLM
@app.get("/api/llm/status")
def api_llm_status():
    return llm.status()


@app.post("/api/llm/test")
def api_llm_test(lang: str = Lang):
    return llm.test(lang)


@app.post("/api/explain")
def api_explain(body: dict = Body(...), lang: str = Lang):
    """{"id": "<recommendation id>" | "summary", "days": 14, "tariff": 8, "method": "stat"|"ml"}"""
    try:
        days = int(body.get("days", 14))
        tariff = float(body.get("tariff", 8.0))
    except (TypeError, ValueError):
        raise HTTPException(400, "bad parameters")
    method = body.get("method", "stat")
    if method not in ("stat", "ml") or not (1 <= days <= 60) or not (0 < tariff <= 100):
        raise HTTPException(400, "bad parameters")
    rid = str(body.get("id", ""))
    if rid == "summary":
        out = llm.explain_summary(days, tariff, method, lang)
    else:
        out = llm.explain_recommendation(rid, days, tariff, method, lang)
    if out is None:
        raise HTTPException(404, "recommendation not found (data changed?)")
    return out


# ------------------------------------------------------------------ data sources
@app.get("/api/ingest/status")
def api_ingest_status():
    return {"sources": ingest.sources(), "live_mode": config.LIVE_MODE, "last_ts": db.last_ts()}


def _parse_mapping(raw):
    if not raw:
        return None
    try:
        m = json.loads(raw)
        return m if isinstance(m, dict) else None
    except ValueError:
        return None


async def _run_import(file, lang, mapping, lift_id, cumulative):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file is larger than 60 MB")
    try:
        return importer.process(file.filename, data, norm(lang), _parse_mapping(mapping), lift_id, cumulative)
    except importer.ImportProblem as e:
        # a problem the user can fix: 422 with the localised message and, when we have it, the detected columns
        raise HTTPException(422, {"message": str(e), "summary": getattr(e, "summary", None)})
    except Exception as e:  # never a bare 500 for a bad file
        raise HTTPException(422, {"message": tr(norm(lang), "imp.bad_file", err=f"{type(e).__name__}: {e}"), "summary": None})


@app.post("/api/import/preview")
async def api_import_preview(file: UploadFile = File(...), lang: str = Lang, mapping: str = Form(None),
                             lift_id: str = Form(None), cumulative: bool = Form(False)):
    summary, _, _, _ = await _run_import(file, lang, mapping, lift_id, cumulative)
    return summary


@app.post("/api/import")
async def api_import(file: UploadFile = File(...), lang: str = Lang, replace: bool = Form(False),
                     mapping: str = Form(None), lift_id: str = Form(None), cumulative: bool = Form(False)):
    summary, readings, names, fields = await _run_import(file, lang, mapping, lift_id, cumulative)
    if replace:
        db.clear()
    for lid, nm in names.items():
        db.upsert_lift(lid, nm)
        if nm and nm != lid:
            db.rename_lift(lid, nm)
    db.merge_readings(readings, fields)
    return summary


@app.get("/api/export/readings.csv")
def api_export_readings(lift_id: str = None):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["lift_id", "ts", "kwh", "trips", "door_cycles"])
    w.writerows(db.all_readings(lift_id))
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=readings.csv"})


@app.get("/api/export/recommendations.csv")
def api_export_recs(days: int = Days, tariff: float = Query(8.0, gt=0, le=100), method: str = Method,
                    lang: str = Lang):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["lift", "severity", "title", "text", "evidence", "saving_rub_year"])
    for r in analytics.recommendations(days, tariff, method, lang):
        w.writerow([r["lift_name"], r["severity"], r["title"], r["text"], " | ".join(r["evidence"]),
                    r.get("est_saving_rub_year") or ""])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=recommendations.csv"})


@app.post("/api/reset-demo")
def api_reset_demo():
    return {"generated": simulator.reset_demo()}


@app.post("/api/clear")
def api_clear():
    db.clear()
    return {"cleared": True}


# ------------------------------------------------------------------ front end (React build)
if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def no_frontend():
        return ("<h3>Frontend не собран</h3><p>Выполните: <code>cd frontend && npm install && npm run build</code> "
                "или запустите <code>npm run dev</code> (порт 5173). API: <a href='/docs'>/docs</a></p>")
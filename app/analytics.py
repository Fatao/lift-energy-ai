"""Explainable analytics. No black box: every number can be recomputed from the readings.

Model per lift: hourly  kWh ~ standby + per_trip * trips   (robust least squares).
 - standby  = energy the lift uses with no movement (lights, ventilation, displays, brake)
 - per_trip = marginal energy of one trip
Anomaly    = hour whose energy is far above what the trips in that hour explain.
Forecast   = per-weekday median of the last weeks x short-term trend (statistical
             estimate; NOT predictive maintenance, there is no failure labelling yet).
Recommendations are rules that quote the facts they are based on. The engineer decides.

The model needs BOTH energy and trips per hour. (They may arrive from different sources,
for example an energy meter on Modbus and trip counts from the controller over MQTT: readings
of the same lift and hour are added together.)
"""
from datetime import datetime, timedelta
from statistics import median, pstdev

from . import db
from .i18n import nf, tr

FMT = "%Y-%m-%dT%H:%M:%S"
HOURS_PER_YEAR = 8760


# ---------------------------------------------------------------- helpers
def _window(days):
    end = db.last_ts()
    if not end:
        return None, None
    e = datetime.strptime(end, FMT)
    s = e - timedelta(days=days) + timedelta(hours=1)
    return s.strftime(FMT), end


def _load(lift_id, days):
    since, _ = _window(days)
    return db.readings(lift_id, since) if since else []


def _ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    if vx == 0:
        return my, 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx
    return my - b * mx, b


def _fit(rows):
    """Robust two-pass OLS. Returns (standby, per_trip, sigma) or None."""
    if len(rows) < 48:
        return None
    xs = [r["trips"] for r in rows]
    ys = [r["kwh"] for r in rows]
    a, b = _ols(xs, ys)
    for _ in range(2):
        res = [y - (a + b * x) for x, y in zip(xs, ys)]
        m = median(res)
        sig = 1.4826 * median(abs(r - m) for r in res) or 1e-6
        keep = [i for i, r in enumerate(res) if abs(r) <= 3 * sig]
        if len(keep) < 48:
            break
        a, b = _ols([xs[i] for i in keep], [ys[i] for i in keep])
    res = [y - (a + b * x) for x, y in zip(xs, ys)]
    m = median(res)
    sig = 1.4826 * median(abs(r - m) for r in res) or 1e-6
    return a, b, sig


def _events(rows, fit, flagged=None):
    """Merge consecutive anomalous hours into events.

    flagged: optional [(row, residual, expected)] from another detector (ML); by default
    the statistical rule is used: residual > max(4 sigma, 0.5 kWh)."""
    if not fit:
        return []
    if flagged is None:
        a, b, sig = fit
        thr = max(4 * sig, 0.5)  # absolute floor (kWh/h) so rush-hour noise never alarms
        flagged = []
        for r in rows:
            expected = a + b * r["trips"]
            res = r["kwh"] - expected
            if res > thr:
                flagged.append((r, res, expected))
    events, cur = [], None
    for r, res, expected in flagged:
        t = datetime.strptime(r["ts"], FMT)
        if cur and t - cur["_last"] == timedelta(hours=1):
            cur["end"] = r["ts"]
            cur["hours"] += 1
            cur["extra_kwh"] += res
            cur["peak_kwh"] = max(cur["peak_kwh"], r["kwh"])
            cur["trips"] += r["trips"]
            cur["_last"] = t
        else:
            if cur:
                events.append(cur)
            cur = {
                "start": r["ts"], "end": r["ts"], "hours": 1, "extra_kwh": res,
                "peak_kwh": r["kwh"], "trips": r["trips"], "_last": t,
            }
    if cur:
        events.append(cur)
    for e in events:
        e.pop("_last")
        e["extra_kwh"] = round(e["extra_kwh"], 2)
        e["peak_kwh"] = round(e["peak_kwh"], 2)
        e["kind"] = "idle" if e["trips"] == 0 else "moving"
        e["severity"] = "high" if e["extra_kwh"] >= 3 else "medium"
    return events


def _names():
    return {l["id"]: l["name"] for l in db.lifts()}


# ---------------------------------------------------------------- per lift
def lift_summary(lift_id, days):
    rows = _load(lift_id, days)
    if not rows:
        return None
    total = sum(r["kwh"] for r in rows)
    trips = sum(r["trips"] for r in rows)
    idle = [r["kwh"] for r in rows if r["trips"] == 0]
    fit = _fit(rows)
    standby_kw = median(idle) if len(idle) >= 6 else (fit[0] if fit else None)
    idle_kwh = sum(idle)
    events = _events(rows, fit)
    last = datetime.strptime(db.last_ts(), FMT)
    recent_cut = (last - timedelta(hours=72)).strftime(FMT)
    by_hour = {}
    for r in rows:
        by_hour.setdefault(int(r["ts"][11:13]), []).append(r["kwh"])
    peak_hour = max(by_hour, key=lambda h: sum(by_hour[h]) / len(by_hour[h])) if by_hour else None
    return {
        "lift_id": lift_id,
        "total_kwh": round(total, 1),
        "avg_kwh_per_day": round(total / (len(rows) / 24), 1),
        "trips": trips,
        "kwh_per_trip": round(total / trips, 3) if trips else None,
        "marginal_kwh_per_trip": round(fit[1], 4) if fit else None,
        "standby_kw": round(standby_kw, 3) if standby_kw is not None else None,
        "standby_share": round(idle_kwh / total, 3) if total else None,
        "anomalies": len(events),
        "recent_anomalies": sum(1 for e in events if e["start"] >= recent_cut),
        "anomaly_extra_kwh": round(sum(e["extra_kwh"] for e in events), 1),
        "completeness": round(min(1.0, len(rows) / (days * 24)), 3),
        "peak_hour": peak_hour,
    }


def _ready(items):
    """Lifts with enough history for model-based metrics (a freshly connected lift is not yet comparable)."""
    keys = ("standby_kw", "marginal_kwh_per_trip", "kwh_per_trip")
    return [i for i in items if all(i.get(k) is not None for k in keys)]


def overview(days):
    names = _names()
    items = []
    for lid in sorted(names):
        s = lift_summary(lid, days)
        if s:
            s["name"] = names[lid]
            items.append(s)
    if not items:
        return {"days": days, "lifts": [], "group": None}
    ready = _ready(items)
    med_s = median(i["standby_kw"] for i in ready) if len(ready) >= 3 else None
    med_m = median(i["marginal_kwh_per_trip"] for i in ready) if len(ready) >= 3 else None
    for i in items:
        if i not in ready:
            i["status"] = "warmup"
        elif i["recent_anomalies"] > 0:
            i["status"] = "alert"
        elif med_s and (i["standby_kw"] > 1.3 * med_s or i["marginal_kwh_per_trip"] > 1.15 * med_m):
            i["status"] = "watch"
        else:
            i["status"] = "ok"
    total = sum(i["total_kwh"] for i in items)
    trips = sum(i["trips"] for i in items)
    idle_kwh = sum((i["standby_share"] or 0) * i["total_kwh"] for i in items)
    group = {
        "total_kwh": round(total, 1),
        "trips": trips,
        "kwh_per_trip": round(total / trips, 3) if trips else None,
        "standby_share": round(idle_kwh / total, 3) if total else None,
        "anomalies": sum(i["anomalies"] for i in items),
        "completeness": round(sum(i["completeness"] for i in items) / len(items), 3),
        "last_ts": db.last_ts(),
    }
    return {"days": days, "lifts": items, "group": group}


def daily(lift_id, days):
    rows = _load(lift_id, days)
    d = {}
    for r in rows:
        k = r["ts"][:10]
        x = d.setdefault(k, {"kwh": 0.0, "trips": 0, "n": 0})
        x["kwh"] += r["kwh"]
        x["trips"] += r["trips"]
        x["n"] += 1
    return d


def series(days):
    """Daily totals per lift. 'hours' says how many hourly readings a day has: a day with fewer
    than 24 is partial (usually today) and must not be drawn as if it were a full day."""
    names = _names()
    out = []
    for lid in sorted(names):
        d = daily(lid, days)
        rows = _load(lid, days)
        prof = {}
        for r in rows:
            prof.setdefault(int(r["ts"][11:13]), []).append(r["kwh"])
        keys = sorted(d)
        out.append({
            "lift_id": lid, "name": names[lid],
            "dates": keys,
            "kwh": [round(d[k]["kwh"], 2) for k in keys],
            "trips": [d[k]["trips"] for k in keys],
            "hours": [d[k]["n"] for k in keys],
            "hour_profile": [round(sum(prof[h]) / len(prof[h]), 3) if h in prof else 0 for h in range(24)],
        })
    return out


def _detect(lift_id, days, method):
    """Events for one lift in the window. method: 'stat' (rules) or 'ml' (IsolationForest)."""
    rows = _load(lift_id, days)
    if method == "ml":
        from . import ml

        rows_all = _load(lift_id, 60)
        fit_all = _fit(rows_all)
        flagged = ml.flag_anomalies(rows_all, rows)
        if flagged is not None:
            return rows, fit_all, _events(rows, fit_all, flagged)
    fit = _fit(rows)
    return rows, fit, _events(rows, fit)


def hourly(lift_id, days, method="stat"):
    rows, fit, events = _detect(lift_id, days, method)
    flagged = set()
    for e in events:
        t = datetime.strptime(e["start"], FMT)
        end = datetime.strptime(e["end"], FMT)
        while t <= end:
            flagged.add(t.strftime(FMT))
            t += timedelta(hours=1)
    fit_show = _fit(_load(lift_id, 30)) or fit
    expected = [round(fit_show[0] + fit_show[1] * r["trips"], 3) if fit_show else None for r in rows]
    return {
        "lift_id": lift_id,
        "method": method,
        "ts": [r["ts"] for r in rows],
        "kwh": [r["kwh"] for r in rows],
        "expected": expected,
        "anomaly_idx": [i for i, r in enumerate(rows) if r["ts"] in flagged],
    }


def anomalies(days, method="stat", lang="ru"):
    names = _names()
    out = []
    for lid in sorted(names):
        _, _, events = _detect(lid, days, method)
        for e in events:
            e["lift_id"], e["lift_name"], e["method"] = lid, names[lid], method
            e["kind_text"] = tr(lang, "ev." + e["kind"])
            out.append(e)
    out.sort(key=lambda e: e["start"], reverse=True)
    return out


# ---------------------------------------------------------------- compare
def compare(days):
    all_lifts = overview(days)["lifts"]
    ov = _ready(all_lifts)
    skipped = [i["name"] for i in all_lifts if i not in ov]
    if len(ov) < 3:
        return {"lifts": ov, "medians": None, "skipped": skipped}
    med = {
        "standby_kw": median(i["standby_kw"] for i in ov),
        "marginal_kwh_per_trip": median(i["marginal_kwh_per_trip"] for i in ov),
        "kwh_per_trip": median(i["kwh_per_trip"] for i in ov),
    }
    for i in ov:
        for k, m in med.items():
            i[k + "_dev"] = round((i[k] / m - 1) * 100, 1) if m else None
    return {"lifts": ov, "medians": {k: round(v, 4) for k, v in med.items()}, "skipped": skipped}


# ---------------------------------------------------------------- forecast
def forecast(lift_id, horizon=7, lang="ru"):
    d = daily(lift_id, 35)
    full = [(k, v["kwh"]) for k, v in sorted(d.items()) if v["n"] >= 22]
    hist = full[-28:]
    if len(hist) < 14:
        return {"lift_id": lift_id, "error": tr(lang, "fc.error")}
    by_wd = {}
    for k, v in hist:
        by_wd.setdefault(datetime.strptime(k, "%Y-%m-%d").weekday(), []).append(v)
    overall = median(v for _, v in hist)
    wd_med = {w: median(vs) if len(vs) >= 2 else overall for w, vs in by_wd.items()}
    last7 = median(v for _, v in hist[-7:])
    prev7 = median(v for _, v in hist[-14:-7])
    trend = max(0.9, min(1.1, last7 / prev7)) if prev7 else 1.0
    resid = [v - wd_med.get(datetime.strptime(k, "%Y-%m-%d").weekday(), overall) for k, v in hist]
    sd = pstdev(resid) if len(resid) > 1 else 0.0
    last_day = datetime.strptime(hist[-1][0], "%Y-%m-%d")
    fc = []
    for i in range(1, horizon + 1):
        day = last_day + timedelta(days=i)
        base = wd_med.get(day.weekday(), overall) * trend
        fc.append({
            "date": day.strftime("%Y-%m-%d"), "kwh": round(base, 2),
            "low": round(max(base - 1.28 * sd, 0), 2), "high": round(base + 1.28 * sd, 2),
        })
    return {
        "lift_id": lift_id,
        "history": [{"date": k, "kwh": round(v, 2)} for k, v in hist],
        "forecast": fc,
        "trend_factor": round(trend, 3),
        "band_sd": round(sd, 2),
        "last7_actual": round(sum(v for _, v in hist[-7:]), 1),
        "next7_forecast": round(sum(f["kwh"] for f in fc), 1),
        "model": "stat",
        "model_name": tr(lang, "model.stat"),
        "backtest": None,
        "method": tr(lang, "fc.method.stat"),
    }


# ---------------------------------------------------------------- recommendations
def recommendations(days, tariff, method="stat", lang="ru"):
    names = _names()
    ov_all = overview(days)["lifts"]
    ov = _ready(ov_all)
    out = []
    med = compare(days)["medians"]

    def pct_text(x):
        return nf(lang, x * 100, 1)

    for i in ov_all:
        if i not in ov:
            out.append({
                "lift_id": i["lift_id"], "lift_name": names[i["lift_id"]], "severity": "low", "kind": "warmup",
                "title": tr(lang, "rec.warmup.title"),
                "text": tr(lang, "rec.warmup.text"),
                "evidence": [tr(lang, "rec.completeness", days=days, pct=pct_text(i["completeness"]))],
                "est_saving_rub_year": None,
            })

    for i in ov:
        lid, name = i["lift_id"], names[i["lift_id"]]

        if i["completeness"] < 0.95:
            out.append({
                "lift_id": lid, "lift_name": name, "severity": "medium", "kind": "data",
                "title": tr(lang, "rec.data.title"),
                "text": tr(lang, "rec.data.text"),
                "evidence": [tr(lang, "rec.completeness", days=days, pct=pct_text(i["completeness"]))],
                "est_saving_rub_year": None,
            })

        if med and i["standby_kw"] > 1.3 * med["standby_kw"]:
            excess_kw = i["standby_kw"] - med["standby_kw"]
            kwh_year = excess_kw * HOURS_PER_YEAR
            out.append({
                "lift_id": lid, "lift_name": name, "severity": "high", "kind": "standby",
                "title": tr(lang, "rec.standby.title"),
                "text": tr(lang, "rec.standby.text"),
                "evidence": [
                    tr(lang, "rec.standby.e1", v=nf(lang, i["standby_kw"], 2), m=nf(lang, med["standby_kw"], 2),
                       p=nf(lang, (i["standby_kw"] / med["standby_kw"] - 1) * 100, 0)),
                    tr(lang, "rec.standby.e2", p=nf(lang, i["standby_share"] * 100, 0)),
                    tr(lang, "rec.excess", v=nf(lang, kwh_year, 0, group=True)),
                ],
                "est_saving_rub_year": round(kwh_year * tariff),
            })

        if med and i["marginal_kwh_per_trip"] > 1.15 * med["marginal_kwh_per_trip"]:
            extra = i["marginal_kwh_per_trip"] - med["marginal_kwh_per_trip"]
            yearly_trips = i["trips"] / days * 365
            kwh_year = extra * yearly_trips
            out.append({
                "lift_id": lid, "lift_name": name, "severity": "medium", "kind": "per_trip",
                "title": tr(lang, "rec.per_trip.title"),
                "text": tr(lang, "rec.per_trip.text"),
                "evidence": [
                    tr(lang, "rec.per_trip.e1", v=nf(lang, i["marginal_kwh_per_trip"], 3),
                       m=nf(lang, med["marginal_kwh_per_trip"], 3),
                       p=nf(lang, (i["marginal_kwh_per_trip"] / med["marginal_kwh_per_trip"] - 1) * 100, 0)),
                    tr(lang, "rec.per_trip.e2", days=days, n=nf(lang, i["trips"], 0, group=True)),
                    tr(lang, "rec.excess", v=nf(lang, kwh_year, 0, group=True)),
                ],
                "est_saving_rub_year": round(kwh_year * tariff),
            })

    # recent anomaly events (last 7 days of the window)
    end = db.last_ts()
    if end:
        cutoff = (datetime.strptime(end, FMT) - timedelta(days=7)).strftime(FMT)
        for e in anomalies(days, method, lang):
            if e["start"] >= cutoff:
                out.append({
                    "lift_id": e["lift_id"], "lift_name": e["lift_name"], "severity": e["severity"],
                    "kind": "anomaly", "start": e["start"],
                    "title": tr(lang, "rec.anomaly.title", when=e["start"][5:16].replace("T", " ")),
                    "text": tr(lang, "rec.anomaly.text"),
                    "evidence": [
                        tr(lang, "rec.anomaly.e1", kind=e["kind_text"], h=e["hours"]),
                        tr(lang, "rec.anomaly.e2", x=nf(lang, e["extra_kwh"], 2), p=nf(lang, e["peak_kwh"], 2)),
                    ],
                    "est_saving_rub_year": None,
                })

        for i in ov:
            f = forecast(i["lift_id"], lang=lang)
            if "error" in f or not f["last7_actual"]:
                continue
            if f["next7_forecast"] > 1.10 * f["last7_actual"]:
                out.append({
                    "lift_id": i["lift_id"], "lift_name": names[i["lift_id"]], "severity": "low",
                    "kind": "forecast", "title": tr(lang, "rec.forecast.title"),
                    "text": tr(lang, "rec.forecast.text"),
                    "evidence": [tr(lang, "rec.forecast.e1", a=nf(lang, f["last7_actual"], 1),
                                    f=nf(lang, f["next7_forecast"], 1))],
                    "est_saving_rub_year": None,
                })

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda r: (order[r["severity"]], r["lift_id"]))
    for r in out:  # stable id so the UI can ask for an explanation of exactly this item
        r["id"] = f"{r['lift_id']}:{r['kind']}:{r.get('start', '')}"
    return out
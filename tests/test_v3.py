import os
import io
import json
import zipfile
from datetime import datetime, timedelta

import httpx
import pytest

from app import analytics, db, importer, llm, simulator
from app.i18n import tr


def make_xlsx(rows):
    """Tiny hand-made .xlsx with a deliberately odd style sheet (openpyxl refuses such files)."""
    strings, srows = [], []
    for r in rows:
        cells = []
        for j, v in enumerate(r):
            ref = "ABCDEFGH"[j] + str(len(srows) + 1)
            if isinstance(v, str):
                strings.append(v)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
        srows.append(f'<row r="{len(srows) + 1}">{"".join(cells)}</row>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml",
                   '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                   + "".join(srows) + "</sheetData></worksheet>")
        z.writestr("xl/sharedStrings.xml",
                   '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/styles.xml", "<styleSheet><borders><border style='bogus'/></borders></styleSheet>")
    return buf.getvalue()


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    db.init()
    return tmp_path


def test_xlsx_russian_headers_15min_rows_are_summed_per_hour():
    rows = [["Лифт", "Дата и время", "Электроэнергия, кВт·ч", "Поездки"]]
    t = datetime(2026, 3, 2, 8, 0)
    for i in range(8):  # 15-minute readings -> two hours
        rows.append(["L7", (t + timedelta(minutes=15 * i)).strftime("%d.%m.%Y %H:%M"), 0.5, 3])
    s, readings, names, fields = importer.process("Book1.xlsx", make_xlsx(rows), "ru")
    assert fields == {"kwh", "trips"} and s["hours"] == 2
    assert readings[0] == ("L7", "2026-03-02T08:00:00", 2.0, 12, 0)


def test_csv_semicolon_decimal_comma_and_excel_serial_dates():
    csv = "lift;time;kwh;trips\nA;46000,5;1,5;4\nA;46000,54;0,5;2\n".encode("cp1251")
    s, readings, _, _ = importer.process("x.csv", csv, "en")
    assert len(readings) == 1 and readings[0][2] == 2.0 and readings[0][3] == 6


def test_cumulative_meter_becomes_differences():
    csv = "lift,ts,kwh\nA,2026-03-02T08:00,100\nA,2026-03-02T09:00,101.5\nA,2026-03-02T10:00,103\nA,2026-03-02T11:00,2\n"
    s, readings, _, _ = importer.process("c.csv", csv.encode(), "en", cumulative=True)
    assert [r[2] for r in readings] == [1.5, 1.5]  # baseline row and the reset row are dropped


def test_garbage_gives_readable_error_not_a_crash():
    for name, data in (("a.xlsx", b"PK\x03\x04not really"), ("a.csv", b"\x00\x01\x02"), ("a.xls", b"x"), ("a.csv", b"")):
        with pytest.raises(importer.ImportProblem):
            importer.process(name, data, "en")


def test_missing_time_column_reports_detected_headers():
    with pytest.raises(importer.ImportProblem) as e:
        importer.process("a.csv", b"lift,foo,kwh\nA,1,2\n", "en")
    assert e.value.summary["headers"] == ["lift", "foo", "kwh"]


def test_api_import_xlsx_end_to_end_and_partial_columns_dont_wipe(scratch):
    from fastapi.testclient import TestClient
    from app.main import app
    base = [["lift_id", "ts", "kwh", "trips"]] + [["Z", f"2026-03-02T{h:02d}:00:00", 1.0, 5] for h in range(6)]
    with TestClient(app) as c:
        r = c.post("/api/import", files={"file": ("Book1.xlsx", make_xlsx(base))}, data={"replace": "true"})
        assert r.status_code == 200 and r.json()["hours"] == 6
        trips_only = [["lift_id", "ts", "trips"]] + [["Z", f"2026-03-02T{h:02d}:00:00", 9] for h in range(6)]
        assert c.post("/api/import", files={"file": ("t.csv", "\n".join(",".join(map(str, r)) for r in trips_only).encode())}).status_code == 200
        rows = db.all_readings("Z")
        assert rows[0][2] == 1.0 and rows[0][3] == 9          # energy kept, trips replaced
        bad = c.post("/api/import", files={"file": ("bad.xlsx", b"PK\x03\x04junk")})
        assert bad.status_code == 422 and "message" in bad.json()["detail"]
        assert c.post("/api/import/preview", files={"file": ("p.csv", b"lift,ts,kwh\nA,2026-03-02T01:00,1\n")}).json()["hours"] == 1
        assert c.patch("/api/lifts/Z", json={"name": "Lift Z"}).status_code == 200
        assert c.delete("/api/lifts/Z").status_code == 200 and c.delete("/api/lifts/Z").status_code == 404
        assert c.get("/api/export/readings.csv").status_code == 200


def test_localised_api_texts_differ(scratch):
    from fastapi.testclient import TestClient
    from app.main import app
    simulator.generate()
    with TestClient(app) as c:
        ru = c.get("/api/recommendations?lang=ru").json()
        en = c.get("/api/recommendations?lang=en").json()
        assert ru and en and ru[0]["title"] != en[0]["title"]
        assert c.get("/api/forecast/L1?lang=en").json()["model_name"] != c.get("/api/forecast/L1?lang=ru").json()["model_name"]
        assert c.get("/api/anomalies?lang=de").status_code == 422


def test_series_reports_hours_per_day_so_partial_day_can_be_hidden(scratch):
    simulator.generate()
    s = analytics.series(7)
    hours = s[0]["hours"]
    assert len(hours) == len(s[0]["dates"]) and all(h == 24 for h in hours[1:-1]) and hours[-1] <= 24


def test_gemini_request_shape_and_secret_scrub(scratch, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyFAKEFAKEFAKEFAKE123456")
    seen = {}

    def fake_post(url, **kw):
        seen.update(url=url, **kw)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "OK"}]}}]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    out = llm.test("en")
    assert out["ok"] and out["provider"] == "gemini"
    assert "gemini-3.8-flash:generateContent" in seen["url"]
    assert seen["headers"]["x-goog-api-key"].startswith("AIza") and "AIza" not in seen["url"]

    def boom(url, **kw):
        raise RuntimeError("bad key AIzaSyFAKEFAKEFAKEFAKE123456")
    monkeypatch.setattr(llm.httpx, "post", boom)
    msg = llm.test("en")["message"]
    assert "AIza" not in msg and "***" in msg


def test_llm_test_without_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    out = llm.test("en")
    assert not out["ok"] and out["message"]


# ---------------------------------------------------------------- Modbus register map
def test_modbus_float32_int16_and_function_4_request():
    import struct
    from app.ingest import modbus_rtu as mb
    hi, lo = struct.unpack(">HH", struct.pack(">f", 123.5))
    f = {"offset": 0, "type": "float32", "scale": 1}
    assert mb.decode_field([hi, lo], f, "big") == 123.5
    assert mb.decode_field([lo, hi], f, "little") == 123.5
    assert mb.decode_field([65535], {"offset": 0, "type": "int16"}) == -1
    req = mb.build_read_request(1, 0x10, 4, function=4)
    assert req[1] == 4 and mb.crc16(req[:-2]) == int.from_bytes(req[-2:], "little")
    with pytest.raises(mb.ModbusError):
        mb.decode_field([1], {"offset": 0, "type": "uint32"})        # map points past the block
    with pytest.raises(mb.ModbusError):
        mb.decode_field([0, 0], {"offset": 0, "type": "nope"})


def test_mqtt_energy_only_then_trips_only_are_summed(scratch):
    from app.ingest import mqtt_client
    ts = "2026-03-02T08:10:00"
    mqtt_client.handle_message("lifts/Q/telemetry", json.dumps({"kwh": 0.5, "ts": ts}).encode())
    mqtt_client.handle_message("lifts/Q/telemetry", json.dumps({"trips": 4, "ts": ts}).encode())
    row = db.all_readings("Q")[0]
    assert row[2] == 0.5 and row[3] == 4


def test_dotenv_strips_inline_comments_and_quotes(tmp_path, monkeypatch):
    from app import config
    f = tmp_path / ".env"
    f.write_text('MODBUS_UNITS=L1=1,L2=2     # lift=address\nGEMINI_X="a # b"\n# C=1\nEMPTY=\n', encoding="utf-8")
    for k in ("MODBUS_UNITS", "GEMINI_X"):
        monkeypatch.delenv(k, raising=False)
    config._load_dotenv(str(f))
    try:
        assert config.os.environ["MODBUS_UNITS"] == "L1=1,L2=2"
        assert config.os.environ["GEMINI_X"] == "a # b"
    finally:
        config.os.environ.pop("MODBUS_UNITS", None)
        config.os.environ.pop("GEMINI_X", None)


def test_two_providers_fallback_and_test_button(monkeypatch):
    llm._down.clear()
    monkeypatch.setenv("LLM_PROVIDER", "gemini,gigachat")
    monkeypatch.setenv("GEMINI_API_KEY", "GEMINIKEY123456")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "GIGAKEY1234567")
    assert llm.providers() == ["gemini", "gigachat"] and llm.status()["configured"]

    def one(messages, p):
        if p == "gemini":
            raise RuntimeError("gemini is down GEMINIKEY123456")
        return "OK from giga"
    monkeypatch.setattr(llm, "_chat_one", one)
    assert llm._chat([{"role": "user", "content": "x"}]) == "OK from giga" and llm._last["provider"] == "gigachat"
    t = llm.test("en")
    assert t["ok"] and [r["ok"] for r in t["results"]] == [False, True]
    assert "GEMINIKEY" not in t["message"]


def test_failed_provider_is_skipped_for_a_while(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini,gigachat")
    monkeypatch.setenv("GEMINI_API_KEY", "GEMINIKEY123456")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "GIGAKEY1234567")
    llm._down.clear()
    calls = []

    def one(messages, p):
        calls.append(p)
        if p == "gemini":
            raise RuntimeError("HTTP 503")
        return "giga"
    monkeypatch.setattr(llm, "_chat_one", one)
    msgs = [{"role": "user", "content": "x"}]
    assert llm._chat(msgs) == "giga" and calls == ["gemini", "gigachat"]
    calls.clear()
    assert llm._chat(msgs) == "giga" and calls == ["gigachat"]   # gemini is cooling, not asked again
    llm._down.clear()


def test_excel_serial_times_are_not_floored_into_the_previous_hour():
    # 08:00 is stored by Excel as a float that is a hair below 8:00 -> must still be 08:00
    rows = [["lift_id", "ts", "kwh", "trips"]]
    base = 46296
    for h in range(8, 14):
        rows.append(["Z", base + h / 24, 1.0, 5])
    s, readings, names, fields = importer.process("x.xlsx", make_xlsx(rows), "en")
    assert s["hours"] == 6 and [r[1][11:13] for r in readings] == ["08", "09", "10", "11", "12", "13"]


# ---------------------------------------------------------------- login
def test_login_off_by_default_and_on_with_password(scratch, monkeypatch):
    from fastapi.testclient import TestClient
    from app import auth
    from app.main import app
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    auth._fails.clear()
    with TestClient(app) as c:
        assert c.get("/api/lifts").status_code == 200
        assert c.get("/api/auth/status").json() == {"required": False, "authenticated": True, "user": None}
        monkeypatch.setenv("APP_PASSWORD", "s3cret-pass")
        assert c.get("/api/lifts").status_code == 401
        assert c.post("/api/clear").status_code == 401
        assert c.get("/docs").status_code == 401
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/auth/status").json()["authenticated"] is False
        assert c.post("/api/login", json={"user": "admin", "password": "wrong"}).status_code == 401
        r = c.post("/api/login", json={"user": "admin", "password": "s3cret-pass"})
        assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
        assert c.get("/api/lifts").status_code == 200
        assert c.get("/api/auth/status").json()["authenticated"] is True
        c.post("/api/logout")
        assert c.get("/api/lifts").status_code == 401


def test_login_token_expiry_forgery_and_rate_limit(monkeypatch):
    from app import auth
    monkeypatch.setenv("APP_PASSWORD", "pw12345678")
    auth._fails.clear()
    tok = auth.make_token(now=1000)
    assert auth.valid_token(tok, now=1000 + 60)
    assert not auth.valid_token(tok, now=1000 + auth.MAX_AGE + 1)
    assert not auth.valid_token(tok[:-2] + "00") and not auth.valid_token("garbage")
    monkeypatch.setenv("APP_PASSWORD", "another-password")      # password change logs everybody out
    assert not auth.valid_token(tok, now=1000 + 60)
    for _ in range(auth.MAX_FAILS):
        auth.record_failure("1.2.3.4", now=2000)
    assert auth.blocked_for("1.2.3.4", now=2001) > 0
    assert auth.blocked_for("1.2.3.4", now=2000 + auth.WINDOW + 1) == 0
    auth._fails.clear()


def test_esp32_firmware_payload_is_accepted_and_extra_fields_ignored(scratch):
    from app.ingest import mqtt_client
    first = b'{"kwh_total":12.345,"trips_total":87,"door_cycles_total":170,"power_w":41.2}'
    nxt = b'{"kwh_total":12.399,"trips_total":90,"door_cycles_total":176,"power_w":55.0}'
    no_meter = b'{"trips_total":91,"door_cycles_total":178}'            # PZEM did not answer: no kwh field
    assert mqtt_client.handle_message("lifts/E1/telemetry", first) == "baseline"
    assert mqtt_client.handle_message("lifts/E1/telemetry", nxt) == "counters"
    assert mqtt_client.handle_message("lifts/E1/telemetry", no_meter) in ("counters", "baseline")
    row = db.all_readings("E1")[0]
    assert abs(row[2] - 0.054) < 1e-6 and row[3] >= 3


def test_seed_file_imports_when_db_is_empty_and_bad_file_does_not_crash(scratch, tmp_path):
    from app import main
    sample = os.path.join(os.path.dirname(__file__), "..", "sample", "test_data_30days.xlsx")
    assert db.is_empty()
    assert main.seed_from_file(sample) is True
    assert {l["id"] for l in db.lifts()} == {"A1", "A2", "B1"} and not db.is_empty()
    bad = tmp_path / "broken.xlsx"
    bad.write_bytes(b"not a spreadsheet")
    assert main.seed_from_file(str(bad)) is False
    assert main.seed_from_file(None) is False and main.seed_from_file("nope.xlsx") is False
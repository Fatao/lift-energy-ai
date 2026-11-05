import json
import struct
from datetime import datetime

import pytest

from app import analytics, db, llm, ml, simulator
from app.ingest import modbus_rtu as mb
from app.ingest import mqtt_client
from app.ingest.aggregator import Aggregator


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    db.init()
    db.clear()
    simulator.generate(end=datetime(2026, 3, 4, 15, 0))  # fixed clock: the test must not depend on the time of day


# ---------------------------------------------------------------- Modbus
def test_crc_matches_spec_vector():
    assert mb.build_read_request(1, 0, 10).hex() == "01030000000ac5cd"


def test_parse_response_ok_and_errors():
    body = struct.pack(">BBB", 1, 3, 4) + struct.pack(">2H", 0x0001, 0x86A0)
    frame = mb.with_crc(body)
    assert mb.parse_read_response(1, frame, 2) == [1, 0x86A0]
    with pytest.raises(mb.ModbusError):
        mb.parse_read_response(1, frame[:-1] + b"\x00", 2)           # bad CRC
    with pytest.raises(mb.ModbusError):
        mb.parse_read_response(2, frame, 2)                          # wrong unit
    exc = mb.with_crc(struct.pack(">BBB", 1, 0x83, 2))
    with pytest.raises(mb.ModbusError, match="exception code 2"):
        mb.parse_read_response(1, exc, 2)


def test_decode_uint32_scale_and_word_order():
    f = {"offset": 0, "words": 2, "scale": 0.01}
    assert mb.decode_field([1, 0x86A0], f) == pytest.approx(1000.0)   # 0x000186A0 = 100000 -> 1000.00
    assert mb.decode_field([0x86A0, 1], f, "little") == pytest.approx(1000.0)


# ---------------------------------------------------------------- aggregator / MQTT
@pytest.fixture
def scratch_db(tmp_path, monkeypatch):
    """Ingest tests write to their own database so they cannot move 'now' of the demo data."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "scratch.db"))
    db.init()


def test_counters_baseline_delta_reset(scratch_db):
    ag = Aggregator()
    now = datetime(2030, 1, 1, 10, 5)
    assert ag.add_counters("T1", now, 100.0, 10, 20) is False        # baseline only
    assert ag.add_counters("T1", now, 100.5, 13, 26) is True
    assert ag.add_counters("T1", now, 3.0, 1, 2) is False            # counter reset -> skipped
    assert ag.add_counters("T1", now, 3.2, 2, 4) is True
    rows = db.readings("T1", "2030-01-01T00:00:00")
    assert len(rows) == 1 and rows[0]["trips"] == 4 and rows[0]["kwh"] == pytest.approx(0.7)


def test_sanity_limit_rejects_absurd_delta(scratch_db):
    with pytest.raises(ValueError):
        Aggregator().add_delta("T2", datetime.now(), 99999, 1)


def test_mqtt_payloads(scratch_db):
    assert mqtt_client.handle_message("lifts/M1/telemetry", json.dumps({"kwh": 0.2, "trips": 2})) == "delta"
    assert mqtt_client.handle_message("lifts/M2/telemetry", json.dumps({"kwh_total": 10, "trips_total": 5})) == "baseline"
    assert mqtt_client.handle_message("lifts/M2/telemetry", json.dumps({"kwh_total": 10.4, "trips_total": 9})) == "counters"
    with pytest.raises(ValueError):
        mqtt_client.handle_message("lifts/M1/telemetry", json.dumps({"hello": 1}))
    with pytest.raises(ValueError):
        mqtt_client.handle_message("lifts/M1/telemetry", "[1,2]")


# ---------------------------------------------------------------- ML
def test_ml_finds_all_injected_fault_hours_and_no_false_alarms():
    stat = analytics.anomalies(30, "stat")
    mlr = analytics.anomalies(30, "ml")
    assert {e["lift_id"] for e in stat} == {"L4"} and len(stat) == 2
    assert {e["lift_id"] for e in mlr} == {"L4"}
    assert sum(e["hours"] for e in stat) == 7
    # the ML detector must find nearly every injected fault hour (a borderline first hour may be missed) and stay quiet elsewhere
    assert 6 <= sum(e["hours"] for e in mlr) <= 7


def test_forecast_backtest_picks_best_model():
    f = ml.forecast("L2")
    assert len(f["forecast"]) == 7 and f["model"] in f["backtest"]["mae_kwh"]
    assert f["backtest"]["mae_kwh"][f["model"]] == min(f["backtest"]["mae_kwh"].values())
    assert all(x["low"] <= x["kwh"] <= x["high"] for x in f["forecast"])


# ---------------------------------------------------------------- LLM guard
FACTS = json.dumps({"evidence": ["Простой: 0.34 кВт против 0.19 кВт (+82%)", "≈10 827 кВт·ч/год"]}, ensure_ascii=False)


def test_number_guard():
    assert llm.unverified_numbers("Простой 0,34 кВт, это на 82% выше, около 10 827 кВт·ч в год", FACTS) == []
    assert llm.unverified_numbers("Это даст экономию 25000 ₽", FACTS) == [25000.0]


def test_explain_falls_back_to_template_without_llm():
    rid = analytics.recommendations(14, 8)[0]["id"]
    out = llm.explain_recommendation(rid, 14, 8)
    assert out["source"] == "template" and "решение принимает инженер" in out["text"].lower()


def test_explain_accepts_grounded_and_rejects_invented(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    rid = analytics.recommendations(14, 8)[0]["id"]
    rec = [r for r in analytics.recommendations(14, 8) if r["id"] == rid][0]
    good = f"{rec['lift_name']}: {rec['evidence'][0]}. Стоит проверить настройки режима ожидания."
    monkeypatch.setattr(llm, "_chat", lambda m: good)
    assert llm.explain_recommendation(rid, 14, 8)["source"] == "llm"
    monkeypatch.setattr(llm, "_chat", lambda m: "Экономия составит 987654 рубля")
    out = llm.explain_recommendation(rid, 14, 8)
    assert out["source"] == "template" and "отклонён" in out["note"]

    def boom(m):
        raise RuntimeError("down")
    monkeypatch.setattr(llm, "_chat", boom)
    assert llm.explain_recommendation(rid, 14, 8)["source"] == "template"


# ---------------------------------------------------------------- API
def test_api_smoke():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        assert c.get("/api/overview?days=14").json()["group"]["total_kwh"] > 0
        assert c.get("/api/forecast/L1").json()["model"] in ("huber", "weekday_median", "naive7")
        assert c.get("/api/anomalies?days=30&method=ml").status_code == 200
        assert c.post("/api/explain", json={"id": "nope"}).status_code == 404
        assert c.post("/api/explain", json={"id": "summary"}).json()["source"] == "template"
        assert c.get("/api/anomalies?method=bad").status_code == 422


def test_new_lift_with_little_data_does_not_break_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "mix.db"))
    db.init()
    simulator.generate()
    db.add_to_hour("NEW", db.last_ts(), 0.4, 3, 6)          # one hour of data for a brand-new lift
    cmp_ = analytics.compare(14)
    assert "NEW" not in [l["lift_id"] for l in cmp_["lifts"]] and cmp_["skipped"]
    recs = analytics.recommendations(14, 8)
    assert any(r["kind"] == "warmup" and r["lift_id"] == "NEW" for r in recs)
"""Protocol-level tests: real sockets for Modbus, fake HTTP servers for the three LLM providers."""
import json
import socketserver
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from app import analytics, db, llm, simulator  # noqa: E402
from app.ingest import modbus_rtu as mb  # noqa: E402
import modbus_slave_sim as sim  # noqa: E402


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "i.db"))
    db.init()


# ---------------------------------------------------------------- Modbus over a real TCP socket
def test_modbus_poll_against_slave_simulator(scratch):
    world = sim.World(speed=3600)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), sim.make_handler(world))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        client = mb.ModbusClient(f"socket://127.0.0.1:{port}", timeout=1.0)
        regmap = {"start": 0, "count": 6, "fields": {
            "kwh": {"offset": 0, "words": 2, "scale": 0.01},
            "trips": {"offset": 2, "words": 2, "scale": 1},
            "doors": {"offset": 4, "words": 2, "scale": 1}}}
        units = {"T1": 1, "GHOST": 9}                      # unit 9 is not on the bus
        assert mb.poll_once(client, units, regmap)["T1"] is None   # baseline
        world.tick(1.0); world.tick(1.0)                   # time passes on the device
        res = mb.poll_once(client, units, regmap)
        assert res["T1"] is None and "timeout" in res["GHOST"]     # dead unit does not stop the others
        rows = db.readings("T1", "2000-01-01T00:00:00")
        assert len(rows) == 1 and rows[0]["kwh"] > 0
        client.close()
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- LLM providers
class _Fake(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        _Fake.seen.append((self.path, dict(self.headers), body))
        user = body["messages"][-1]["content"]
        facts = json.loads(user.split("ФАКТЫ:\n", 1)[1])
        text = f"{facts['lift_name']}: {facts['evidence'][0]}. Проверьте режим ожидания."
        if self.path.endswith("/api/chat"):
            out = {"message": {"content": text}}
        else:
            out = {"choices": [{"message": {"content": text}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake_llm_server():
    _Fake.seen = []
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="module")
def demo():
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "demo.db")
    old = db.DB_PATH
    db.DB_PATH = path
    db.init(); simulator.generate()
    yield
    db.DB_PATH = old


def _rid():
    return analytics.recommendations(14, 8)[0]["id"]


def test_openai_compatible_provider(demo, fake_llm_server, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_BASE_URL", fake_llm_server + "/v1")
    monkeypatch.setenv("LLM_MODEL", "free-model")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    out = llm.explain_recommendation(_rid(), 14, 8)
    assert out["source"] == "llm" and out["model"] == "free-model"
    path, headers, body = _Fake.seen[-1]
    assert path == "/v1/chat/completions" and headers["Authorization"] == "Bearer sk-test"
    assert body["model"] == "free-model" and body["messages"][0]["role"] == "system"


def test_ollama_provider(demo, fake_llm_server, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_URL", fake_llm_server)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    out = llm.explain_recommendation(_rid(), 14, 8)
    assert out["source"] == "llm" and _Fake.seen[-1][0] == "/api/chat" and _Fake.seen[-1][2]["stream"] is False


def test_gigachat_oauth_then_chat(demo, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "BASE64KEY")
    llm._tok.update(value=None, exp=0.0)
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        if "oauth" in url:
            return httpx.Response(200, json={"access_token": "TOK", "expires_at": (datetime.now().timestamp() + 1800) * 1000},
                                  request=httpx.Request("POST", url))
        user = kw["json"]["messages"][-1]["content"]
        facts = json.loads(user.split("ФАКТЫ:\n", 1)[1])
        return httpx.Response(200, json={"choices": [{"message": {"content": f"{facts['lift_name']}: {facts['evidence'][0]}."}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    rid = _rid()
    assert llm.explain_recommendation(rid, 14, 8)["source"] == "llm"
    assert llm.explain_recommendation(rid, 14, 8)["source"] == "llm"       # token is cached
    oauth = [c for c in calls if "oauth" in c[0]]
    assert len(oauth) == 1
    assert oauth[0][1]["headers"]["Authorization"] == "Basic BASE64KEY" and "RqUID" in oauth[0][1]["headers"]
    assert oauth[0][1]["data"]["scope"] == "GIGACHAT_API_PERS"
    assert calls[-1][1]["headers"]["Authorization"] == "Bearer TOK"

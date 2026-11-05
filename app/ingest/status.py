"""Thread-safe registry of ingest source states, shown in the UI."""
import threading
from datetime import datetime

_lock = threading.Lock()
_sources = {}


def update(name, **kw):
    with _lock:
        s = _sources.setdefault(
            name, {"state": "idle", "detail": "", "messages": 0, "errors": 0,
                   "last_message": None, "last_error": None}
        )
        s.update(kw)


def message(name):
    with _lock:
        s = _sources.setdefault(name, {"state": "idle", "detail": "", "messages": 0, "errors": 0,
                                       "last_message": None, "last_error": None})
        s["messages"] += 1
        s["last_message"] = datetime.now().isoformat(timespec="seconds")


def error(name, text):
    with _lock:
        s = _sources.setdefault(name, {"state": "idle", "detail": "", "messages": 0, "errors": 0,
                                       "last_message": None, "last_error": None})
        s["errors"] += 1
        s["last_error"] = str(text)[:300]


def snapshot():
    with _lock:
        return {k: dict(v) for k, v in _sources.items()}

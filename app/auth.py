"""Optional password login.

Off by default (local use). Turn it on by setting APP_PASSWORD in .env (APP_USER defaults to "admin").
A successful login sets a signed, HttpOnly cookie that is valid for 7 days. No passwords or tokens
are stored on the server; the cookie is an HMAC of "user|expiry", so restarting the server keeps
people logged in as long as the password does not change.
"""
import base64
import hashlib
import hmac
import time

from . import config

COOKIE = "lift_session"
MAX_AGE = 7 * 24 * 3600
OPEN_PATHS = {"/api/login", "/api/logout", "/api/auth/status", "/api/health"}
PROTECTED_EXTRA = ("/docs", "/redoc", "/openapi.json")   # API schema is private when login is on

_fails = {}   # ip -> [timestamps of recent failures]
MAX_FAILS, WINDOW = 5, 300


def user():
    return config.env("APP_USER", "admin")


def password():
    return config.env("APP_PASSWORD")


def required():
    return bool(password())


def _secret():
    s = config.env("APP_SECRET")
    return (s or "lift-energy|" + (password() or "")).encode()


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(now=None):
    exp = int((now or time.time()) + MAX_AGE)
    payload = f"{user()}|{exp}"
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + _sign(payload)


def valid_token(token, now=None):
    try:
        body, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(body.encode()).decode()
        name, exp = payload.split("|", 1)
        ok = hmac.compare_digest(sig, _sign(payload)) and name == user()
        return ok and int(exp) > (now or time.time())
    except Exception:
        return False


def check_credentials(u, p):
    # constant-time comparison of both fields
    a = hmac.compare_digest(str(u).encode(), user().encode())
    b = hmac.compare_digest(str(p).encode(), (password() or "").encode())
    return a and b


def blocked_for(ip, now=None):
    """Seconds the client must wait after too many failed logins (0 = may try)."""
    now = now or time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < WINDOW]
    _fails[ip] = recent
    if len(recent) >= MAX_FAILS:
        return int(WINDOW - (now - recent[0])) + 1
    return 0


def record_failure(ip, now=None):
    _fails.setdefault(ip, []).append(now or time.time())


def clear_failures(ip):
    _fails.pop(ip, None)


def needs_login(path, cookie_value):
    """True when this request must be rejected with 401."""
    if not required() or path in OPEN_PATHS:
        return False
    if not (path.startswith("/api/") or path in PROTECTED_EXTRA):
        return False  # the static front end itself is public; it shows the login screen
    return not (cookie_value and valid_token(cookie_value))
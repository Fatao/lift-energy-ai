"""LLM explanation layer: turns already-computed FACTS into plain language for the engineer.

The model never sees raw telemetry and is never asked to calculate or decide.
Safety net: every number in the answer must be traceable to the facts we sent. If the model
adds a number that is not in the facts (or is unreachable), we return a deterministic template
built from the same facts instead. So the UI can never show an invented figure.

Providers (set in .env, see .env.example):
  LLM_PROVIDER=gemini     GEMINI_API_KEY, [GEMINI_MODEL=gemini-3.8-flash]     (Google AI Studio key)
  LLM_PROVIDER=gigachat   GIGACHAT_AUTH_KEY, [GIGACHAT_SCOPE, GIGACHAT_MODEL, GIGACHAT_CA_BUNDLE | GIGACHAT_VERIFY_SSL=false]
  LLM_PROVIDER=ollama     [OLLAMA_URL=http://localhost:11434] OLLAMA_MODEL=qwen2.5:3b   (free, local)
  LLM_PROVIDER=openai     LLM_BASE_URL, LLM_API_KEY, LLM_MODEL   (any OpenAI-compatible API)
  (unset / none)          no AI; the UI hides the explain buttons

Several providers at once: LLM_PROVIDER=gemini,gigachat  (tried in this order; if the first one fails
or is not configured, the next one answers). "Test connection" checks every one of them.
"""
import json
import re
import threading
import time
import uuid

import httpx

from . import analytics, config
from .i18n import norm, tr

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_SECRET_KEYS = ("GEMINI_API_KEY", "GIGACHAT_AUTH_KEY", "LLM_API_KEY", "MQTT_PASSWORD")


# ---------------------------------------------------------------- provider config
KNOWN = ("gemini", "gigachat", "ollama", "openai")
_last = {"provider": None}  # which provider gave the latest answer
_down = {}                   # provider -> time until which it is skipped after a failure
COOLDOWN = 120               # seconds


def providers():
    """Providers from LLM_PROVIDER, in order. 'gemini,gigachat' -> ['gemini', 'gigachat']."""
    raw = (config.env("LLM_PROVIDER", "none") or "none").lower()
    out = []
    for part in re.split(r"[,+;\s]+", raw):
        if part in KNOWN and part not in out:
            out.append(part)
    return out


def provider():
    ps = providers()
    return "+".join(ps) if ps else "none"


def model_name(p=None):
    if p is None:
        ps = providers()
        if len(ps) != 1:
            return " + ".join(model_name(x) or x for x in ps) or None
        p = ps[0]
    if p == "gemini":
        return config.env("GEMINI_MODEL", "gemini-3.8-flash")
    if p == "gigachat":
        return config.env("GIGACHAT_MODEL", "GigaChat")
    if p == "ollama":
        return config.env("OLLAMA_MODEL", "qwen2.5:3b")
    if p == "openai":
        return config.env("LLM_MODEL", "")
    return None


def is_configured(p):
    return {
        "gemini": bool(config.env("GEMINI_API_KEY")),
        "gigachat": bool(config.env("GIGACHAT_AUTH_KEY")),
        "ollama": True,
        "openai": bool(config.env("LLM_BASE_URL") and config.env("LLM_MODEL")),
    }.get(p, False)


def status():
    ps = providers()
    return {"provider": provider(), "model": model_name(), "configured": any(is_configured(p) for p in ps),
            "providers": [{"provider": p, "model": model_name(p), "configured": is_configured(p)} for p in ps]}


def _scrub(text):
    """Never let a secret leave the server inside an error message."""
    text = str(text)
    for k in _SECRET_KEYS:
        v = config.env(k)
        if v and len(v) > 6:
            text = text.replace(v, "***")
    return text


# ---------------------------------------------------------------- GigaChat auth
_tok = {"value": None, "exp": 0.0}
_tok_lock = threading.Lock()


def _verify():
    bundle = config.env("GIGACHAT_CA_BUNDLE")
    if bundle:
        return bundle
    return config.env("GIGACHAT_VERIFY_SSL", "true").lower() != "false"


def _gigachat_token():
    with _tok_lock:
        if _tok["value"] and time.time() < _tok["exp"] - 60:
            return _tok["value"]
        r = httpx.post(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={
                "Authorization": "Basic " + config.env("GIGACHAT_AUTH_KEY", ""),
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={"scope": config.env("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")},
            timeout=20, verify=_verify(),
        )
        r.raise_for_status()
        j = r.json()
        _tok["value"], _tok["exp"] = j["access_token"], j["expires_at"] / 1000.0
        return _tok["value"]


# ---------------------------------------------------------------- one chat call per provider
def _gemini_chat(messages):
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name()}:generateContent"
    headers = {"x-goog-api-key": config.env("GEMINI_API_KEY", ""), "Content-Type": "application/json"}

    def call(thinking):
        gen = {"temperature": 0.2, "maxOutputTokens": 2048}
        if thinking:  # newer Gemini models "think" before answering, which is slow: keep it short
            gen["thinkingConfig"] = {"thinkingLevel": thinking}
        body = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        r = httpx.post(url, headers=headers, json=body, timeout=120)
        r.raise_for_status()
        return r.json()

    try:
        j = call(config.env("GEMINI_THINKING", "low"))
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 400:
            raise
        j = call(None)  # this model does not know the thinking setting: ask without it
    cand = (j.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    if not text.strip():
        raise RuntimeError(f"empty answer from Gemini (finishReason={cand.get('finishReason')})")
    return text


def _chat_one(messages, p):
    """One chat completion with ONE provider. Returns the assistant text. Raises on any failure."""
    if p == "gemini":
        return _gemini_chat(messages)
    if p == "gigachat":
        r = httpx.post(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={"Authorization": "Bearer " + _gigachat_token(), "Accept": "application/json"},
            json={"model": model_name(p), "messages": messages, "temperature": 0.2, "max_tokens": 400},
            timeout=40, verify=_verify(),
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if p == "ollama":
        r = httpx.post(
            config.env("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/chat",
            json={"model": model_name(p), "messages": messages, "stream": False,
                  "options": {"temperature": 0.2}},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]
    if p == "openai":
        headers = {"Authorization": "Bearer " + config.env("LLM_API_KEY", "")} if config.env("LLM_API_KEY") else {}
        r = httpx.post(
            config.env("LLM_BASE_URL", "").rstrip("/") + "/chat/completions",
            headers=headers,
            json={"model": model_name(p), "messages": messages, "temperature": 0.2, "max_tokens": 400},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("LLM provider is not configured")


def _chat(messages):
    """Ask the configured providers in order; the first one that answers wins."""
    errors = []
    order = [p for p in providers() if is_configured(p)]
    now = time.time()
    # a provider that just failed (503 / timeout / quota) is skipped for COOLDOWN seconds, so the
    # next cards do not each wait for it again; if every provider is cooling we try them anyway
    ready = [p for p in order if _down.get(p, 0) <= now]
    for p in providers():
        if not is_configured(p):
            errors.append(f"{p}: no key")
    for p in (ready or order):
        try:
            text = _chat_one(messages, p)
            _last["provider"] = p
            _down.pop(p, None)
            return text
        except Exception as e:
            _down[p] = time.time() + COOLDOWN
            errors.append(f"{p}: {describe_error(e)}")
    _last["provider"] = None
    raise RuntimeError(" | ".join(errors) if errors else "LLM provider is not configured")


def describe_error(e):
    """Short, secret-free, human-readable reason for a failed call."""
    if isinstance(e, httpx.HTTPStatusError):
        body = e.response.text[:300].replace("\n", " ")
        return _scrub(f"HTTP {e.response.status_code}: {body}")
    text = _scrub(f"{type(e).__name__}: {e}")
    if "CERTIFICATE_VERIFY_FAILED" in text:
        text += " (set GIGACHAT_CA_BUNDLE to the Russian trusted root certificate, or GIGACHAT_VERIFY_SSL=false for a quick test)"
    return text


def test(lang="en"):
    """Real round trip with a tiny prompt for EVERY configured provider ('Test connection' button)."""
    st = status()
    out = {"provider": st["provider"], "model": st["model"], "ok": False, "ms": None, "message": "", "results": []}
    if not providers():
        out["message"] = tr(lang, "llm.test.none")
        return out
    t0 = time.time()
    parts = []
    for p in providers():
        r = {"provider": p, "model": model_name(p), "ok": False, "ms": None, "message": ""}
        if not is_configured(p):
            r["message"] = tr(lang, "llm.test.nokey")
        else:
            t1 = time.time()
            try:
                answer = _chat_one([{"role": "user", "content": "Reply with the single word OK."}], p)
                r.update(ok=True, ms=int((time.time() - t1) * 1000),
                         message=tr(lang, "llm.test.ok") + " " + answer.strip()[:80])
            except Exception as e:  # report every failure mode to the user instead of crashing
                r.update(ms=int((time.time() - t1) * 1000), message=describe_error(e))
        out["results"].append(r)
        parts.append(f"{p}: {'OK' if r['ok'] else 'FAILED'} - {r['message']}")
    out["ok"] = any(r["ok"] for r in out["results"])
    out["ms"] = int((time.time() - t0) * 1000)
    out["message"] = parts[0].split(": ", 1)[1].split(" - ", 1)[1] if len(parts) == 1 else "  |  ".join(parts)
    return out


# ---------------------------------------------------------------- number guard
def numbers(text, lang):
    """All numbers in a text, as floats. Handles '1 234,5' (ru) and '1,234.5' (en)."""
    text = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}(?!\d))", "", text)  # space as thousands separator
    if norm(lang) == "en":
        text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)             # comma as thousands separator
    return [float(m.replace(",", ".")) for m in _NUM.findall(text)]


def unverified_numbers(answer, facts_text, lang="ru"):
    """Numbers in the answer that cannot be traced to the facts (small integers <= 10 are free)."""
    known = numbers(facts_text, lang)
    bad = []
    for n in numbers(answer, lang):
        if n == int(n) and n <= 10:
            continue
        if any(abs(n - f) <= max(0.006 * abs(f), 0.0051) for f in known):
            continue
        bad.append(n)
    return bad


# ---------------------------------------------------------------- explanations
def _template_rec(rec, lang):
    saving = tr(lang, "llm.tpl.saving", v=rec["est_saving_rub_year"]) if rec.get("est_saving_rub_year") else ""
    return tr(lang, "llm.tpl.rec", lift=rec["lift_name"], title=rec["title"], text=rec["text"],
              evidence="; ".join(rec["evidence"]), saving=saving)


def _template_summary(facts, lang):
    g = facts["group"]
    parts = [tr(lang, "llm.tpl.summary1", days=facts["days"], kwh=g["total_kwh"], n=g["anomalies"])]
    if facts["recommendations"]:
        items = "; ".join(f"{r['lift_name']}: {r['title']}" for r in facts["recommendations"][:3])
        parts.append(tr(lang, "llm.tpl.summary2", items=items))
    else:
        parts.append(tr(lang, "llm.tpl.summary3"))
    parts.append(tr(lang, "llm.tpl.summary4"))
    return " ".join(parts)


def _ask(facts, template_text, task_key, lang):
    lang = norm(lang)
    facts_text = json.dumps(facts, ensure_ascii=False)
    base = {"text": template_text, "source": "template", "provider": provider(), "model": model_name(),
            "verified": True, "note": None}
    _last["provider"] = None
    if not status()["configured"]:
        base["note"] = tr(lang, "llm.note.not_configured")
        return base
    try:
        answer = _chat([
            {"role": "system", "content": tr(lang, "llm.system")},
            {"role": "user", "content": f"{tr(lang, task_key)}\n\n{tr(lang, 'llm.facts')}:\n{facts_text}"},
        ]).strip()
    except Exception as e:
        base["note"] = tr(lang, "llm.note.unavailable", err=describe_error(e))
        return base
    bad = unverified_numbers(answer, facts_text, lang)
    if bad or not answer:
        base["note"] = tr(lang, "llm.note.rejected", nums=", ".join(str(b) for b in bad[:5]))
        return base
    used = _last["provider"] or provider()
    return {"text": answer, "source": "llm", "provider": used, "model": model_name(used) if used in KNOWN else model_name(),
            "verified": True, "note": None}


def explain_recommendation(rec_id, days, tariff, method="stat", lang="ru"):
    recs = analytics.recommendations(days, tariff, method, lang)
    rec = next((r for r in recs if r["id"] == rec_id), None)
    if rec is None:
        return None
    facts = {k: rec[k] for k in ("lift_name", "title", "text", "evidence", "severity")}
    facts["est_saving_rub_year"] = rec.get("est_saving_rub_year")
    out = _ask(facts, _template_rec(rec, lang), "llm.task.rec", lang)
    out["id"] = rec_id
    return out


def explain_summary(days, tariff, method="stat", lang="ru"):
    ov = analytics.overview(days)
    if not ov["group"]:
        return None
    g = ov["group"]
    recs = analytics.recommendations(days, tariff, method, lang)
    facts = {
        "days": days,
        "group": {"total_kwh": g["total_kwh"], "anomalies": g["anomalies"],
                  "kwh_per_trip": g["kwh_per_trip"], "standby_share": g["standby_share"]},
        "recommendations": [
            {"lift_name": r["lift_name"], "title": r["title"], "evidence": r["evidence"]} for r in recs[:5]
        ],
    }
    out = _ask(facts, _template_summary(facts, lang), "llm.task.summary", lang)
    out["id"] = "summary"
    return out
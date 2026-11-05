import { useEffect, useState } from "react";
import { api } from "../api";
import type { Ctx } from "../ctx";
import { useI18n } from "../i18n";
import type { Explanation } from "../types";

/** Asks the backend to explain one recommendation (or the whole summary) in plain language. */
export default function ExplainBox({ id, ctx, label }: { id: string; ctx: Ctx; label?: string }) {
  const { t, lang } = useI18n();
  const [res, setRes] = useState<Explanation | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // the answer belongs to the settings it was asked with
  useEffect(() => { setRes(null); setErr(null); }, [id, ctx.days, ctx.tariff, ctx.method, ctx.version, lang]);

  const ask = async () => {
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.explain(id, ctx.days, ctx.tariff, ctx.method, lang));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!ctx.llmReady && !res) {
    return <p className="muted small-note explain-off">✦ {t("ex.off")}</p>;
  }
  return (
    <div className="explain">
      {!res && (
        <button className="btn ghost small" onClick={ask} disabled={busy}>
          {busy ? t("ex.busy") : `✦ ${label ?? t("ex.btn")}`}
        </button>
      )}
      {err && <p className="err">{err}</p>}
      {res && (
        <div className="explain-text">
          <span className={`badge ${res.source === "llm" ? "low" : "ok"}`}>
            {res.source === "llm" ? t("ex.ai", { m: res.model ?? res.provider }) : t("ex.tpl")}
          </span>{" "}
          {res.text}
          {res.note && <div className="muted small-note">{res.note}</div>}
          <div className="muted small-note">{t("ex.check")}</div>
        </div>
      )}
    </div>
  );
}

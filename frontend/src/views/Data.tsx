import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import type { ImportOptions } from "../api";
import type { Ctx } from "../ctx";
import { useI18n } from "../i18n";
import type { Key } from "../i18n";
import type { ImportSummary, IngestStatus, LlmStatus, LlmTest, MapField } from "../types";
import { useAsync } from "../util";

const TEMPLATE = "lift_id,ts,kwh,trips,door_cycles,name\nA1,2026-10-01 08:00,1.34,12,25,Lift A1\nA1,2026-10-01 09:00,0.82,6,13,Lift A1\n";
const FIELDS: MapField[] = ["lift_id", "name", "ts", "kwh", "trips", "door_cycles"];
const FIELD_KEY: Record<MapField, Key> = {
  lift_id: "data.map.lift", name: "data.map.name", ts: "data.map.ts", kwh: "data.map.kwh", trips: "data.map.trips", door_cycles: "data.map.door_cycles",
};
const stateBadge = (s: string) => (s === "connected" ? "ok" : s === "error" ? "high" : "medium");

function Sources() {
  const { t } = useI18n();
  const [st, setSt] = useState<IngestStatus | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.ingestStatus().then((s) => alive && setSt(s)).catch(() => undefined);
    load();
    const id = setInterval(load, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  const entries = st ? Object.entries(st.sources) : [];
  return (
    <div className="card">
      <h3>{t("data.sources")}</h3>
      {entries.length === 0 ? <p className="muted" style={{ margin: 0 }}>{t("data.nolive")}</p> : (
        <div className="scroll"><table>
          <thead><tr><th>{t("data.source")}</th><th>{t("data.state")}</th><th className="n">{t("data.msgs")}</th><th className="n">{t("data.errs")}</th><th>{t("data.last")}</th></tr></thead>
          <tbody>
            {entries.map(([name, s]) => (
              <tr key={name}>
                <td><strong>{name === "mqtt" ? "MQTT" : name === "modbus" ? "Modbus RTU / RS-485" : name}</strong><div className="muted small-note">{s.detail}</div></td>
                <td><span className={`badge ${stateBadge(s.state)}`}>{s.state}</span></td>
                <td className="n">{s.messages}</td><td className="n">{s.errors}</td>
                <td>{s.last_message?.replace("T", " ") ?? "—"}{s.last_error && <div className="err small-note">{s.last_error}</div>}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </div>
  );
}

function Llm() {
  const { t, lang } = useI18n();
  const [st, setSt] = useState<LlmStatus | null>(null);
  const [res, setRes] = useState<LlmTest | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.llmStatus().then(setSt).catch(() => undefined); }, []);
  const run = async () => {
    setBusy(true);
    setRes(null);
    try { setRes(await api.llmTest(lang)); }
    catch (e) { setRes({ provider: st?.provider ?? "", model: st?.model ?? null, ok: false, ms: null, message: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(false); }
  };
  return (
    <div className="card">
      <h3>{t("data.llm")}</h3>
      <div className="row">
        <span className="muted">{t("data.llm.provider")}:</span> <strong>{st?.provider ?? "…"}</strong>
        <span className="muted">{t("data.llm.model")}:</span> <strong>{st?.model ?? "—"}</strong>
        <span className={`badge ${st?.configured ? "ok" : "medium"}`}>{st?.configured ? t("data.llm.ready") : t("data.llm.no")}</span>
        <button className="btn small" onClick={run} disabled={busy}>{busy ? t("data.llm.testing") : t("data.llm.test")}</button>
      </div>
      {res && <p className={res.ok ? "ok-text" : "err"}>{res.ok ? "✔" : "✖"} {res.message}{res.ms != null && ` (${res.ms} ms)`}</p>}
      <p className="muted small-note" style={{ marginBottom: 0 }}>{t("data.llm.hint")}</p>
    </div>
  );
}

function Importer({ ctx }: { ctx: Ctx }) {
  const { t, lang, n } = useI18n();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [opts, setOpts] = useState<ImportOptions>({ replace: false, cumulative: false, liftId: "", mapping: null });
  const [sum, setSum] = useState<ImportSummary | null>(null);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const preview = async (o: ImportOptions, f: File | null = file) => {
    if (!f) { setErr(t("data.nofile")); return; }
    setBusy(true); setErr(null); setDone(false);
    try { setSum(await api.importPreview(f, lang, o)); }
    catch (e) {
      setSum(e instanceof ApiError ? e.summary : null);
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };
  const apply = async () => {
    if (!file) { setErr(t("data.nofile")); return; }
    setBusy(true); setErr(null);
    try {
      setSum(await api.importApply(file, lang, opts));
      setDone(true);
      ctx.onDataChanged();
    } catch (e) {
      setSum(e instanceof ApiError ? e.summary : null);
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };
  const setMap = (field: MapField, value: string) => {
    const cur = opts.mapping ?? (sum ? { ...sum.mapping } : {});
    const next = { ...opts, mapping: { ...cur, [field]: value === "" ? null : Number(value) } as Record<string, number | null> };
    setOpts(next);
    preview(next);
  };
  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + TEMPLATE], { type: "text/csv" }));
    a.download = "template.csv";
    a.click();
  };

  return (
    <div className="card">
      <h3>{t("data.import")}</h3>
      <p className="muted" style={{ marginTop: 0 }}>{t("data.import.hint")}</p>
      <div className="row">
        <input type="file" ref={fileRef} accept=".xlsx,.xlsm,.csv,text/csv" aria-label={t("data.pick")}
          onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); setSum(null); setDone(false); setErr(null); setOpts({ ...opts, mapping: null }); if (f) preview({ ...opts, mapping: null }, f); }} />
        <button className="btn ghost small" onClick={download}>{t("data.template")}</button>
      </div>
      <div className="row">
        <label className="check"><input type="checkbox" checked={opts.cumulative} onChange={(e) => { const o = { ...opts, cumulative: e.target.checked }; setOpts(o); if (file) preview(o); }} /> {t("data.cumulative")}</label>
        <label className="check"><input type="checkbox" checked={opts.replace} onChange={(e) => setOpts({ ...opts, replace: e.target.checked })} /> {t("data.replace")}</label>
      </div>
      <div className="row">
        <label className="stack">{t("data.defaultlift")}
          <input type="text" value={opts.liftId} onChange={(e) => setOpts({ ...opts, liftId: e.target.value })}
            onBlur={() => file && preview(opts)} placeholder="L1" />
        </label>
      </div>

      {sum && (
        <>
          <h4 className="sub-h">{t("data.map")}</h4>
          <div className="map-grid">
            {FIELDS.map((f) => (
              <label key={f} className="stack">{t(FIELD_KEY[f])}
                <select value={sum.mapping[f] ?? ""} onChange={(e) => setMap(f, e.target.value)}>
                  <option value="">{t("data.map.none")}</option>
                  {sum.headers.map((h, i) => <option key={i} value={i}>{h || `#${i + 1}`}</option>)}
                </select>
              </label>
            ))}
          </div>
          {sum.sample.length > 0 && (
            <div className="scroll"><table className="sample">
              <thead><tr>{sum.headers.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
              <tbody>{sum.sample.map((r, i) => <tr key={i}>{sum.headers.map((_, j) => <td key={j}>{r[j] ?? ""}</td>)}</tr>)}</tbody>
            </table></div>
          )}
        </>
      )}

      {err && <p className="err">{err}</p>}
      {sum?.warnings.map((w) => <p key={w} className="warn">⚠ {w}</p>)}
      {sum?.hours != null && (
        <p className={done ? "ok-text" : ""}>
          {done && <strong>✔ {t("data.done")} </strong>}
          {t("data.result", { rows: n(sum.rows_used ?? 0, 0), hours: n(sum.hours, 0), n: sum.lifts?.length ?? 0, lifts: (sum.lifts ?? []).join(", "), a: sum.first?.replace("T", " ").slice(0, 16) ?? "", b: sum.last?.replace("T", " ").slice(0, 16) ?? "" })}
        </p>
      )}
      {sum?.skipped && Object.keys(sum.skipped).length > 0 && (
        <p className="muted small-note">{t("data.skipped")}: {Object.entries(sum.skipped).map(([k, v]) =>
          `${t(`data.skip.${k}` as Key)}: ${v} (${t("data.skip.rows")} ${(sum.skipped_rows?.[k] ?? []).join(", ")}${v > 5 ? "…" : ""})`).join(" · ")}</p>
      )}
      <div className="row">
        <button className="btn" onClick={apply} disabled={busy || !file || sum?.hours == null}>{t("data.apply")}</button>
      </div>
    </div>
  );
}

function Lifts({ ctx }: { ctx: Ctx }) {
  const { t } = useI18n();
  const [edit, setEdit] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (ctx.lifts.length === 0) return null;
  const save = async (id: string) => {
    try { await api.renameLift(id, name); setEdit(null); ctx.onDataChanged(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  const del = async (id: string) => {
    if (!window.confirm(t("data.delete.confirm"))) return;
    try { await api.deleteLift(id); ctx.onDataChanged(); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className="card">
      <h3>{t("data.lifts")}</h3>
      <table>
        <tbody>
          {ctx.lifts.map((l) => (
            <tr key={l.id}>
              <td className="mono">{l.id}</td>
              <td>{edit === l.id
                ? <input type="text" value={name} autoFocus onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save(l.id)} />
                : l.name}</td>
              <td className="n">
                {edit === l.id
                  ? <button className="btn small" onClick={() => save(l.id)}>{t("data.save")}</button>
                  : <button className="btn ghost small" onClick={() => { setEdit(l.id); setName(l.name); }}>{t("data.rename")}</button>}{" "}
                <button className="btn danger small" onClick={() => del(l.id)}>{t("data.delete")}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {err && <p className="err">{err}</p>}
    </div>
  );
}

export default function Data({ ctx }: { ctx: Ctx }) {
  const { t } = useI18n();
  const [msg, setMsg] = useState("");
  const last = useAsync(() => api.ingestStatus(), [ctx.version]);
  return (
    <div className="stackv">
      <div className="grid two"><Sources /><Llm /></div>
      <Importer ctx={ctx} />
      <Lifts ctx={ctx} />
      <div className="card">
        <h3>{t("data.db")}</h3>
        <p className="muted" style={{ marginTop: 0 }}>{t("data.lastrec")}: {last.data?.last_ts?.replace("T", " ") ?? "—"}. {t("data.demo.note")}</p>
        <div className="row">
          <a className="btn ghost small" href={api.readingsCsvUrl}>{t("data.export")}</a>
          <button className="btn ghost small" onClick={async () => { await api.resetDemo(); ctx.onDataChanged(); setMsg(t("data.demo.done")); }}>{t("data.demo.reset")}</button>
          <button className="btn danger small" onClick={async () => { if (window.confirm(t("data.clear.confirm"))) { await api.clear(); ctx.onDataChanged(); setMsg(t("data.cleared")); } }}>{t("data.clear")}</button>
          <span className="muted">{msg}</span>
        </div>
      </div>
    </div>
  );
}

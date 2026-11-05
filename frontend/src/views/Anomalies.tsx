import { useMemo, useState } from "react";
import { api } from "../api";
import type { Ctx } from "../ctx";
import { useI18n } from "../i18n";
import type { Hourly } from "../types";
import { Badge, ChartView, Status, cssVar, seriesColor, useAsync } from "../util";

function HourChart({ h }: { h: Hourly }) {
  const { t } = useI18n();
  const cfg = useMemo(() => {
    const marks = h.ts.map((_, i) => (h.anomaly_idx.includes(i) ? h.kwh[i] : null));
    return {
      type: "line",
      data: {
        labels: h.ts.map((x) => `${x.slice(8, 10)}.${x.slice(5, 7)} ${x.slice(11, 13)}:00`),
        datasets: [
          { label: t("an.fact"), data: h.kwh, borderColor: seriesColor(0), borderWidth: 1.6, pointRadius: 0, tension: 0.1 },
          { label: t("an.expected"), data: h.expected, borderColor: cssVar("--muted"), borderDash: [5, 4], borderWidth: 1.4, pointRadius: 0 },
          { label: t("an.point"), data: marks, borderColor: cssVar("--alert"), backgroundColor: cssVar("--alert"), showLine: false, pointRadius: 6 },
        ],
      },
      options: { scales: { x: { ticks: { maxTicksLimit: 10 } } }, plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } } } },
    };
  }, [h, t]);
  return <ChartView config={cfg} />;
}

export default function Anomalies({ ctx }: { ctx: Ctx }) {
  const { t, n, rub, lang } = useI18n();
  const [lift, setLift] = useState("");
  const selected = ctx.lifts.some((l) => l.id === lift) ? lift : ctx.lifts[0]?.id ?? "";
  const hDays = Math.min(ctx.days, 14);
  const hourly = useAsync(() => (selected ? api.hourly(selected, hDays, ctx.method) : Promise.reject(new Error(t("an.nolifts")))),
    [selected, hDays, ctx.method, ctx.version, lang]);
  const events = useAsync(() => api.anomalies(ctx.days, ctx.method, lang), [ctx.days, ctx.method, ctx.version, lang]);

  return (
    <>
      <div className="card">
        <h3>
          {t("an.chart")}{" "}
          <select value={selected} onChange={(e) => setLift(e.target.value)}>
            {ctx.lifts.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </h3>
        <p className="muted" style={{ marginTop: 0 }}>
          {t("an.method")}: <strong>{ctx.method === "ml" ? t("ctl.ml") : t("ctl.stat")}</strong>. {t("an.hint", { n: hDays })}
        </p>
        <Status s={hourly}>{(h) => <HourChart h={h} />}</Status>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h3>{t("an.events", { n: ctx.days })}</h3>
        <Status s={events}>{(ev) =>
          ev.length === 0 ? <p className="muted">{t("an.none")}</p> : (
            <div className="scroll">
              <table>
                <thead><tr><th>{t("col.lift")}</th><th>{t("an.start")}</th><th className="n">{t("an.hours")}</th><th>{t("an.type")}</th>
                  <th className="n">{t("an.extra")}</th><th className="n">{t("an.cost")}</th><th>{t("an.sev")}</th></tr></thead>
                <tbody>
                  {ev.map((e) => (
                    <tr key={e.lift_id + e.start}>
                      <td>{e.lift_name}</td><td>{e.start.replace("T", " ").slice(0, 16)}</td><td className="n">{e.hours}</td>
                      <td>{e.kind_text}</td><td className="n">{n(e.extra_kwh, 2)}</td>
                      <td className="n">{rub(e.extra_kwh * ctx.tariff)}</td><td><Badge sev={e.severity} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Status>
      </div>
    </>
  );
}

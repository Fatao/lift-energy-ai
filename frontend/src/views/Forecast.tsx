import { useMemo, useState } from "react";
import { api } from "../api";
import type { Ctx } from "../ctx";
import { useI18n } from "../i18n";
import type { Forecast as ForecastData } from "../types";
import { ChartView, Status, cssVar, seriesColor, shortDate, useAsync } from "../util";

function Body({ f }: { f: ForecastData }) {
  const { t, n } = useI18n();
  const cfg = useMemo(() => {
    const nH = f.history.length;
    const pad = (a: number[]) => [...Array<null>(nH).fill(null), ...a];
    const brass = cssVar("--accent");
    return {
      type: "line",
      data: {
        labels: [...f.history.map((x) => shortDate(x.date)), ...f.forecast.map((x) => shortDate(x.date))],
        datasets: [
          { label: t("fc.hist"), data: [...f.history.map((x) => x.kwh), ...Array<null>(f.forecast.length).fill(null)], borderColor: seriesColor(1), backgroundColor: seriesColor(1), pointRadius: 2.5, tension: 0.25, borderWidth: 2 },
          { label: t("fc.fc"), data: [...Array<null>(Math.max(nH - 1, 0)).fill(null), f.history[nH - 1]?.kwh ?? null, ...f.forecast.map((x) => x.kwh)], borderColor: brass, backgroundColor: brass, borderDash: [6, 4], pointRadius: 3, tension: 0.25, borderWidth: 2 },
          { label: t("fc.low"), data: pad(f.forecast.map((x) => x.low)), borderColor: "transparent", pointRadius: 0, fill: false },
          { label: t("fc.band"), data: pad(f.forecast.map((x) => x.high)), borderColor: "transparent", backgroundColor: brass + "30", pointRadius: 0, fill: "-1" },
        ],
      },
      options: { plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, filter: (i: { text: string }) => i.text !== t("fc.low") } } } },
    };
  }, [f, t]);
  const diff = f.last7_actual ? (f.next7_forecast / f.last7_actual - 1) * 100 : 0;
  const bt = f.backtest;
  return (
    <>
      <div className="grid kpis three">
        <div className="card kpi"><div className="l">{t("fc.last7")}</div><div className="v">{n(f.last7_actual)} <small>{t("unit.kwh")}</small></div></div>
        <div className="card kpi"><div className="l">{t("fc.next7")}</div><div className="v">{n(f.next7_forecast)} <small>{t("unit.kwh")}</small></div><div className="sub">{diff > 0 ? "+" : ""}{n(diff, 1)}%</div></div>
        <div className="card kpi"><div className="l">{t("fc.model")}</div><div className="v small">{f.model_name}</div></div>
      </div>
      <div className="card">
        <h3>{t("fc.chart")}</h3>
        <ChartView config={cfg} />
        <p className="muted">{f.method}</p>
      </div>
      {bt && (
        <div className="card" style={{ marginTop: 16 }}>
          <h3>{t("fc.backtest", { n: bt.days })}</h3>
          <p className="muted" style={{ marginTop: 0 }}>{t("fc.backtest.hint")}</p>
          <table>
            <thead><tr><th>{t("fc.model.col")}</th><th className="n">{t("fc.mae")}</th><th /></tr></thead>
            <tbody>
              {Object.entries(bt.mae_kwh).sort((a, b) => a[1] - b[1]).map(([k, v]) => (
                <tr key={k}><td>{bt.names[k]}</td><td className="n">{n(v, 3)}</td>
                  <td>{k === f.model && <span className="badge ok">{t("fc.chosen")}</span>}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function Forecast({ ctx }: { ctx: Ctx }) {
  const { t, lang } = useI18n();
  const [lift, setLift] = useState("");
  const selected = ctx.lifts.some((l) => l.id === lift) ? lift : ctx.lifts[0]?.id ?? "";
  const s = useAsync(() => (selected ? api.forecast(selected, lang) : Promise.reject(new Error(t("an.nolifts")))), [selected, ctx.version, lang]);
  return (
    <>
      <div className="row"><strong>{t("fc.lift")}:</strong>
        <select value={selected} onChange={(e) => setLift(e.target.value)}>
          {ctx.lifts.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
      </div>
      <Status s={s}>{(f) => (f.error ? <p className="err">{f.error}</p> : <Body f={f} />)}</Status>
    </>
  );
}

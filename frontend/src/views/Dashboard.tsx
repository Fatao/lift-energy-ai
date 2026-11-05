import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import ExplainBox from "../components/ExplainBox";
import type { Ctx } from "../ctx";
import { useI18n } from "../i18n";
import type { LiftSummary, Overview, Series } from "../types";
import { ChartView, SevenSeg, Status, StatusLed, seriesColor, shortDate, useAsync } from "../util";

const FULL_DAY_HOURS = 20; // a day with fewer hours of data is "not finished" and is not drawn as a drop

function Kpi({ v, l, sub }: { v: string; l: string; sub: string }) {
  return (
    <div className="card kpi">
      <div className="l">{l}</div>
      <div className="v">{v}</div>
      <div className="sub">{sub}</div>
    </div>
  );
}

function FleetBoard({ lifts }: { lifts: LiftSummary[] }) {
  const { t } = useI18n();
  return (
    <div className="card board">
      <h3>{t("dash.board")} <span className="hint">{t("dash.board.hint")}</span></h3>
      <div className="board-grid">
        {lifts.map((l) => (
          <div key={l.lift_id} className={`panel ${l.status ?? "ok"}`}>
            <div className="panel-top"><span className="panel-name">{l.name}</span><StatusLed status={l.status ?? "ok"} /></div>
            <SevenSeg value={l.avg_kwh_per_day ?? null} digits={4} decimals={1} />
            <div className="panel-foot">
              <span>{t("unit.kwh")}/24h</span>
              <span>{l.recent_anomalies ? `⚠ ${l.recent_anomalies}` : ""}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Charts({ ser }: { ser: Series[] }) {
  const { t, n } = useI18n();
  const [lift, setLift] = useState(ser[0]?.lift_id ?? "");
  useEffect(() => { if (!ser.some((s) => s.lift_id === lift)) setLift(ser[0]?.lift_id ?? ""); }, [ser, lift]);

  // days that are not finished yet are cut off the line (they would look like a sudden drop)
  const { daily, partial } = useMemo(() => {
    const longest = ser.reduce((a, b) => (b.dates.length > a.dates.length ? b : a), ser[0]);
    const keep = longest.dates.map((_, i) => (longest.hours?.[i] ?? 24) >= FULL_DAY_HOURS);
    const idx = keep.map((k, i) => (k ? i : -1)).filter((i) => i >= 0);
    const last = longest.dates.length - 1;
    const part = !keep[last] ? { h: longest.hours[last], kwh: ser.reduce((a, s) => a + (s.kwh[last] ?? 0), 0) } : null;
    return {
      partial: part,
      daily: {
        type: "line",
        data: {
          labels: idx.map((i) => shortDate(longest.dates[i])),
          datasets: ser.map((s, k) => ({
            label: s.name,
            data: idx.map((i) => (i < s.dates.length ? s.kwh[i] : null)),
            borderColor: seriesColor(k), backgroundColor: seriesColor(k), borderWidth: 2, tension: 0.3, pointRadius: 2.5,
          })),
        },
        options: { plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } } }, scales: { y: { beginAtZero: true } } },
      },
    };
  }, [ser]);

  const cur = ser.find((s) => s.lift_id === lift) ?? ser[0];
  const prof = useMemo(() => ({
    type: "bar",
    data: {
      labels: Array.from({ length: 24 }, (_, h) => `${h}`),
      datasets: [{ label: cur.name, data: cur.hour_profile, backgroundColor: seriesColor(0), borderRadius: 3 }],
    },
    options: { plugins: { legend: { display: false } } },
  }), [cur]);

  return (
    <>
      <div className="grid two">
        <div className="card"><h3>{t("dash.daily")}</h3><ChartView config={daily} />
          {partial && <p className="muted small-note">{t("dash.daily.note", { h: partial.h, kwh: n(partial.kwh, 1) })}</p>}</div>
        <div className="card">
          <h3>{t("dash.profile")}{" "}
            <select value={lift} onChange={(e) => setLift(e.target.value)}>
              {ser.map((s) => <option key={s.lift_id} value={s.lift_id}>{s.name}</option>)}
            </select>
          </h3>
          <ChartView config={prof} />
        </div>
      </div>
    </>
  );
}

function Body({ ov, ser, ctx }: { ov: Overview; ser: Series[]; ctx: Ctx }) {
  const { t, n, rub } = useI18n();
  const g = ov.group;
  if (!g) return <div className="card empty"><p>{t("dash.empty")}</p><button className="btn" onClick={ctx.goData}>{t("nav.data")} →</button></div>;
  return (
    <>
      <FleetBoard lifts={ov.lifts} />
      <div className="grid kpis">
        <Kpi l={t("dash.kpi.total", { n: ctx.days })} v={`${n(g.total_kwh, 0)} ${t("unit.kwh")}`} sub={t("dash.kpi.total.l", { rub: rub(g.total_kwh * ctx.tariff) })} />
        <Kpi l={t("dash.kpi.trip")} v={n(g.kwh_per_trip, 3)} sub={t("dash.kpi.trip.l")} />
        <Kpi l={t("dash.kpi.standby")} v={g.standby_share == null ? "—" : `${n(g.standby_share * 100, 0)}%`} sub={t("dash.kpi.standby.l")} />
        <Kpi l={t("dash.kpi.anom")} v={String(g.anomalies)} sub={t("dash.kpi.anom.l")} />
        <Kpi l={t("dash.kpi.compl")} v={`${n(g.completeness * 100, 0)}%`} sub={t("dash.kpi.compl.l")} />
      </div>
      <div className="card" style={{ marginBottom: 16 }}>
        <h3>{t("dash.summary")}</h3>
        <ExplainBox id="summary" ctx={ctx} label={t("ex.summary")} />
      </div>
      {ser.length > 0 && <Charts ser={ser} />}
      <div className="card" style={{ marginTop: 16 }}>
        <h3>{t("dash.table")}</h3>
        <div className="scroll">
          <table>
            <thead>
              <tr><th>{t("col.lift")}</th><th>{t("col.state")}</th><th className="n">{t("col.kwh")}</th><th className="n">{t("col.trips")}</th>
                <th className="n">{t("col.kwhtrip")}</th><th className="n">{t("col.standby")}</th><th className="n">{t("col.anom")}</th><th className="n">{t("col.compl")}</th></tr>
            </thead>
            <tbody>
              {ov.lifts.map((l) => (
                <tr key={l.lift_id}>
                  <td>{l.name}</td><td><StatusLed status={l.status ?? "ok"} /></td>
                  <td className="n">{n(l.total_kwh)}</td><td className="n">{n(l.trips, 0)}</td>
                  <td className="n">{n(l.kwh_per_trip, 3)}</td><td className="n">{n(l.standby_kw, 2)}</td>
                  <td className="n"><span className={`badge ${l.anomalies ? "high" : "ok"}`}>{l.anomalies}</span></td>
                  <td className="n">{n(l.completeness * 100, 0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

export default function Dashboard({ ctx }: { ctx: Ctx }) {
  const ov = useAsync(() => api.overview(ctx.days), [ctx.days, ctx.version]);
  const ser = useAsync(() => api.series(ctx.days), [ctx.days, ctx.version]);
  return (
    <Status s={ov}>{(o) => (
      <Status s={ser}>{(s) => <Body ov={o} ser={s} ctx={ctx} />}</Status>
    )}</Status>
  );
}

import { useMemo } from "react";
import { api } from "../api";
import type { Ctx } from "../ctx";
import { useI18n } from "../i18n";
import type { Compare as CompareData, CompareRow } from "../types";
import { ChartView, Status, cssVar, seriesColor, useAsync } from "../util";

const dev = (v: number | null | undefined) =>
  v == null ? "—" : <span className={v > 15 ? "dev-bad" : "dev-ok"}>{v > 0 ? "+" : ""}{v}%</span>;

function Bar({ rows, k, devKey, median }: { rows: CompareRow[]; k: "standby_kw" | "marginal_kwh_per_trip"; devKey: "standby_kw_dev" | "marginal_kwh_per_trip_dev"; median: string }) {
  const { t } = useI18n();
  const cfg = useMemo(() => ({
    type: "bar",
    data: {
      labels: rows.map((l) => l.name),
      datasets: [{ data: rows.map((l) => l[k]), borderRadius: 4,
        backgroundColor: rows.map((l) => ((l[devKey] ?? 0) > 15 ? cssVar("--alert") : seriesColor(0))) }],
    },
    options: { plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: () => `${t("cmp.med")}: ${median}` } } } },
  }), [rows, k, devKey, median, t]);
  return <ChartView config={cfg} />;
}

function Body({ c }: { c: CompareData }) {
  const { t, n } = useI18n();
  if (!c.medians) {
    return <div className="card"><p className="muted" style={{ margin: 0 }}>{t("cmp.need")} {c.skipped.length > 0 && t("cmp.notready", { list: c.skipped.join(", ") })}</p></div>;
  }
  const m = c.medians;
  return (
    <>
      <div className="card">
        <h3>{t("cmp.title")}</h3>
        <p className="muted" style={{ marginTop: 0 }}>{t("cmp.hint")}</p>
        <div className="scroll">
          <table>
            <thead><tr><th>{t("col.lift")}</th><th className="n">{t("cmp.standby")}</th><th className="n">{t("cmp.vs")}</th>
              <th className="n">{t("cmp.marginal")}</th><th className="n">{t("cmp.vs")}</th><th className="n">{t("cmp.total")}</th></tr></thead>
            <tbody>
              {c.lifts.map((l) => (
                <tr key={l.lift_id}>
                  <td>{l.name}</td><td className="n">{n(l.standby_kw, 3)}</td><td className="n">{dev(l.standby_kw_dev)}</td>
                  <td className="n">{n(l.marginal_kwh_per_trip, 4)}</td><td className="n">{dev(l.marginal_kwh_per_trip_dev)}</td>
                  <td className="n">{n(l.kwh_per_trip, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted">{t("cmp.median", { a: n(m.standby_kw, 3), b: n(m.marginal_kwh_per_trip, 4) })}
          {c.skipped.length > 0 && ` · ${t("cmp.excluded", { list: c.skipped.join(", ") })}`}</p>
      </div>
      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="card"><h3>{t("cmp.c1")}</h3>
          <Bar rows={c.lifts} k="standby_kw" devKey="standby_kw_dev" median={n(m.standby_kw, 3)} /></div>
        <div className="card"><h3>{t("cmp.c2")}</h3>
          <Bar rows={c.lifts} k="marginal_kwh_per_trip" devKey="marginal_kwh_per_trip_dev" median={n(m.marginal_kwh_per_trip, 4)} /></div>
      </div>
    </>
  );
}

export default function Compare({ ctx }: { ctx: Ctx }) {
  const s = useAsync(() => api.compare(ctx.days), [ctx.days, ctx.version]);
  return <Status s={s}>{(c) => <Body c={c} />}</Status>;
}

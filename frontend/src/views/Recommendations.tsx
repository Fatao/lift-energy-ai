import { api } from "../api";
import ExplainBox from "../components/ExplainBox";
import type { Ctx } from "../ctx";
import { useI18n } from "../i18n";
import { Badge, Status, useAsync } from "../util";

export default function Recommendations({ ctx }: { ctx: Ctx }) {
  const { t, rub, lang } = useI18n();
  const s = useAsync(() => api.recommendations(ctx.days, ctx.tariff, ctx.method, lang), [ctx.days, ctx.tariff, ctx.method, ctx.version, lang]);
  return (
    <Status s={s}>{(r) => {
      if (!r.length) return <div className="card"><p className="muted" style={{ margin: 0 }}>{t("rec.none")}</p></div>;
      const total = r.reduce((a, x) => a + (x.est_saving_rub_year ?? 0), 0);
      return (
        <>
          <div className="card rec-head">
            <div>
              <strong>{t("rec.count", { n: r.length, days: ctx.days })}</strong>
              {total > 0 && <> · {t("rec.potential")}: <strong>{rub(total)}</strong>{" "}
                <span className="muted">({t("rec.assump", { t: ctx.tariff })})</span></>}
            </div>
            <div className="row no-print" style={{ margin: 0 }}>
              <a className="btn ghost small" href={api.recsCsvUrl(ctx.days, ctx.tariff, ctx.method, lang)}>{t("rec.csv")}</a>
              <button className="btn ghost small" onClick={() => window.print()}>{t("rec.print")}</button>
            </div>
          </div>
          {r.map((x) => (
            <div key={x.id} className={`card rec ${x.severity}`}>
              <h4><Badge sev={x.severity} /> {x.lift_name} — {x.title}</h4>
              <div>{x.text}</div>
              <ul>{x.evidence.map((e) => <li key={e}>{e}</li>)}</ul>
              {x.est_saving_rub_year != null && <div className="save">{t("rec.saving", { v: rub(x.est_saving_rub_year) })}</div>}
              <div className="no-print"><ExplainBox id={x.id} ctx={ctx} /></div>
            </div>
          ))}
        </>
      );
    }}</Status>
  );
}

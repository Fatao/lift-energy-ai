import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { api, AUTH_EVENT } from "./api";
import type { AuthStatus } from "./api";
import type { Ctx } from "./ctx";
import { I18nCtx, makeI18n } from "./i18n";
import type { Key, Lang } from "./i18n";
import type { LiftInfo, Method } from "./types";
import { ThemeCtx } from "./util";
import type { Theme } from "./util";
import Anomalies from "./views/Anomalies";
import Compare from "./views/Compare";
import Dashboard from "./views/Dashboard";
import Data from "./views/Data";
import Forecast from "./views/Forecast";
import Login from "./views/Login";
import Recommendations from "./views/Recommendations";

const TABS: { id: string; label: Key; View: (p: { ctx: Ctx }) => JSX.Element }[] = [
  { id: "dashboard", label: "nav.dashboard", View: Dashboard },
  { id: "anomalies", label: "nav.anomalies", View: Anomalies },
  { id: "compare", label: "nav.compare", View: Compare },
  { id: "forecast", label: "nav.forecast", View: Forecast },
  { id: "recs", label: "nav.recs", View: Recommendations },
  { id: "data", label: "nav.data", View: Data },
];

const DEMO_IDS = ["L1", "L2", "L3", "L4"];

function stored(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function store(key: string, v: string) {
  try { localStorage.setItem(key, v); } catch { /* private mode: setting just is not remembered */ }
}

export default function App() {
  const [lang, setLang] = useState<Lang>(() => (stored("lang") === "en" ? "en" : "ru"));
  const [theme, setTheme] = useState<Theme>(() => {
    const s = stored("theme");
    if (s === "light" || s === "dark") return s;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [tab, setTab] = useState("dashboard");
  const [days, setDays] = useState(14);
  const [tariffInput, setTariffInput] = useState("8");
  const [tariff, setTariff] = useState(8);
  const [method, setMethod] = useState<Method>("ml");
  const [lifts, setLifts] = useState<LiftInfo[]>([]);
  const [version, setVersion] = useState(0);
  const [llmReady, setLlmReady] = useState(false);

  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const authed = auth !== null && auth.authenticated;

  const i18n = useMemo(() => makeI18n(lang), [lang]);
  const { t } = i18n;

  useEffect(() => {
    api.authStatus().then(setAuth).catch(() => setAuth({ required: false, authenticated: true, user: null }));
    const onExpired = () => setAuth((a) => (a ? { ...a, required: true, authenticated: false } : a));
    window.addEventListener(AUTH_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EVENT, onExpired);
  }, []);

  // layout effect: the CSS variables must be switched before the charts read them
  useLayoutEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dataset.theme = theme;
    store("lang", lang);
    store("theme", theme);
  }, [lang, theme]);

  // debounce the tariff so typing "12.5" does not fire a request per keystroke
  useEffect(() => {
    const id = setTimeout(() => {
      const v = Number(tariffInput.replace(",", "."));
      if (v > 0 && v <= 100) setTariff(v);
    }, 400);
    return () => clearTimeout(id);
  }, [tariffInput]);

  useEffect(() => { if (authed) api.lifts().then(setLifts).catch(() => setLifts([])); }, [version, authed]);
  useEffect(() => { if (authed) api.llmStatus().then((s) => setLlmReady(s.configured)).catch(() => setLlmReady(false)); }, [version, authed]);
  const onDataChanged = useCallback(() => setVersion((v) => v + 1), []);

  const ctx: Ctx = { days, tariff, method, lifts, version, llmReady, onDataChanged, goData: () => setTab("data") };
  const demo = lifts.length > 0 && lifts.every((l) => DEMO_IDS.includes(l.id));
  const View = TABS.find((x) => x.id === tab)!.View;

  if (auth === null) return null;
  if (!authed) {
    return (
      <I18nCtx.Provider value={i18n}>
        <Login onDone={() => api.authStatus().then(setAuth)} />
      </I18nCtx.Provider>
    );
  }

  return (
    <I18nCtx.Provider value={i18n}>
      <ThemeCtx.Provider value={theme}>
        <header>
          <div className="brand">
            <svg viewBox="0 0 32 32" className="mark" aria-hidden="true"><rect width="32" height="32" rx="8" /><path d="M18 4 8 18h7l-1 10 10-14h-7z" /></svg>
            <div>
              <div className="name">{t("app.name")}</div>
              <div className="tag">{t("app.tag")}</div>
            </div>
          </div>
          <div className="controls">
            <label>{t("ctl.period")}
              <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
                {[7, 14, 30].map((n) => <option key={n} value={n}>{t("ctl.days", { n })}</option>)}
              </select>
            </label>
            <label>{t("ctl.detector")}
              <select value={method} onChange={(e) => setMethod(e.target.value as Method)}>
                <option value="ml">{t("ctl.ml")}</option><option value="stat">{t("ctl.stat")}</option>
              </select>
            </label>
            <label>{t("ctl.tariff")}
              <input type="number" min={1} max={100} step={0.5} value={tariffInput} onChange={(e) => setTariffInput(e.target.value)} />
            </label>
            <div className="seg-switch" role="group" aria-label="language">
              {(["ru", "en"] as Lang[]).map((l) => (
                <button key={l} className={l === lang ? "on" : ""} onClick={() => setLang(l)}>{l.toUpperCase()}</button>
              ))}
            </div>
            <button className="icon-btn" title={t("ctl.theme")} aria-label={t("ctl.theme")} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
              {theme === "dark" ? "☀" : "☾"}
            </button>
            {auth?.required && (
              <button className="btn ghost small" onClick={() => api.logout().then(() => setAuth({ ...auth, authenticated: false }))}>
                {t("login.out")}
              </button>
            )}
          </div>
        </header>
        <nav>
          {TABS.map((x) => (
            <button key={x.id} className={x.id === tab ? "active" : ""} onClick={() => setTab(x.id)}>{t(x.label)}</button>
          ))}
        </nav>
        {demo && (
          <div className="banner">
            {t("banner.demo")} <button className="link" onClick={() => setTab("data")}>{t("banner.go")} →</button>
          </div>
        )}
        <main><View ctx={ctx} /></main>
        <footer>{t("footer")}</footer>
      </ThemeCtx.Provider>
    </I18nCtx.Provider>
  );
}
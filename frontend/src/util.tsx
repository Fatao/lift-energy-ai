import { createContext, useContext, useEffect, useRef, useState } from "react";
import { Chart, registerables } from "chart.js";
import type { ChartConfiguration } from "chart.js";
import type { LiftStatus, Severity } from "./types";
import { useI18n } from "./i18n";

Chart.register(...registerables);

export type Theme = "light" | "dark";
export const ThemeCtx = createContext<Theme>("light");

export const cssVar = (name: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";

/** Six distinguishable series colours; they are defined per theme in style.css (--c1 … --c6). */
export const seriesColor = (i: number): string => cssVar(`--c${(i % 6) + 1}`);

export const shortDate = (d: string): string => d.slice(8, 10) + "." + d.slice(5, 7);

export interface AsyncState<T> { data: T | null; error: string | null; loading: boolean }

/** Runs `fn` whenever `deps` change; ignores answers that arrive after a newer request started. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn().then(
      (data) => alive && setState({ data, error: null, loading: false }),
      (e: unknown) => alive && setState({ data: null, error: e instanceof Error ? e.message : String(e), loading: false }),
    );
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function ChartView({ config, height = 300 }: { config: ChartConfiguration<any, any, any>; height?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const theme = useContext(ThemeCtx);
  useEffect(() => {
    if (!ref.current) return;
    const text = cssVar("--muted");
    const grid = cssVar("--line");
    Chart.defaults.color = text;
    Chart.defaults.font.family = "'Inter Variable', system-ui, sans-serif";
    Chart.defaults.borderColor = grid;
    const chart = new Chart(ref.current, {
      ...config,
      options: { responsive: true, maintainAspectRatio: false, animation: { duration: 250 }, ...config.options },
    });
    return () => chart.destroy();
  }, [config, theme]);
  return (
    <div className="chart" style={{ height }}>
      <canvas ref={ref} />
    </div>
  );
}

export function Status<T>({ s, children }: { s: AsyncState<T>; children: (d: T) => JSX.Element }) {
  const { t } = useI18n();
  if (s.error) return <p className="err">{t("error")}: {s.error}</p>;
  if (!s.data) return <p className="muted">{t("loading")}</p>;
  return <div style={{ opacity: s.loading ? 0.6 : 1, transition: "opacity .15s" }}>{children(s.data)}</div>;
}

export const Badge = ({ sev }: { sev: Severity }) => {
  const { t } = useI18n();
  return <span className={`badge ${sev}`}>{t(`sev.${sev}` as const)}</span>;
};

export const StatusLed = ({ status }: { status: LiftStatus }) => {
  const { t } = useI18n();
  return <span className={`led-label ${status}`}><i className={`led ${status}`} />{t(`status.${status}` as const)}</span>;
};

// ---------------------------------------------------------------- seven-segment display
//   _a_
//  f|   |b
//   _g_
//  e|   |c
//   _d_
const SEG: Record<string, string> = {
  "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
  "5": "acdfg", "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", " ": "",
};
const PATH: Record<string, string> = {
  a: "M3 1h12l-2 2H5z", b: "M16 2v10l-2 2V4z", c: "M16 16v10l-2-2V14z",
  d: "M3 29h12l-2-2H5z", e: "M2 16v10l2-2V14z", f: "M2 2v10l2 2V4z", g: "M3 15l2-2h8l2 2-2 2H5z",
};

function Digit({ ch }: { ch: string }) {
  const on = SEG[ch] ?? "";
  return (
    <svg viewBox="0 0 18 30" className="digit" aria-hidden="true">
      {Object.keys(PATH).map((k) => <path key={k} d={PATH[k]} className={on.includes(k) ? "seg on" : "seg"} />)}
    </svg>
  );
}

/** Value shown on a seven-segment display; the real number is also given to screen readers. */
export function SevenSeg({ value, digits = 4, decimals = 1, unit }: { value: number | null | undefined; digits?: number; decimals?: number; unit?: string }) {
  let text = value == null ? "-".repeat(digits) : Math.abs(value).toFixed(decimals);
  const label = value == null ? "no data" : `${value.toFixed(decimals)} ${unit ?? ""}`;
  const plain = text.replace(".", "");
  const pad = Math.max(0, digits - plain.length);
  text = " ".repeat(pad) + text;
  const out: JSX.Element[] = [];
  let k = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === ".") continue;
    out.push(<span key={k++} className="cell"><Digit ch={c} />{text[i + 1] === "." && <b className="dot" />}</span>);
  }
  return <span className="sevenseg" role="img" aria-label={label}>{out}{unit && <em>{unit}</em>}</span>;
}

import type {
  AnomalyEvent, Compare, Explanation, Forecast, Hourly, ImportSummary, IngestStatus, LiftInfo,
  LlmStatus, LlmTest, Method, Overview, Recommendation, Series,
} from "./types";
import type { Lang } from "./i18n";

export class ApiError extends Error {
  summary: ImportSummary | null;
  status: number;
  constructor(message: string, summary: ImportSummary | null = null, status = 0) {
    super(message);
    this.summary = summary;
    this.status = status;
  }
}

/** App.tsx listens to this and shows the login screen when the session has expired. */
export const AUTH_EVENT = "lift-auth-required";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch("/api" + path, init);
  } catch {
    throw new ApiError("The server is not reachable");
  }
  if (!r.ok) {
    if (r.status === 401 && !path.startsWith("/login") && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event(AUTH_EVENT));
    }
    let msg = `HTTP ${r.status}`;
    let summary: ImportSummary | null = null;
    try {
      const j = await r.json();
      if (typeof j.detail === "string") msg = j.detail;
      else if (j.detail && typeof j.detail.message === "string") {
        msg = j.detail.message;
        summary = j.detail.summary ?? null;
      } else if (Array.isArray(j.detail)) msg = "Invalid request";
    } catch { /* body is not JSON */ }
    throw new ApiError(msg, summary, r.status);
  }
  return r.json() as Promise<T>;
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

export interface ImportOptions {
  replace: boolean;
  cumulative: boolean;
  liftId: string;
  mapping: Record<string, number | null> | null;
}

function importForm(file: File, o: ImportOptions) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("replace", String(o.replace));
  fd.append("cumulative", String(o.cumulative));
  if (o.liftId.trim()) fd.append("lift_id", o.liftId.trim());
  if (o.mapping) fd.append("mapping", JSON.stringify(o.mapping));
  return fd;
}

export interface AuthStatus { required: boolean; authenticated: boolean; user: string | null }

export const api = {
  authStatus: () => request<AuthStatus>("/auth/status"),
  login: (user: string, password: string) => post<{ ok: boolean }>("/login", { user, password }),
  logout: () => post<{ ok: boolean }>("/logout"),
  lifts: () => request<LiftInfo[]>("/lifts"),
  renameLift: (id: string, name: string) =>
    request<LiftInfo>(`/lifts/${encodeURIComponent(id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
    }),
  deleteLift: (id: string) => request<unknown>(`/lifts/${encodeURIComponent(id)}`, { method: "DELETE" }),
  overview: (days: number) => request<Overview>(`/overview?days=${days}`),
  series: (days: number) => request<Series[]>(`/series?days=${days}`),
  hourly: (id: string, days: number, method: Method) =>
    request<Hourly>(`/hourly/${encodeURIComponent(id)}?days=${days}&method=${method}`),
  anomalies: (days: number, method: Method, lang: Lang) =>
    request<AnomalyEvent[]>(`/anomalies?days=${days}&method=${method}&lang=${lang}`),
  compare: (days: number) => request<Compare>(`/compare?days=${days}`),
  forecast: (id: string, lang: Lang) => request<Forecast>(`/forecast/${encodeURIComponent(id)}?lang=${lang}`),
  recommendations: (days: number, tariff: number, method: Method, lang: Lang) =>
    request<Recommendation[]>(`/recommendations?days=${days}&tariff=${tariff}&method=${method}&lang=${lang}`),
  explain: (id: string, days: number, tariff: number, method: Method, lang: Lang) =>
    post<Explanation>(`/explain?lang=${lang}`, { id, days, tariff, method }),
  llmStatus: () => request<LlmStatus>("/llm/status"),
  llmTest: (lang: Lang) => post<LlmTest>(`/llm/test?lang=${lang}`),
  ingestStatus: () => request<IngestStatus>("/ingest/status"),
  importPreview: (file: File, lang: Lang, o: ImportOptions) =>
    request<ImportSummary>(`/import/preview?lang=${lang}`, { method: "POST", body: importForm(file, o) }),
  importApply: (file: File, lang: Lang, o: ImportOptions) =>
    request<ImportSummary>(`/import?lang=${lang}`, { method: "POST", body: importForm(file, o) }),
  resetDemo: () => post<{ generated: number }>("/reset-demo"),
  clear: () => post<{ cleared: boolean }>("/clear"),
  recsCsvUrl: (days: number, tariff: number, method: Method, lang: Lang) =>
    `/api/export/recommendations.csv?days=${days}&tariff=${tariff}&method=${method}&lang=${lang}`,
  readingsCsvUrl: "/api/export/readings.csv",
};
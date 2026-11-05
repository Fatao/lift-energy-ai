export type Severity = "high" | "medium" | "low";
export type Method = "stat" | "ml";
export type LiftStatus = "ok" | "watch" | "alert" | "warmup";

export interface LiftInfo { id: string; name: string }

export interface LiftSummary {
  lift_id: string;
  name: string;
  status?: LiftStatus;
  total_kwh: number;
  avg_kwh_per_day?: number;
  trips: number;
  kwh_per_trip: number | null;
  marginal_kwh_per_trip: number | null;
  standby_kw: number | null;
  standby_share: number | null;
  anomalies: number;
  recent_anomalies?: number;
  anomaly_extra_kwh: number;
  completeness: number;
  peak_hour: number | null;
}

export interface Group {
  total_kwh: number;
  trips: number;
  kwh_per_trip: number | null;
  standby_share: number | null;
  anomalies: number;
  completeness: number;
  last_ts: string | null;
}

export interface Overview { days: number; lifts: LiftSummary[]; group: Group | null }

export interface Series {
  lift_id: string;
  name: string;
  dates: string[];
  kwh: number[];
  trips: number[];
  hours: number[];
  hour_profile: number[];
}

export interface Hourly {
  lift_id: string;
  method: Method;
  ts: string[];
  kwh: number[];
  expected: (number | null)[];
  anomaly_idx: number[];
}

export interface AnomalyEvent {
  lift_id: string;
  lift_name: string;
  method: Method;
  start: string;
  end: string;
  hours: number;
  extra_kwh: number;
  peak_kwh: number;
  trips: number;
  kind: "idle" | "moving";
  kind_text: string;
  severity: Severity;
}

export interface CompareRow extends LiftSummary {
  standby_kw_dev?: number | null;
  marginal_kwh_per_trip_dev?: number | null;
  kwh_per_trip_dev?: number | null;
}

export interface Compare {
  lifts: CompareRow[];
  medians: { standby_kw: number; marginal_kwh_per_trip: number; kwh_per_trip: number } | null;
  skipped: string[];
}

export interface ForecastPoint { date: string; kwh: number; low: number; high: number }

export interface Forecast {
  lift_id: string;
  error?: string;
  history: { date: string; kwh: number }[];
  forecast: ForecastPoint[];
  trend_factor: number;
  band_sd: number;
  last7_actual: number;
  next7_forecast: number;
  method: string;
  model: string;
  model_name: string;
  backtest: { days: number; mae_kwh: Record<string, number>; names: Record<string, string> } | null;
}

export interface Recommendation {
  id: string;
  lift_id: string;
  lift_name: string;
  severity: Severity;
  kind: string;
  title: string;
  text: string;
  evidence: string[];
  est_saving_rub_year: number | null;
}

export interface Explanation {
  id: string;
  text: string;
  source: "llm" | "template";
  provider: string;
  model: string | null;
  verified: boolean;
  note: string | null;
}

export interface LlmStatus { provider: string; model: string | null; configured: boolean }
export interface LlmTest { provider: string; model: string | null; ok: boolean; ms: number | null; message: string }

export interface SourceState {
  state: string;
  detail: string;
  messages: number;
  errors: number;
  last_message: string | null;
  last_error: string | null;
}

export interface IngestStatus {
  sources: Record<string, SourceState>;
  live_mode: boolean;
  last_ts: string | null;
}

export type MapField = "lift_id" | "name" | "ts" | "kwh" | "trips" | "door_cycles";

export interface ImportSummary {
  headers: string[];
  mapping: Record<MapField, number | null>;
  auto_mapping: Record<MapField, number | null>;
  sample: string[][];
  rows_total: number;
  rows_used?: number;
  warnings: string[];
  skipped?: Record<string, number>;
  skipped_rows?: Record<string, number[]>;
  lifts?: string[];
  hours?: number;
  first?: string;
  last?: string;
  fields?: string[];
}
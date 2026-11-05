import type { LiftInfo, Method } from "./types";

/** Settings shared by every view. `version` changes after data is imported/cleared -> views reload. */
export interface Ctx {
  days: number;
  tariff: number;
  method: Method;
  lifts: LiftInfo[];
  version: number;
  llmReady: boolean;
  onDataChanged: () => void;
  goData: () => void;
}
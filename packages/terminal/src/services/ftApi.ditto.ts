import { get, post } from "./ftApi.helpers";

export interface DittoAccount {
  id: string;
  name: string;
  broker: string;
  capital: number;
  pnl_today: number;
  status: "active" | "disabled";
  positions: number;
  group: string;
  allocation_weight: number;
  is_master: boolean;
}

export interface MirrorStatus {
  active: boolean;
  source_account: string | null;
  target_accounts: string[];
  mode: "proportional" | "fixed" | "equal";
  mirrored_positions: number;
  last_sync: string | null;
  errors: string[];
}

export interface MirrorStartResult {
  active: boolean;
  source_account: string;
  target_accounts: string[];
  mode: string;
  started_at: string;
}

export interface DittoRiskAccount {
  id: string;
  name: string;
  margin_used_pct: number;
  pnl_today: number;
  positions: number;
  risk_status: "OK" | "WARNING" | "CRITICAL" | "PAUSED";
}

export interface DittoRiskData {
  aggregate_pnl: number;
  aggregate_capital: number;
  accounts: DittoRiskAccount[];
}

export const getDittoAccounts = () =>
  get<{ accounts: DittoAccount[] }>("ditto/accounts");

export const getDittoMirrorStatus = () =>
  get<MirrorStatus>("ditto/mirror/status");

export const startDittoMirror = (
  source_account: string,
  target_accounts: string[],
  mode: string,
) =>
  post<MirrorStartResult>("ditto/mirror/start", {
    source_account,
    target_accounts,
    mode,
  });

export const stopDittoMirror = () =>
  post<{ active: boolean; stopped_at: string }>("ditto/mirror/stop");

export const getDittoRisk = () => get<DittoRiskData>("ditto/risk");

export const dittoKillAll = () =>
  post<{ message: string; accounts_affected: number }>("ditto/kill-all");

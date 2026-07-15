import { del, get, isDemoAuthSession, post } from "./ftApi.helpers";

export interface DittoAccount {
  id: string;
  name: string;
  broker: string;
  capital: number | null;
  pnl_today: number | null;
  status: "active" | "disabled";
  positions: number | null;
  group: string;
  allocation_weight: number;
  max_loss_daily: number;
  is_master: boolean;
}

export interface DittoAccountCreatePayload {
  account_id: string;
  openalgo_host: string;
  api_key: string;
  name?: string;
  enabled?: boolean;
  group?: string;
  allocation_weight?: number;
  max_loss_daily?: number;
  is_master?: boolean;
}

export type MirrorMode = "equal" | "weighted";

export function normaliseMirrorMode(value: unknown): MirrorMode {
  const mode = String(value ?? "").trim().toUpperCase();
  if (mode === "EQUAL" || mode === "FIXED") return "equal";
  if (mode === "WEIGHTED" || mode === "PROPORTIONAL") return "weighted";
  throw new Error("Ditto returned an unsupported allocation mode");
}

export interface MirrorStatus {
  active: boolean;
  source_account: string | null;
  target_accounts: string[];
  mode: MirrorMode;
  mirrored_positions: number;
  last_sync: string | null;
  errors: string[];
}

export interface MirrorStartResult {
  active: boolean;
  source_account: string;
  target_accounts: string[];
  mode: MirrorMode;
  started_at: string;
}

export interface DittoRiskAccount {
  id: string;
  name: string;
  margin_used_pct: number;
  pnl_today: number;
  positions: number;
  risk_status: "OK" | "WARNING" | "CRITICAL" | "PAUSED";
  capital: number;
}

export interface DittoRiskData {
  complete: boolean;
  aggregate_pnl: number;
  aggregate_capital: number;
  accounts: DittoRiskAccount[];
}

export interface DittoKillAllResult {
  complete: boolean;
  cleanup_complete: boolean;
  message: string;
  accounts_affected: number;
  emergency_actions: Record<string, unknown>;
}

export const getDittoAccounts = () =>
  isDemoAuthSession()
    ? Promise.resolve({ accounts: [] })
    : get<{ accounts: DittoAccount[] }>("ditto/accounts");

export const addDittoAccount = (account: DittoAccountCreatePayload) =>
  post<{ account: DittoAccount }>("ditto/accounts", account).then((res) => res.account);

export const setDittoAccountEnabled = (accountId: string, enabled: boolean) =>
  post<{ account: DittoAccount }>(
    `ditto/accounts/${encodeURIComponent(accountId)}/${enabled ? "enable" : "disable"}`,
  ).then((res) => res.account);

export const removeDittoAccount = (accountId: string) =>
  del<{ id: string; removed: boolean }>(`ditto/accounts/${encodeURIComponent(accountId)}`);

export const getDittoMirrorStatus = () =>
  isDemoAuthSession()
    ? Promise.resolve({
      active: false,
      source_account: null,
      target_accounts: [],
      mode: "equal" as const,
      mirrored_positions: 0,
      last_sync: null,
      errors: [],
    })
    : get<Omit<MirrorStatus, "mode"> & { mode: unknown }>("ditto/mirror/status")
      .then((status) => ({ ...status, mode: normaliseMirrorMode(status.mode) }));

export const startDittoMirror = (
  source_account: string,
  target_accounts: string[],
  mode: MirrorMode,
) =>
  post<Omit<MirrorStartResult, "mode"> & { mode: unknown }>("ditto/mirror/start", {
    source_account,
    target_accounts,
    mode,
  }).then((result) => ({ ...result, mode: normaliseMirrorMode(result.mode) }));

export const stopDittoMirror = () =>
  post<{ active: boolean; stopped_at: string }>("ditto/mirror/stop");

export const getDittoRisk = () =>
  isDemoAuthSession()
    ? Promise.resolve({
      complete: true,
      aggregate_pnl: 0,
      aggregate_capital: 0,
      accounts: [],
    })
    : get<DittoRiskData>("ditto/risk");

export const dittoKillAll = () =>
  post<DittoKillAllResult>("ditto/kill-all").then((result) => {
    if (!result.complete) {
      throw new Error(result.message || "One or more managed accounts could not be fully flattened");
    }
    return result;
  });

import { del, get, isDemoAuthSession, post } from "./ftApi.helpers";

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
    : get<MirrorStatus>("ditto/mirror/status");

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

export const getDittoRisk = () =>
  isDemoAuthSession()
    ? Promise.resolve({
      aggregate_pnl: 0,
      aggregate_capital: 0,
      accounts: [],
    })
    : get<DittoRiskData>("ditto/risk");

export const dittoKillAll = () =>
  post<{ message: string; accounts_affected: number }>("ditto/kill-all");

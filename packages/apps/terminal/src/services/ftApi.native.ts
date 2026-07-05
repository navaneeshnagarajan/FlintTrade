/**
 * ftApi.native — native broker connect API (Phase 1 G4 UI).
 *
 * Wraps the backend /api/v1/native/* routes: the broker catalogue (which login
 * methods each broker supports), connecting an account (direct credentials or
 * OAuth), listing/removing connected accounts, and re-login. Credentials are
 * POSTed straight to the local backend — they never leave the machine.
 */

import { get, post, del } from "./ftApi.helpers";

export interface NativeAuthField {
  name: string;
  label: string;
  secret: boolean;
  required: boolean;
  help: string;
}

export interface NativeAuthMethod {
  id: string;
  label: string;
  kind: "direct" | "oauth";
  description: string;
  fields: NativeAuthField[];
}

export interface McpClientConfig {
  id: string;
  label: string;
  command?: string | null;
  args?: string[];
  url?: string | null;
  config?: Record<string, unknown>;
}

export interface BrokerMcpInfo {
  remote_url: string;
  docs_url: string;
  auth_mode: string;
  reauth: string;
  read_only: boolean;
  trading_supported: boolean;
  daily_reauthorization?: boolean;
  login_steps: string[];
  use_cases: string[];
  cautions: string[];
  client_configs: McpClientConfig[];
}

export interface NativeBroker {
  adapter_id: string;
  display_name: string;
  /** Tried-and-tested against a live account (Dhan, Upstox, INDmoney today). When false
   * the broker is catalogued but "coming soon" — the connect UI must not offer
   * it, and the backend rejects a connect for it. */
  connectable: boolean;
  auth_methods: NativeAuthMethod[];
  mcp?: BrokerMcpInfo | null;
  oauth_redirect_uri?: string;
  postback_uri?: string;
}

export interface BrokerMcpCatalogueEntry {
  adapter_id: string;
  display_name: string;
  native: boolean;
  connectable: boolean;
  mcp: BrokerMcpInfo;
}

export interface NativeAccount {
  adapter_id: string;
  account_id: string;
  label?: string | null;
  is_primary?: boolean;
  has_session?: boolean;
  expires_at?: number | null;
  /** Set when the last credential replay failed — the stored material is
   * stale/single-use and the operator must re-authenticate (G7). */
  needs_relogin?: boolean;
  /** Set when the last credential replay could not complete because the broker
   * login/service was temporarily unavailable; stored credentials are not known
   * stale. */
  login_retryable?: boolean;
  login_error?: string | null;
}

// NOTE: `get`/`post` (ftApi.helpers) already unwrap the backend `{status,
// data}` envelope and return `data` directly (and throw the backend `message`
// on any non-2xx). So these functions consume the INNER payload — do NOT read
// a second `.data` level, or every list comes back empty.

export async function listNativeBrokers(): Promise<NativeBroker[]> {
  const r = await get<{ brokers: NativeBroker[] }>("native/brokers");
  return r?.brokers ?? [];
}

export async function listBrokerMcpCatalogue(): Promise<BrokerMcpCatalogueEntry[]> {
  const r = await get<{ brokers: BrokerMcpCatalogueEntry[] }>("broker/mcp");
  return r?.brokers ?? [];
}

export async function listNativeAccounts(): Promise<NativeAccount[]> {
  const r = await get<{ accounts: NativeAccount[] }>("native/accounts");
  return r?.accounts ?? [];
}

export type NativeReadKind =
  | "funds"
  | "limits"
  | "positions"
  | "holdings"
  | "profile"
  | "orders"
  | "orderstatus"
  | "orderhistory"
  | "ordertrades"
  | "trades"
  | "quotes"
  | "quote_details"
  | "depth"
  | "margin"
  | "scrip_master"
  | "holidays"
  | "timings"
  | "optiongreeks"
  | "history"
  | "expiry"
  | "optionchain"
  | "search"
  | "search_scrip";

export type NativeReadParams = Record<
  string,
  string | number | boolean | Array<string | number | boolean> | null | undefined
>;

function serialiseNativeReadParams(params?: NativeReadParams): string {
  if (!params) return "";
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined) return;
    const values = Array.isArray(value) ? value : [value];
    values.forEach((item) => search.append(key, String(item)));
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

export async function readNativeAccount<T>(
  adapterId: string,
  accountId: string,
  kind: NativeReadKind,
  params?: NativeReadParams,
): Promise<T> {
  return get<T>(
    `native/accounts/${encodeURIComponent(adapterId)}/${encodeURIComponent(accountId)}/${kind}${serialiseNativeReadParams(params)}`,
  );
}

export interface ConnectResult {
  connected: boolean;
  login: string;
}

export async function connectNativeAccount(input: {
  adapter_id: string;
  account_id: string;
  label?: string;
  credentials: Record<string, string>;
  is_primary?: boolean;
}): Promise<ConnectResult> {
  // A failed connect is a non-2xx, so `post` throws the backend message before
  // returning; a 2xx always carries connected:true.
  const r = await post<{ connected: boolean; login: string }>("native/accounts", input);
  return { connected: !!r?.connected, login: r?.login ?? "" };
}

export interface OAuthStartResult {
  auth_url: string;
  state: string;
  redirect_uri: string;
  postback_uri?: string;
}

export async function oauthStartNativeAccount(input: {
  adapter_id: string;
  account_id: string;
  api_key: string;
  api_secret: string;
  label?: string;
  is_primary?: boolean;
}): Promise<OAuthStartResult> {
  const r = await post<OAuthStartResult>("native/oauth/start", input);
  if (!r?.auth_url) throw new Error("Could not start OAuth login");
  return r;
}

export async function removeNativeAccount(adapterId: string, accountId: string): Promise<void> {
  await del(`native/accounts/${encodeURIComponent(adapterId)}/${encodeURIComponent(accountId)}`);
}

export async function setPrimaryNativeAccount(adapterId: string, accountId: string): Promise<void> {
  await post(`native/accounts/${encodeURIComponent(adapterId)}/${encodeURIComponent(accountId)}/set-primary`);
}

export interface ReloginResult {
  has_session: boolean;
  expires_at?: number | null;
  login?: string;
}

/**
 * Re-authenticate a connected account (daily re-auth / expired token, G5).
 * Omit `credentials` to replay the stored (replayable) material; pass fresh
 * credentials when the stored ones are stale (e.g. a new TOTP or token).
 */
export async function reloginNativeAccount(
  adapterId: string,
  accountId: string,
  credentials?: Record<string, string>,
): Promise<ReloginResult> {
  const r = await post<{ session: ReloginResult; login?: string }>(
    `native/accounts/${encodeURIComponent(adapterId)}/${encodeURIComponent(accountId)}/login`,
    credentials ? { credentials } : {},
  );
  const session = r?.session;
  if (!session?.has_session) {
    throw new Error("Re-login did not establish a session — enter fresh credentials.");
  }
  return session;
}

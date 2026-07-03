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

export interface NativeBroker {
  adapter_id: string;
  display_name: string;
  auth_methods: NativeAuthMethod[];
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
  login_error?: string | null;
}

interface ApiEnvelope<T> {
  status: string;
  data?: T;
  message?: string;
}

export async function listNativeBrokers(): Promise<NativeBroker[]> {
  const r = await get<ApiEnvelope<{ brokers: NativeBroker[] }>>("native/brokers");
  return r.data?.brokers ?? [];
}

export async function listNativeAccounts(): Promise<NativeAccount[]> {
  const r = await get<ApiEnvelope<{ accounts: NativeAccount[] }>>("native/accounts");
  return r.data?.accounts ?? [];
}

export interface ConnectResult {
  connected: boolean;
  login: string;
  message?: string;
}

export async function connectNativeAccount(input: {
  adapter_id: string;
  account_id: string;
  label?: string;
  credentials: Record<string, string>;
  is_primary?: boolean;
}): Promise<ConnectResult> {
  const r = await post<ApiEnvelope<{ connected: boolean; login: string }>>("native/accounts", input);
  return { connected: !!r.data?.connected, login: r.data?.login ?? "", message: r.message };
}

export interface OAuthStartResult {
  auth_url: string;
  state: string;
  redirect_uri: string;
}

export async function oauthStartNativeAccount(input: {
  adapter_id: string;
  account_id: string;
  api_key: string;
  api_secret: string;
  label?: string;
  is_primary?: boolean;
}): Promise<OAuthStartResult> {
  const r = await post<ApiEnvelope<OAuthStartResult>>("native/oauth/start", input);
  if (!r.data?.auth_url) throw new Error(r.message || "Could not start OAuth login");
  return r.data;
}

export async function removeNativeAccount(adapterId: string, accountId: string): Promise<void> {
  await del(`native/accounts/${encodeURIComponent(adapterId)}/${encodeURIComponent(accountId)}`);
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
  const r = await post<ApiEnvelope<{ session: ReloginResult; login?: string }>>(
    `native/accounts/${encodeURIComponent(adapterId)}/${encodeURIComponent(accountId)}/login`,
    credentials ? { credentials } : {},
  );
  const session = r.data?.session;
  if (!session?.has_session) {
    throw new Error(r.message || "Re-login did not establish a session — enter fresh credentials.");
  }
  return session;
}

import { get, getV1, isDemoAuthSession, post, postV1 } from "./ftApi.helpers";

export interface AuditLog {
  timestamp: string;
  event_type: string;
  strategy: string;
  symbol: string;
  exchange: string;
  action: string;
  quantity: number;
  price: number;
  layer: string;
  verdict: string;
  reason: string;
}

export interface SecurityStatsOffender {
  ip: string;
  request_count: number;
  failed_auth_count: number;
  not_found_count: number;
  is_banned: boolean;
  last_seen: string;
}

export interface SecurityStats {
  total_ips: number;
  banned_count: number;
  top_offenders: SecurityStatsOffender[];
}

export interface BannedIP {
  ip: string;
  reason: string;
  banned_at: string;
}

export interface SecuritySettings {
  auto_ban_enabled: boolean;
  ban_threshold: number;
  notfound_ban_threshold: number;
  ban_duration: number;
}

export interface HealthSubsystem {
  status: "ok" | "degraded" | "error";
  note?: string;
  [key: string]: unknown;
}

export interface SystemHealth {
  status: "ok" | "degraded" | "error";
  broker: HealthSubsystem;
  duckdb: HealthSubsystem;
  disk: HealthSubsystem & { free_gb?: number; total_gb?: number; used_pct?: number };
  memory: HealthSubsystem & { used_mb?: number; total_mb?: number; used_pct?: number };
}

export interface PathStat {
  path: string;
  count: number;
}

export interface TrafficStats {
  window_minutes: number;
  total_requests: number;
  requests_per_sec: number;
  error_rate: number;
  avg_latency_ms: number;
  top_paths: PathStat[];
}

export interface BrokerLatency {
  count: number;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
}

export type LatencyStats = Record<string, BrokerLatency>;

export interface ActivityEntry {
  id: number;
  timestamp: string;
  action: string;
  user: string;
  details: string;
  ip: string;
}

/**
 * Fetch the gated-execution audit trail for a single day (newest-first).
 *
 * Reads the hash-chain audit logger via the bare ``/v1/audit/events`` route —
 * the log whose rows carry the gated-execution shape the Execution Logs viewer
 * renders (``event_type``/``strategy``/``layer``/``verdict``), distinct from the
 * operator action log at ``/v1/audit/log``.
 */
export const getAuditLogs = (
  date?: string,
  limit?: number,
  offset?: number,
) => {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  const qs = params.toString();
  return getV1<{ logs: AuditLog[]; total: number }>(
    "audit/events" + (qs ? "?" + qs : ""),
  );
};

export interface AuthStatusData {
  is_setup: boolean;
  is_locked: boolean;
  has_pin: boolean;
}

/**
 * Auth account status — public read (no session required).
 *
 * GET /ft-api/v1/auth/status → ``{ is_setup, is_locked, has_pin }``.
 * ``has_pin`` drives the Settings → Security quick-unlock PIN block (set vs
 * change) and lets the UI explain why Live mode cannot be armed yet.
 */
export const getAuthStatus = () => getV1<AuthStatusData>("auth/status");

/**
 * Set or change the quick-unlock PIN over the live operator session.
 *
 * POST /ft-api/v1/auth/pin/set — the session Bearer JWT is attached by
 * ``buildHeaders`` (the endpoint is session-bound, G9-style) and the account
 * password is an explicit re-confirmation. Throws with the backend's
 * actionable message on failure (bad password, malformed PIN, no session).
 */
export const setAuthPin = (password: string, pin: string) =>
  postV1<{ has_pin: boolean }>("auth/pin/set", { password, pin });

const DEMO_SECURITY_SETTINGS: SecuritySettings = {
  auto_ban_enabled: false,
  ban_threshold: 25,
  notfound_ban_threshold: 10,
  ban_duration: 24,
};

const DEMO_HEALTH: SystemHealth = {
  status: "degraded",
  broker: { status: "degraded", note: "Explore mode" },
  duckdb: { status: "ok" },
  disk: { status: "ok", free_gb: 128, total_gb: 256, used_pct: 50 },
  memory: { status: "ok", used_mb: 2048, total_mb: 8192, used_pct: 25 },
};

export const getSecurityStats = () =>
  isDemoAuthSession()
    ? Promise.resolve({ total_ips: 0, banned_count: 0, top_offenders: [] })
    : get<SecurityStats>("security/stats");

/** The raw per-IP row the security monitor serialises (IPRecord.to_dict). */
interface RawBannedRow {
  ip: string;
  ban_reason: string | null;
  ban_expires: number | null;
  first_seen: number;
  last_seen: number;
}

/**
 * Fetch banned IPs, mapping the monitor's raw row to the table's contract.
 *
 * The route emits ``ban_reason`` and epoch-second timestamps; the table reads
 * ``reason`` + an ISO ``banned_at``. Map here so a live (non-demo) bans table
 * shows real reasons and ages instead of blanks and "NaNd ago".
 */
export const getBannedIPs = async (): Promise<{ bans: BannedIP[] }> => {
  if (isDemoAuthSession()) return { bans: [] };
  const raw = await get<{ bans: RawBannedRow[] }>("security/bans");
  const bans: BannedIP[] = (raw.bans ?? []).map((r) => ({
    ip: r.ip,
    reason: r.ban_reason ?? "Auto-ban",
    // last_seen (epoch seconds) marks the offending request that tripped the
    // ban — the best available "banned around" timestamp the monitor records.
    banned_at:
      typeof r.last_seen === "number" && Number.isFinite(r.last_seen)
        ? new Date(r.last_seen * 1000).toISOString()
        : "",
  }));
  return { bans };
};
export const banIP            = (ip: string, reason: string) =>
  isDemoAuthSession()
    ? Promise.resolve({ status: "demo" })
    : post<{ status: string }>("security/ban", { ip, reason });
export const unbanIP          = (ip: string) =>
  isDemoAuthSession()
    ? Promise.resolve({ status: "demo" })
    : post<{ status: string }>("security/unban", { ip });

export const getSecuritySettings = () =>
  isDemoAuthSession()
    ? Promise.resolve(DEMO_SECURITY_SETTINGS)
    : get<SecuritySettings>("security/settings");
export const updateSecuritySettings = (settings: Partial<SecuritySettings>) =>
  isDemoAuthSession()
    ? Promise.resolve({ status: "demo" })
    : post<{ status: string }>("security/settings", settings);

export const getHealth = () =>
  isDemoAuthSession()
    ? Promise.resolve(DEMO_HEALTH)
    : get<SystemHealth>("health");
export const getTrafficStats = () =>
  isDemoAuthSession()
    ? Promise.resolve({
      window_minutes: 15,
      total_requests: 0,
      requests_per_sec: 0,
      error_rate: 0,
      avg_latency_ms: 0,
      top_paths: [],
    })
    : get<TrafficStats>("traffic/stats");
export const getLatencyStats = () =>
  isDemoAuthSession()
    ? Promise.resolve({})
    : get<LatencyStats>("latency/stats");


export const getActivityLog = (params?: {
  action?: string;
  user?: string;
  since?: string;
  limit?: number;
}) => {
  const qs = new URLSearchParams();
  if (params?.action) qs.set("action", params.action);
  if (params?.user) qs.set("user", params.user);
  if (params?.since) qs.set("since", params.since);
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  const query = qs.toString();
  return get<{ entries: ActivityEntry[]; total: number }>(
    "admin/activity" + (query ? "?" + query : ""),
  );
};

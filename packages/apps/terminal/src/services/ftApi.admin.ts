import { get, isDemoAuthSession, post } from "./ftApi.helpers";

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
  return get<{ logs: AuditLog[]; total: number }>(
    "audit/logs" + (qs ? "?" + qs : ""),
  );
};

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
export const getBannedIPs = () =>
  isDemoAuthSession()
    ? Promise.resolve({ bans: [] })
    : get<{ bans: BannedIP[] }>("security/bans");
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

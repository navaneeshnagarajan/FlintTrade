import { get, post, put, del } from "./ftApi.helpers";

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

export interface UserAccount {
  id: number;
  username: string;
  email: string;
  role: "admin" | "trader" | "viewer";
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

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

export const getSecurityStats = () => get<SecurityStats>("security/stats");
export const getBannedIPs     = () => get<{ bans: BannedIP[] }>("security/bans");
export const banIP            = (ip: string, reason: string) =>
  post<{ status: string }>("security/ban", { ip, reason });
export const unbanIP          = (ip: string) =>
  post<{ status: string }>("security/unban", { ip });

export const getSecuritySettings = () => get<SecuritySettings>("security/settings");
export const updateSecuritySettings = (settings: Partial<SecuritySettings>) =>
  post<{ status: string }>("security/settings", settings);

export const getHealth       = () => get<SystemHealth>("health");
export const getTrafficStats = () => get<TrafficStats>("traffic/stats");
export const getLatencyStats = () => get<LatencyStats>("latency/stats");

export const listUsers = () =>
  get<{ users: UserAccount[] }>("users");

export const createUser = (
  username: string,
  password: string,
  email: string,
  role?: "admin" | "trader" | "viewer",
) =>
  post<UserAccount>("users", {
    username,
    password,
    email,
    ...(role ? { role } : {}),
  });

export const updateUser = (
  username: string,
  fields: { email?: string; role?: string; is_active?: boolean },
) =>
  put<UserAccount>(
    "users/" + encodeURIComponent(username),
    fields,
  );

export const deleteUser = (username: string) =>
  del<{ message: string }>(
    "users/" + encodeURIComponent(username),
  );

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

import { noteObservedFailure } from "@/stores/operatorSignalStore";

import {
  FtApiError,
  buildHeaders,
  get,
  getBase,
  getV1,
  isDemoAuthSession,
  post,
  postV1,
} from "./ftApi.helpers";

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

export type ResourceScope = "host" | "process" | "unavailable" | "sample";

export interface HealthSubsystem {
  status: "ok" | "degraded" | "error" | "unavailable";
  note?: string;
  scope?: ResourceScope;
  [key: string]: unknown;
}

/** This process only — never install-host RAM. */
export interface ProcessMemory {
  scope?: "process";
  rss_mb?: number;
  vms_mb?: number;
  percent?: number;
}

export interface HostCpu {
  status?: HealthSubsystem["status"];
  scope?: ResourceScope;
  used_pct?: number;
  cores?: number;
  note?: string;
}

export interface HostGpu {
  status?: HealthSubsystem["status"];
  scope?: ResourceScope;
  used_pct?: number;
  used_mb?: number;
  total_mb?: number;
  name?: string;
  count?: number;
  note?: string;
}

export interface HostNetwork {
  status?: HealthSubsystem["status"];
  scope?: ResourceScope;
  bytes_sent?: number;
  bytes_recv?: number;
  note?: string;
}

export interface SystemHealth {
  status: "ok" | "degraded" | "error";
  broker: HealthSubsystem;
  duckdb: HealthSubsystem;
  disk: HealthSubsystem & {
    free_gb?: number;
    total_gb?: number;
    used_gb?: number;
    used_pct?: number;
    percent_used?: number;
  };
  memory: HealthSubsystem & {
    used_mb?: number;
    total_mb?: number;
    used_pct?: number;
    rss_mb?: number;
    vms_mb?: number;
    percent?: number;
    process?: ProcessMemory;
  };
  cpu?: HostCpu;
  gpu?: HostGpu;
  network?: HostNetwork;
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
  totp_enabled?: boolean;
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

/**
 * Explore fallback when the install host cannot be read.
 *
 * Service rows may say Explore. Host disk, RAM, CPU, GPU, and network are
 * unavailable — sample gigabytes must not be painted as this machine.
 */
const EXPLORE_HEALTH: SystemHealth = {
  status: "degraded",
  broker: { status: "degraded", note: "Explore", scope: "unavailable" },
  duckdb: { status: "degraded", note: "Explore", scope: "unavailable" },
  disk: { status: "unavailable", scope: "unavailable", note: "Unavailable" },
  memory: { status: "unavailable", scope: "unavailable", note: "Unavailable" },
};

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function isSystemHealthBody(value: unknown): value is SystemHealth {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.status === "string"
    && record.disk !== null && typeof record.disk === "object"
    && record.memory !== null && typeof record.memory === "object"
  );
}

/**
 * Tag a live health document so the panel can tell host totals from process RSS.
 *
 * Disk ``percent_used`` is copied to ``used_pct``. Process RSS is nested and
 * is not written into host ``used_mb`` / ``total_mb``. Zero host totals are
 * dropped so the panel shows Unavailable rather than 0/0.
 */
export function normaliseLiveHealth(raw: SystemHealth): SystemHealth {
  const disk: SystemHealth["disk"] = raw.disk.scope === "sample"
    ? { status: "unavailable", scope: "unavailable", note: "Unavailable" }
    : { ...raw.disk };
  if (disk.scope !== "unavailable") {
    const total = finiteNumber(disk.total_gb);
    const free = finiteNumber(disk.free_gb);
    if (total !== undefined && total > 0 && free !== undefined) {
      disk.scope = "host";
      const pct = finiteNumber(disk.used_pct) ?? finiteNumber(disk.percent_used);
      if (pct !== undefined) disk.used_pct = pct;
    }
  }

  const memory: SystemHealth["memory"] = raw.memory.scope === "sample"
    ? { status: "unavailable", scope: "unavailable", note: "Unavailable" }
    : { ...raw.memory };
  const totalMb = finiteNumber(memory.total_mb);
  const usedMb = finiteNumber(memory.used_mb);
  const hostMemory = (
    memory.scope !== "sample"
    && memory.scope !== "unavailable"
    && memory.scope !== "process"
    && totalMb !== undefined
    && totalMb > 0
    && usedMb !== undefined
  );
  const rss = finiteNumber(memory.rss_mb) ?? finiteNumber(memory.process?.rss_mb);
  const vms = finiteNumber(memory.vms_mb) ?? finiteNumber(memory.process?.vms_mb);
  const processPercent = finiteNumber(memory.percent) ?? finiteNumber(memory.process?.percent);
  if (rss !== undefined || vms !== undefined) {
    memory.process = {
      scope: "process",
      ...(rss !== undefined ? { rss_mb: rss } : {}),
      ...(vms !== undefined ? { vms_mb: vms } : {}),
      ...(processPercent !== undefined ? { percent: processPercent } : {}),
    };
  }
  if (hostMemory) {
    memory.scope = "host";
  } else if (memory.scope !== "unavailable" && memory.process) {
    memory.scope = "process";
    delete memory.used_mb;
    delete memory.total_mb;
    delete memory.used_pct;
  } else {
    memory.scope = "unavailable";
    delete memory.used_mb;
    delete memory.total_mb;
    delete memory.used_pct;
  }

  return {
    ...raw,
    disk,
    memory,
    cpu: normaliseCpu(raw.cpu),
    gpu: normaliseGpu(raw.gpu),
    network: normaliseNetwork(raw.network),
  };
}

function normaliseCpu(cpu: HostCpu | undefined): HostCpu | undefined {
  if (!cpu) return undefined;
  if (cpu.scope === "sample" || cpu.scope === "unavailable") {
    return { status: "unavailable", scope: "unavailable", note: "Unavailable" };
  }
  const used = finiteNumber(cpu.used_pct);
  if (used === undefined || used < 0) return { status: "unavailable", scope: "unavailable", note: "Unavailable" };
  return { ...cpu, scope: "host", used_pct: used };
}

function normaliseGpu(gpu: HostGpu | undefined): HostGpu | undefined {
  if (!gpu) return undefined;
  if (gpu.scope === "sample" || gpu.scope === "unavailable") {
    return { status: "unavailable", scope: "unavailable", note: "Unavailable" };
  }
  const total = finiteNumber(gpu.total_mb);
  const usedPct = finiteNumber(gpu.used_pct);
  if ((total === undefined || total <= 0) && usedPct === undefined) {
    return { status: "unavailable", scope: "unavailable", note: "Unavailable" };
  }
  return { ...gpu, scope: "host" };
}

function normaliseNetwork(network: HostNetwork | undefined): HostNetwork | undefined {
  if (!network) return undefined;
  if (network.scope === "sample" || network.scope === "unavailable") {
    return { status: "unavailable", scope: "unavailable", note: "Unavailable" };
  }
  const sent = finiteNumber(network.bytes_sent);
  const received = finiteNumber(network.bytes_recv);
  if (sent === undefined || received === undefined || sent < 0 || received < 0) {
    return { status: "unavailable", scope: "unavailable", note: "Unavailable" };
  }
  return { ...network, scope: "host", bytes_sent: sent, bytes_recv: received };
}

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

/**
 * Install-host health for Settings → Monitoring.
 *
 * Live and Explore both prefer ``GET /api/v1/health`` when the backend
 * answers, including a degraded (HTTP 503) body that still carries host
 * totals. Explore falls back to service rows plus unavailable host
 * resources — never sample disk or RAM figures.
 */
export async function getHealth(): Promise<SystemHealth> {
  try {
    const resp = await fetch(`${getBase()}/api/v1/health`, {
      headers: buildHeaders(false),
    });
    const body: unknown = await resp.json().catch(() => undefined);
    if (isSystemHealthBody(body)) return normaliseLiveHealth(body);
    if (resp.ok) return body as SystemHealth;
    if (isDemoAuthSession()) return EXPLORE_HEALTH;
    const message = `FT API health: HTTP ${resp.status}`;
    noteObservedFailure({ message, httpStatus: resp.status, provenance: "general" });
    throw new FtApiError(message, resp.status, body);
  } catch (err) {
    if (err instanceof FtApiError) throw err;
    if (isDemoAuthSession()) return EXPLORE_HEALTH;
    throw err;
  }
}
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

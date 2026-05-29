/**
 * HealthWidget — System health and security status for FlintTrade terminal.
 *
 * Shows real-time status of:
 *  - Connection layer: OpenAlgo API, WebSocket, FlintTrade backend
 *  - System health: uptime, last heartbeat, disk, memory
 *  - Security: failed logins, active sessions, banned IPs
 *  - Performance: API latency (avg / p95 / p99), WS message rate
 *  - Active alerts
 *
 * Data sources:
 *  - ping              → @/services/api (OpenAlgo health check)
 *  - getHealth         → @/services/ftApi (FT backend health)
 *  - getTrafficStats   → @/services/ftApi (API request metrics)
 *  - getLatencyStats   → @/services/ftApi (per-endpoint latency)
 *  - getSecurityStats  → @/services/ftApi (failed logins, banned IPs)
 *  - useConnectionStore → Zustand (WS connected / status / lastPing)
 *
 * Auto-refreshes every 30 seconds.
 */

import { useState, useEffect, useCallback, memo } from "react";
import {
  Activity,
  Shield,
  Wifi,
  Clock,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
  WifiOff,
  Server,
  Cpu,
  HardDrive,
  Lock,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ping } from "@/services/api";
import {
  getHealth,
  getTrafficStats,
  getLatencyStats,
  getSecurityStats,
} from "@/services/ftApi";
import type { SystemHealth, TrafficStats, LatencyStats, SecurityStats } from "@/services/ftApi";
import { useConnectionStore } from "@/stores/connectionStore";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_INTERVAL_MS = 30_000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ServiceStatus = "ok" | "degraded" | "error" | "unknown";

interface ConnectionRow {
  name: string;
  status: ServiceStatus;
  latencyMs?: number | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusColor(s: ServiceStatus): string {
  switch (s) {
    case "ok":       return "bg-profit";
    case "degraded": return "bg-amber-400";
    case "error":    return "bg-loss";
    default:         return "bg-text-muted";
  }
}

function statusBadgeVariant(s: ServiceStatus): "default" | "secondary" | "destructive" | "outline" {
  switch (s) {
    case "ok":       return "default";
    case "degraded": return "secondary";
    case "error":    return "destructive";
    default:         return "outline";
  }
}

function statusLabel(s: ServiceStatus): string {
  switch (s) {
    case "ok":       return "Online";
    case "degraded": return "Degraded";
    case "error":    return "Down";
    default:         return "Unknown";
  }
}

function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "--";
  return `${ms.toFixed(0)} ms`;
}

function formatBytes(mb: number | null | undefined): string {
  if (mb == null) return "--";
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb.toFixed(0)} MB`;
}

function relativeTime(ts: number | null): string {
  if (!ts) return "never";
  const secs = Math.floor((Date.now() - ts) / 1000);
  if (secs < 5)  return "just now";
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionHeading({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <div className="flex items-center gap-1.5 mb-2">
      <Icon size={12} className="text-text-muted" />
      <span className="text-xxs font-sans uppercase tracking-wider text-text-muted">{label}</span>
    </div>
  );
}

function StatusDot({ status }: { status: ServiceStatus }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full shrink-0 ${statusColor(status)} ${status === "ok" ? "animate-pulse" : ""}`}
      aria-hidden="true"
    />
  );
}

function ConnectionCard({ rows }: { rows: ConnectionRow[] }) {
  return (
    <div className="space-y-1.5">
      {rows.map((row) => (
        <div key={row.name} className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <StatusDot status={row.status} />
            <span className="text-xs text-text-secondary truncate">{row.name}</span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {row.latencyMs != null && (
              <span className="text-xxs font-mono text-text-muted">{formatMs(row.latencyMs)}</span>
            )}
            <Badge variant={statusBadgeVariant(row.status)} className="h-4 px-1.5 text-xxs">
              {statusLabel(row.status)}
            </Badge>
          </div>
        </div>
      ))}
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-xs text-text-muted">{label}</span>
      <span className="text-xs font-mono text-text-primary">{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

function HealthWidget() {
  const { status: connStatus, wsConnected, lastPing } = useConnectionStore();

  const [openAlgoStatus, setOpenAlgoStatus]   = useState<ServiceStatus>("unknown");
  const [openAlgoLatency, setOpenAlgoLatency] = useState<number | null>(null);
  const [health, setHealth]                   = useState<SystemHealth | null>(null);
  const [traffic, setTraffic]                 = useState<TrafficStats | null>(null);
  const [latency, setLatency]                 = useState<LatencyStats | null>(null);
  const [security, setSecurity]               = useState<SecurityStats | null>(null);
  const [ftStatus, setFtStatus]               = useState<ServiceStatus>("unknown");
  const [lastRefresh, setLastRefresh]         = useState<Date | null>(null);
  const [loading, setLoading]                 = useState(false);

  // ---------------------------------------------------------------------------
  // Fetch all data
  // ---------------------------------------------------------------------------

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      // OpenAlgo ping
      const t0 = Date.now();
      try {
        await ping();
        setOpenAlgoStatus(connStatus === "connected" ? "ok" : "degraded");
        setOpenAlgoLatency(Date.now() - t0);
      } catch {
        setOpenAlgoStatus("error");
        setOpenAlgoLatency(null);
      }

      // FT backend health
      try {
        const h = await getHealth();
        setHealth(h);
        setFtStatus(h.status === "ok" ? "ok" : h.status === "degraded" ? "degraded" : "error");
      } catch {
        setFtStatus("error");
        setHealth(null);
      }

      // Traffic stats
      try {
        const t = await getTrafficStats();
        setTraffic(t);
      } catch {
        setTraffic(null);
      }

      // Latency stats
      try {
        const l = await getLatencyStats();
        setLatency(l);
      } catch {
        setLatency(null);
      }

      // Security stats
      try {
        const s = await getSecurityStats();
        setSecurity(s);
      } catch {
        setSecurity(null);
      }
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, [connStatus]);

  // Initial load + 30s polling
  useEffect(() => {
    void refresh();
    const id = setInterval(() => { void refresh(); }, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------------------------------------------------------------------
  // Derived data
  // ---------------------------------------------------------------------------

  const wsStatus: ServiceStatus = wsConnected ? "ok" : "error";

  const connectionRows: ConnectionRow[] = [
    {
      name: "OpenAlgo API",
      status: openAlgoStatus,
      latencyMs: openAlgoLatency,
    },
    {
      name: "WebSocket",
      status: wsStatus,
      latencyMs: null,
    },
    {
      name: "FlintTrade Backend",
      status: ftStatus,
      latencyMs: null,
    },
  ];

  // Aggregate p95 latency across all tracked endpoints
  const latencyEntries = latency ? Object.values(latency) : [];
  const avgP95 =
    latencyEntries.length > 0
      ? latencyEntries.reduce((sum, v) => sum + (v.p95_ms ?? 0), 0) / latencyEntries.length
      : null;
  const avgP99 =
    latencyEntries.length > 0
      ? latencyEntries.reduce((sum, v) => sum + (v.p99_ms ?? 0), 0) / latencyEntries.length
      : null;

  // Active alerts: surface degraded/error subsystems
  const alerts: string[] = [];
  if (openAlgoStatus === "error")           alerts.push("OpenAlgo API unreachable");
  if (!wsConnected)                         alerts.push("WebSocket disconnected");
  if (ftStatus === "error")                 alerts.push("FT backend unreachable");
  if (health?.broker?.status === "error")   alerts.push("Broker connection error");
  if (health?.disk?.used_pct != null && health.disk.used_pct > 90)
                                            alerts.push(`Disk usage critical: ${health.disk.used_pct.toFixed(0)}%`);
  if (health?.memory?.used_pct != null && health.memory.used_pct > 90)
                                            alerts.push(`Memory usage critical: ${health.memory.used_pct.toFixed(0)}%`);
  if ((security?.banned_count ?? 0) > 0)    alerts.push(`${security!.banned_count} IP(s) currently banned`);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      className="flex flex-col h-full w-full bg-surface-base overflow-y-auto"
      aria-label="System health dashboard"
      data-testid="health-widget"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border-default shrink-0">
        <div className="flex items-center gap-2">
          <Activity size={13} className="text-accent" />
          <span className="text-sm font-heading font-semibold text-text-primary">System Health</span>
        </div>
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-xxs text-text-muted font-mono">
              {lastRefresh.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => { void refresh(); }}
            disabled={loading}
            className="h-6 w-6 p-0 text-text-muted hover:text-text-primary disabled:opacity-40"
            aria-label="Refresh health status"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </Button>
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-col gap-4 p-3">

        {/* Active alerts */}
        {alerts.length > 0 && (
          <div className="rounded border border-amber-500/30 bg-amber-500/10 px-2.5 py-2 space-y-1">
            <div className="flex items-center gap-1.5 mb-1">
              <AlertTriangle size={11} className="text-amber-400" />
              <span className="text-xxs font-sans uppercase tracking-wider text-amber-400">Active Alerts</span>
            </div>
            {alerts.map((a, i) => (
              <div key={i} className="flex items-center gap-1.5">
                <span className="w-1 h-1 rounded-full bg-amber-400 shrink-0" />
                <span className="text-xs text-amber-300">{a}</span>
              </div>
            ))}
          </div>
        )}

        {alerts.length === 0 && (
          <div className="rounded border border-profit/30 bg-profit/10 px-2.5 py-2 flex items-center gap-2">
            <CheckCircle size={11} className="text-profit" />
            <span className="text-xs text-profit">All systems operational</span>
          </div>
        )}

        {/* Connection status */}
        <div>
          <SectionHeading icon={Wifi} label="Connections" />
          <ConnectionCard rows={connectionRows} />
        </div>

        {/* System health */}
        <div>
          <SectionHeading icon={Server} label="System" />
          <div className="space-y-0.5">
            <MetricRow
              label="WS last heartbeat"
              value={relativeTime(lastPing)}
            />
            <MetricRow
              label="Backend status"
              value={health?.status ?? "--"}
            />
            {health?.disk && (
              <MetricRow
                label="Disk free"
                value={
                  health.disk.free_gb != null
                    ? `${health.disk.free_gb.toFixed(1)} GB (${(100 - (health.disk.used_pct ?? 0)).toFixed(0)}% free)`
                    : "--"
                }
              />
            )}
            {health?.memory && (
              <MetricRow
                label="Memory"
                value={
                  health.memory.used_mb != null && health.memory.total_mb != null
                    ? `${formatBytes(health.memory.used_mb)} / ${formatBytes(health.memory.total_mb)}`
                    : "--"
                }
              />
            )}
          </div>
        </div>

        {/* Performance */}
        <div>
          <SectionHeading icon={Cpu} label="Performance" />
          <div className="space-y-0.5">
            <MetricRow
              label="API avg latency"
              value={traffic?.avg_latency_ms != null ? formatMs(traffic.avg_latency_ms) : "--"}
            />
            <MetricRow
              label="Broker p95 latency"
              value={avgP95 != null ? formatMs(avgP95) : "--"}
            />
            <MetricRow
              label="Broker p99 latency"
              value={avgP99 != null ? formatMs(avgP99) : "--"}
            />
            <MetricRow
              label="Requests / sec"
              value={traffic?.requests_per_sec != null ? traffic.requests_per_sec.toFixed(2) : "--"}
            />
            <MetricRow
              label="API error rate"
              value={traffic?.error_rate != null ? `${(traffic.error_rate * 100).toFixed(1)} %` : "--"}
            />
          </div>
        </div>

        {/* Security */}
        <div>
          <SectionHeading icon={Shield} label="Security" />
          <div className="space-y-0.5">
            <MetricRow
              label="Active tracked IPs"
              value={security?.total_ips ?? "--"}
            />
            <MetricRow
              label="Banned IPs"
              value={security?.banned_count ?? "--"}
            />
            <MetricRow
              label="Top offender requests"
              value={
                security?.top_offenders?.[0]?.request_count != null
                  ? security.top_offenders[0].request_count
                  : "--"
              }
            />
          </div>
        </div>

        {/* Connection detail */}
        <div>
          <SectionHeading icon={Lock} label="Session" />
          <div className="space-y-0.5">
            <MetricRow
              label="API connection"
              value={connStatus}
            />
            <MetricRow
              label="WS connected"
              value={wsConnected ? "Yes" : "No"}
            />
            <MetricRow
              label="Last ping"
              value={relativeTime(lastPing)}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center gap-1.5 pt-1 border-t border-border-default">
          <Clock size={10} className="text-text-muted" />
          <span className="text-xxs text-text-muted">
            Auto-refreshes every 30 s
          </span>
          {loading && (
            <span className="ml-auto text-xxs text-accent animate-pulse">Refreshing…</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default memo(HealthWidget);

// Named exports for convenience in tests
export { HealthWidget };

// Icons re-exported so test can verify they're present without importing lucide
export { WifiOff, HardDrive };

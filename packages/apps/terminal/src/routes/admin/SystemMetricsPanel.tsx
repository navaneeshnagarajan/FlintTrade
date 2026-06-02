/**
 * SystemMetricsPanel — server resource metrics for the /admin route.
 *
 * Fetches from GET /ft-api/v1/admin/system (built by the backend agent).
 * Shows: CPU gauge, Memory gauge, Disk usage bar, Uptime, Network I/O.
 * Auto-refreshes every 30 seconds via TanStack Query.
 *
 * Uses local progress bars for disk/CPU/memory usage.
 * Layout stays within the existing AdminRoute shell.
 */

import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Cpu, HardDrive, MemoryStick, Clock, Network, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SystemMetricsResponseSchema } from "@/lib/schemas/ftApi";
import { useAuthStore } from "@/stores/authStore";

// ---------------------------------------------------------------------------
// Types (matches the backend schema from core/monitoring.py)
// ---------------------------------------------------------------------------

interface NetworkIO {
  bytes_sent: number;
  bytes_recv: number;
  packets_sent: number;
  packets_recv: number;
}

interface SystemMetrics {
  cpu_percent: number;
  memory_percent: number;
  memory_used_gb: number;
  memory_total_gb: number;
  disk_percent: number;
  disk_used_gb: number;
  disk_total_gb: number;
  uptime_seconds: number;
  network_io: NetworkIO;
  process_count: number;
  load_avg_1m: number;
  load_avg_5m: number;
  load_avg_15m: number;
  collected_at: string;
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

const REFETCH_INTERVAL_MS = 30_000;

async function fetchSystemMetrics(): Promise<SystemMetrics> {
  const res = await fetch("/ft-api/v1/admin/system");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const raw: unknown = await res.json();
  const result = SystemMetricsResponseSchema.safeParse(raw);
  if (!result.success) {
    console.error("[SystemMetricsPanel] /admin/system shape mismatch:", result.error.issues);
    throw new Error("System metrics response did not match expected shape");
  }
  // Backend returns flat network_bytes_sent/recv; map to nested network_io expected by the UI.
  const d = result.data.data;
  return {
    cpu_percent: d.cpu_percent,
    memory_percent: d.memory_percent,
    memory_used_gb: d.memory_used_gb,
    memory_total_gb: d.memory_total_gb,
    disk_percent: d.disk_percent,
    disk_used_gb: d.disk_used_gb,
    disk_total_gb: d.disk_total_gb,
    uptime_seconds: d.uptime_seconds,
    network_io: {
      bytes_sent: d.network_bytes_sent ?? 0,
      bytes_recv: d.network_bytes_recv ?? 0,
      packets_sent: 0,
      packets_recv: 0,
    },
    process_count: d.process_count,
    load_avg_1m: 0,
    load_avg_5m: 0,
    load_avg_15m: 0,
    collected_at: new Date().toISOString(),
  };
}

function isDemoAuthSession(): boolean {
  const token = useAuthStore.getState().token;
  return token === "demo-user" || token === "dev-bypass";
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (d > 0) parts.push(`${d}d`);
  if (h > 0) parts.push(`${h}h`);
  parts.push(`${m}m`);
  return parts.join(" ");
}

function formatBytes(bytes: number): string {
  if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function usageColour(percent: number): string {
  if (percent >= 90) return "#EF5350"; // critical — red
  if (percent >= 75) return "#FFA726"; // warning — amber
  return "#26A69A"; // healthy — teal
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface GaugeBarProps {
  label: string;
  percent: number;
  detail: string;
  icon: React.ReactNode;
}

function GaugeBar({ label, percent, detail, icon }: GaugeBarProps) {
  const colour = usageColour(percent);
  const clampedPct = Math.min(100, Math.max(0, percent));

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-sm text-text-secondary">
          {icon}
          <span>{label}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted font-mono">{detail}</span>
          <span
            className="text-sm font-semibold font-mono tabular-nums"
            style={{ color: colour }}
          >
            {clampedPct.toFixed(1)}%
          </span>
        </div>
      </div>
      {/* Custom progress bar kept local so admin metrics do not depend on a chart package. */}
      <div
        className="h-2 w-full rounded-full bg-surface-elevated overflow-hidden"
        role="progressbar"
        aria-valuenow={clampedPct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label} usage`}
      >
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${clampedPct}%`, backgroundColor: colour }}
        />
      </div>
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: string;
  sub?: string;
  icon: React.ReactNode;
}

function StatCard({ label, value, sub, icon }: StatCardProps) {
  return (
    <div className="rounded-lg border border-border bg-surface-card px-4 py-3 space-y-1">
      <div className="flex items-center gap-1.5 text-xs text-text-muted">
        {icon}
        <span className="uppercase tracking-wider">{label}</span>
      </div>
      <div className="text-lg font-semibold font-mono tabular-nums text-text-primary">
        {value}
      </div>
      {sub && <div className="text-xs text-text-muted font-mono">{sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function SystemMetricsPanel() {
  const demoAdmin = isDemoAuthSession();
  const { data, isLoading, isError, isFetching, dataUpdatedAt, refetch } = useQuery<SystemMetrics>({
    queryKey: ["adminSystemMetrics"],
    queryFn: fetchSystemMetrics,
    refetchInterval: REFETCH_INTERVAL_MS,
    staleTime: 25_000,
    retry: 2,
    enabled: !demoAdmin,
  });

  const lastUpdated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : null;

  if (demoAdmin) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3 text-sm text-text-muted">
        <AlertCircle className="w-5 h-5 text-amber-400" />
        <p>System metrics require a live admin session.</p>
        <p className="text-xs">Explore mode keeps backend admin endpoints offline.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-text-muted gap-2">
        <RefreshCw className="w-4 h-4 animate-spin" />
        Loading system metrics…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3 text-sm text-text-muted">
        <AlertCircle className="w-5 h-5 text-red-400" />
        <p>Failed to load system metrics.</p>
        <p className="text-xs">Ensure the FlintTrade backend is running on port 5100.</p>
        <Button
          variant="ghost"
          size="sm"
          className="text-xs h-7 text-text-muted hover:text-text-primary"
          onClick={() => void refetch()}
        >
          <RefreshCw className="w-3 h-3 mr-1" />
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-text-primary">System Metrics</h2>
          <p className="text-xs text-text-muted mt-0.5">
            Auto-refreshes every 30 s
            {lastUpdated && ` · Last updated ${lastUpdated}`}
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs text-text-muted hover:text-text-primary gap-1.5"
          onClick={() => void refetch()}
          disabled={isFetching}
          aria-label="Refresh metrics now"
        >
          <RefreshCw className={`w-3 h-3 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Usage bars */}
      <div className="rounded-lg border border-border bg-surface-card px-5 py-4 space-y-5">
        <GaugeBar
          label="CPU"
          percent={data.cpu_percent}
          detail={`${data.process_count} processes`}
          icon={<Cpu className="w-4 h-4" />}
        />
        <GaugeBar
          label="Memory"
          percent={data.memory_percent}
          detail={`${data.memory_used_gb.toFixed(1)} / ${data.memory_total_gb.toFixed(1)} GB`}
          icon={<MemoryStick className="w-4 h-4" />}
        />
        <GaugeBar
          label="Disk"
          percent={data.disk_percent}
          detail={`${data.disk_used_gb.toFixed(1)} / ${data.disk_total_gb.toFixed(1)} GB`}
          icon={<HardDrive className="w-4 h-4" />}
        />
      </div>

      {/* Stat cards grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Uptime"
          value={formatUptime(data.uptime_seconds)}
          icon={<Clock className="w-3 h-3" />}
        />
        <StatCard
          label="Load Avg"
          value={data.load_avg_1m.toFixed(2)}
          sub={`5m: ${data.load_avg_5m.toFixed(2)}  15m: ${data.load_avg_15m.toFixed(2)}`}
          icon={<Cpu className="w-3 h-3" />}
        />
        <StatCard
          label="Net Sent"
          value={formatBytes(data.network_io.bytes_sent)}
          sub={`${data.network_io.packets_sent.toLocaleString()} pkts`}
          icon={<Network className="w-3 h-3" />}
        />
        <StatCard
          label="Net Recv"
          value={formatBytes(data.network_io.bytes_recv)}
          sub={`${data.network_io.packets_recv.toLocaleString()} pkts`}
          icon={<Network className="w-3 h-3" />}
        />
      </div>
    </div>
  );
}

/**
 * MonitoringSection — system health, traffic, and latency panels.
 *
 * APIs:
 *   GET /ft-api/api/v1/health         → broker, DuckDB, and this host's disk,
 *                                     RAM, CPU, GPU, and network. Process RSS
 *                                     is separate. Missing host figures are
 *                                     Unavailable, never Explore sample totals.
 *   GET /ft-api/api/v1/traffic/stats  → requests/sec, error rate, top endpoints
 *   GET /ft-api/api/v1/latency/stats  → order latency per broker (avg/p50/p95/p99)
 */

import { useQuery } from "@tanstack/react-query";
import { RefreshCw, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { SectionTitle } from "./shared";
import { ConnectionStatusPanel } from "./ConnectionStatusPanel";
import {
  getHealth,
  getTrafficStats,
  getLatencyStats,
  type SystemHealth,
  type TrafficStats,
  type LatencyStats,
} from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pct(used: number, total: number): number {
  if (total === 0) return 0;
  return Math.round((used / total) * 100);
}

function fmtBytes(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb.toFixed(0)} MB`;
}

// ---------------------------------------------------------------------------
// Bar indicator (disk / memory)
// ---------------------------------------------------------------------------

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function fmtByteCount(bytes: number): string {
  const gb = bytes / (1024 ** 3);
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  const mb = bytes / (1024 ** 2);
  if (mb >= 1) return `${mb.toFixed(0)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

function UsageBar({
  label,
  provenance,
  usedPct,
  usedLabel,
  totalLabel,
}: {
  label: string;
  provenance: string;
  usedPct: number;
  usedLabel: string;
  totalLabel: string;
}) {
  const color =
    usedPct > 90
      ? "bg-loss"
      : usedPct > 70
        ? "bg-warning"
        : "bg-profit";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-text-secondary">{label}</span>
        <span className="text-xxs uppercase tracking-wider text-text-muted">{provenance}</span>
        <span className="font-mono tabular-nums text-text-muted">
          {usedLabel} / {totalLabel}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-surface-hover overflow-hidden">
        <div
          className={`h-full rounded-full transition-[width] ${color}`}
          style={{ width: `${Math.min(usedPct, 100)}%` }}
        />
      </div>
    </div>
  );
}

function UnavailableRow({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="text-text-secondary">{label}</span>
      <span className="text-text-muted">Unavailable</span>
    </div>
  );
}

function hostDisk(disk: SystemHealth["disk"]): { usedGb: number; totalGb: number; usedPct: number } | null {
  if (disk?.scope !== "host") return null;
  const total = finiteNumber(disk.total_gb);
  const free = finiteNumber(disk.free_gb);
  const usedField = finiteNumber(disk.used_gb);
  if (total === null || total <= 0) return null;
  const used = usedField ?? (free !== null ? total - free : null);
  if (used === null || used < 0) return null;
  const usedPct = finiteNumber(disk.used_pct) ?? finiteNumber(disk.percent_used) ?? pct(used, total);
  return { usedGb: used, totalGb: total, usedPct };
}

function hostMemory(memory: SystemHealth["memory"]): { usedMb: number; totalMb: number; usedPct: number } | null {
  if (memory?.scope !== "host") return null;
  const total = finiteNumber(memory.total_mb);
  const used = finiteNumber(memory.used_mb);
  if (total === null || total <= 0 || used === null || used < 0) return null;
  return {
    usedMb: used,
    totalMb: total,
    usedPct: finiteNumber(memory.used_pct) ?? pct(used, total),
  };
}

function processReading(
  memory: SystemHealth["memory"],
): { rssMb: number | null; vmsMb: number | null } | null {
  const nestedRss = finiteNumber(memory?.process?.rss_mb);
  const nestedVms = finiteNumber(memory?.process?.vms_mb);
  if (nestedRss !== null || nestedVms !== null) return { rssMb: nestedRss, vmsMb: nestedVms };
  if (memory?.scope === "host" || memory?.scope === "sample" || memory?.scope === "unavailable") return null;
  const rssMb = finiteNumber(memory?.rss_mb);
  const vmsMb = finiteNumber(memory?.vms_mb);
  if (rssMb === null && vmsMb === null) return null;
  return { rssMb, vmsMb };
}

function hostCpu(cpu: SystemHealth["cpu"]): { usedPct: number; cores: number | null } | null {
  if (!cpu || cpu.scope !== "host") return null;
  const usedPct = finiteNumber(cpu.used_pct);
  if (usedPct === null || usedPct < 0) return null;
  const cores = finiteNumber(cpu.cores);
  return { usedPct, cores: cores !== null && cores > 0 ? cores : null };
}

function hostGpu(gpu: SystemHealth["gpu"]): {
  label: string;
  usedPct: number | null;
  usedMb: number | null;
  totalMb: number | null;
} | null {
  if (!gpu || gpu.scope !== "host") return null;
  const totalMb = finiteNumber(gpu.total_mb);
  const usedMb = finiteNumber(gpu.used_mb);
  const usedPct = finiteNumber(gpu.used_pct);
  const total = totalMb !== null && totalMb > 0 ? totalMb : null;
  if (total === null && usedPct === null) return null;
  return {
    label: gpu.name ? `GPU — ${gpu.name}` : "GPU",
    usedPct,
    usedMb,
    totalMb: total,
  };
}

function hostNetwork(network: SystemHealth["network"]): { sent: number; received: number } | null {
  if (!network || network.scope !== "host") return null;
  const sent = finiteNumber(network.bytes_sent);
  const received = finiteNumber(network.bytes_recv);
  if (sent === null || received === null || sent < 0 || received < 0) return null;
  return { sent, received };
}

// ---------------------------------------------------------------------------
// Status dot
// ---------------------------------------------------------------------------

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      {ok ? (
        <CheckCircle2 size={12} className="text-profit shrink-0" />
      ) : (
        <XCircle size={12} className="text-loss shrink-0" />
      )}
      <span className={`text-xs ${ok ? "text-text-secondary" : "text-loss"}`}>
        {label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section panels
// ---------------------------------------------------------------------------

function HealthPanel({ data }: { data: SystemHealth }) {
  const disk = hostDisk(data.disk);
  const memory = hostMemory(data.memory);
  const process = processReading(data.memory);
  const cpu = hostCpu(data.cpu);
  const gpu = hostGpu(data.gpu);
  const network = hostNetwork(data.network);
  const gpuPct = gpu == null
    ? null
    : gpu.usedPct ?? (
      gpu.usedMb !== null && gpu.totalMb !== null && gpu.totalMb > 0
        ? pct(gpu.usedMb, gpu.totalMb)
        : null
    );

  return (
    <div className="space-y-4">
      {/* Service rows stay separate from install-host resources. */}
      <div data-testid="subsystem-status">
        <p className="text-xxs text-text-muted uppercase tracking-wider mb-1.5">
          Subsystem status
        </p>
        <div className="space-y-1">
          <StatusDot
            ok={data.broker?.status === "ok"}
            label={`Broker — ${data.broker?.note ?? data.broker?.status ?? "unknown"}`}
          />
          <StatusDot
            ok={data.duckdb?.status === "ok"}
            label={`DuckDB — ${data.duckdb?.status === "ok" ? "Healthy" : data.duckdb?.note ?? "Error"}`}
          />
        </div>
      </div>

      <div data-testid="host-resources" className="space-y-2">
        <p className="text-xxs text-text-muted uppercase tracking-wider">
          This host
        </p>
        {disk ? (
          <UsageBar
            label="Disk"
            provenance="This host"
            usedPct={disk.usedPct}
            usedLabel={`${disk.usedGb.toFixed(1)} GB`}
            totalLabel={`${disk.totalGb.toFixed(0)} GB`}
          />
        ) : (
          <UnavailableRow label="Disk" />
        )}
        {memory ? (
          <UsageBar
            label="Memory"
            provenance="This host"
            usedPct={memory.usedPct}
            usedLabel={fmtBytes(memory.usedMb)}
            totalLabel={fmtBytes(memory.totalMb)}
          />
        ) : (
          <UnavailableRow label="Memory" />
        )}
        {cpu ? (
          <UsageBar
            label="CPU"
            provenance="This host"
            usedPct={cpu.usedPct}
            usedLabel={cpu.cores !== null ? `${cpu.usedPct.toFixed(1)}% · ${cpu.cores} cores` : `${cpu.usedPct.toFixed(1)}%`}
            totalLabel="100%"
          />
        ) : (
          <UnavailableRow label="CPU" />
        )}
        {gpu && gpuPct !== null && gpu.usedMb !== null && gpu.totalMb !== null ? (
          <UsageBar
            label={gpu.label}
            provenance="This host"
            usedPct={gpuPct}
            usedLabel={fmtBytes(gpu.usedMb)}
            totalLabel={fmtBytes(gpu.totalMb)}
          />
        ) : gpu && gpuPct !== null ? (
          <UsageBar
            label={gpu.label}
            provenance="This host"
            usedPct={gpuPct}
            usedLabel={`${gpuPct.toFixed(1)}%`}
            totalLabel="100%"
          />
        ) : (
          <UnavailableRow label="GPU" />
        )}
        {network ? (
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="text-text-secondary">Network</span>
            <span className="text-xxs uppercase tracking-wider text-text-muted">This host</span>
            <span className="font-mono tabular-nums text-text-muted">
              Sent {fmtByteCount(network.sent)} · Received {fmtByteCount(network.received)}
            </span>
          </div>
        ) : (
          <UnavailableRow label="Network" />
        )}
      </div>

      {process && (
        <div data-testid="process-resources" className="flex items-center justify-between gap-2 text-xs">
          <span className="text-text-secondary">Process (this app)</span>
          <span className="font-mono tabular-nums text-text-muted">
            {process.rssMb !== null ? `RSS ${fmtBytes(process.rssMb)}` : "RSS unknown"}
            {process.vmsMb !== null ? ` · VMS ${fmtBytes(process.vmsMb)}` : ""}
          </span>
        </div>
      )}
    </div>
  );
}

function TrafficPanel({ data }: { data: TrafficStats }) {
  const errorColor =
    data.error_rate > 5
      ? "text-loss"
      : data.error_rate > 1
        ? "text-warning"
        : "text-profit";

  const maxCount = Math.max(...data.top_paths.map((e) => e.count), 1);

  return (
    <div className="space-y-3">
      {/* KPI row */}
      <div className="grid grid-cols-2 gap-2">
        <div className="p-2 rounded bg-surface-card border border-border-default">
          <p className="text-xxs text-text-muted uppercase tracking-wider">Requests / sec</p>
          <p className="font-mono tabular-nums font-bold text-base text-text-primary">
            {data.requests_per_sec.toFixed(1)}
          </p>
        </div>
        <div className="p-2 rounded bg-surface-card border border-border-default">
          <p className="text-xxs text-text-muted uppercase tracking-wider">Error Rate</p>
          <p className={`font-mono tabular-nums font-bold text-base ${errorColor}`}>
            {(data.error_rate * 100).toFixed(1)}%
          </p>
        </div>
      </div>

      {/* Top endpoints */}
      <div>
        <p className="text-xxs text-text-muted uppercase tracking-wider mb-1.5">
          Top Endpoints
        </p>
        {data.top_paths.length === 0 ? (
          <p className="text-xs text-text-muted">No data yet</p>
        ) : (
          <div className="space-y-1">
            {data.top_paths.map((ep) => (
              <div key={ep.path} className="flex items-center gap-2">
                <span className="text-xs text-text-muted font-mono min-w-0 truncate flex-1">
                  {ep.path}
                </span>
                <div className="w-24 h-1.5 rounded-full bg-surface-hover overflow-hidden flex-none">
                  <div
                    className="h-full rounded-full bg-accent/60"
                    style={{ width: `${pct(ep.count, maxCount)}%` }}
                  />
                </div>
                <span className="text-xxs font-mono tabular-nums text-text-muted w-10 text-right flex-none">
                  {ep.count}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function LatencyPanel({ data }: { data: LatencyStats }) {
  const entries = Object.entries(data);
  return (
    <div>
      <p className="text-xxs text-text-muted uppercase tracking-wider mb-1.5">
        Order Latency by Broker
      </p>
      {entries.length === 0 ? (
        <p className="text-xs text-text-muted">No latency data recorded yet</p>
      ) : (
        <div className="rounded border border-border-default overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-default bg-surface-card">
                <th className="px-3 py-1.5 text-left text-text-muted font-medium">Broker</th>
                <th className="px-3 py-1.5 text-right text-text-muted font-medium">Avg</th>
                <th className="px-3 py-1.5 text-right text-text-muted font-medium">p50</th>
                <th className="px-3 py-1.5 text-right text-text-muted font-medium">p95</th>
                <th className="px-3 py-1.5 text-right text-text-muted font-medium">p99</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([broker, row]) => {
                const p99Color =
                  row.p99_ms > 500
                    ? "text-loss"
                    : row.p99_ms > 200
                      ? "text-warning"
                      : "text-profit";
                return (
                  <tr
                    key={broker}
                    className="border-b border-border-default last:border-0 hover:bg-surface-hover transition-colors"
                  >
                    <td className="px-3 py-1.5 text-text-secondary font-medium">{broker}</td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-text-muted">
                      {row.avg_ms} ms
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-text-muted">
                      {row.p50_ms} ms
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-text-muted">
                      {row.p95_ms} ms
                    </td>
                    <td className={`px-3 py-1.5 text-right font-mono tabular-nums font-semibold ${p99Color}`}>
                      {row.p99_ms} ms
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton row for loading state
// ---------------------------------------------------------------------------

function LoadingRow({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-text-muted">
      <RefreshCw size={12} className="animate-spin shrink-0" />
      Loading {label}…
    </div>
  );
}

function ErrorRow({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-warning">
      <AlertTriangle size={12} className="shrink-0" />
      Backend unreachable — {label} unavailable
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

export function MonitoringSection() {
  const healthQuery  = useQuery<SystemHealth>({
    queryKey: ["ft", "health"],
    queryFn: getHealth,
    refetchInterval: 30_000,
  });

  const trafficQuery = useQuery<TrafficStats>({
    queryKey: ["ft", "traffic", "stats"],
    queryFn: getTrafficStats,
    refetchInterval: 30_000,
  });

  const latencyQuery = useQuery<LatencyStats>({
    queryKey: ["ft", "latency", "stats"],
    queryFn: getLatencyStats,
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-6">
      <SectionTitle>Monitoring</SectionTitle>

      {/* Connection layer roll-up — moved here from the retired System
          Health widget (ruling D6); it existed nowhere else in Settings. */}
      <section className="space-y-2">
        <ConnectionStatusPanel />
      </section>

      {/* Health panel */}
      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          System Health
        </p>
        {healthQuery.isLoading && <LoadingRow label="health" />}
        {healthQuery.isError   && <ErrorRow   label="health" />}
        {healthQuery.data && <HealthPanel data={healthQuery.data} />}
      </section>

      {/* Traffic panel */}
      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Traffic (this backend session)
        </p>
        {trafficQuery.isLoading && <LoadingRow label="traffic" />}
        {trafficQuery.isError   && <ErrorRow   label="traffic" />}
        {trafficQuery.data && <TrafficPanel data={trafficQuery.data} />}
      </section>

      {/* Latency panel */}
      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Latency (this backend session)
        </p>
        {latencyQuery.isLoading && <LoadingRow label="latency" />}
        {latencyQuery.isError   && <ErrorRow   label="latency" />}
        {latencyQuery.data && <LatencyPanel data={latencyQuery.data} />}
      </section>
    </div>
  );
}

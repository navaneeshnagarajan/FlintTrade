/**
 * MonitoringSection — system health, traffic, and latency panels.
 *
 * APIs:
 *   GET /ft-api/api/v1/health         → broker connections, DuckDB, disk, memory
 *   GET /ft-api/api/v1/traffic/stats  → requests/sec, error rate, top endpoints
 *   GET /ft-api/api/v1/latency/stats  → order latency per broker (avg/p50/p95/p99)
 */

import { useQuery } from "@tanstack/react-query";
import { RefreshCw, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { SectionTitle } from "./shared";
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

function UsageBar({
  label,
  usedPct,
  usedLabel,
  totalLabel,
}: {
  label: string;
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
      <div className="flex items-center justify-between text-xs">
        <span className="text-text-secondary">{label}</span>
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
  const diskFreeGb  = data.disk?.free_gb ?? 0;
  const diskTotalGb = data.disk?.total_gb ?? 0;
  const diskUsedGb  = diskTotalGb - diskFreeGb;
  const diskUsedPct = data.disk?.used_pct ?? pct(diskUsedGb, diskTotalGb);
  const memUsedMb   = data.memory?.used_mb ?? 0;
  const memTotalMb  = data.memory?.total_mb ?? 0;
  const memUsedPct  = data.memory?.used_pct ?? pct(memUsedMb, memTotalMb);

  return (
    <div className="space-y-4">
      {/* Subsystem status */}
      <div>
        <p className="text-xxs text-text-muted uppercase tracking-wider mb-1.5">
          Subsystem Status
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

      {/* Resource usage */}
      <div>
        <p className="text-xxs text-text-muted uppercase tracking-wider mb-1.5">
          Resources
        </p>
        <div className="space-y-2">
          <UsageBar
            label="Disk"
            usedPct={diskUsedPct}
            usedLabel={`${diskUsedGb.toFixed(1)} GB`}
            totalLabel={`${diskTotalGb.toFixed(0)} GB`}
          />
          <UsageBar
            label="Memory"
            usedPct={memUsedPct}
            usedLabel={fmtBytes(memUsedMb)}
            totalLabel={fmtBytes(memTotalMb)}
          />
        </div>
      </div>
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

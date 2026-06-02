/**
 * PnLSummary — intraday P&L tracker panel included inside MTMMonitorWidget.
 *
 * Wires real backend data via GET /ft-api/api/v1/pnl-tracker/summary.
 * Falls back gracefully if the endpoint is not yet available (shows placeholder).
 *
 * Auto-refreshes every 10s during market hours, 60s outside.
 */

import { useQuery } from "@tanstack/react-query";
import { RefreshCw, AlertTriangle } from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import {
  getPnLSummary,
  getPnLTracker,
  type PnLSummary as PnLSummaryType,
  type PnLTrackerEntry,
} from "@/services/ftApi";
import { isMarketHours } from "@/lib/market";

// ---------------------------------------------------------------------------
// Currency formatter
// ---------------------------------------------------------------------------
const INR_FMT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
function fmt(n: number): string {
  return INR_FMT.format(n);
}

// ---------------------------------------------------------------------------
// Metric row
// ---------------------------------------------------------------------------

function MetricRow({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: string;
  colorClass: string;
}) {
  return (
    <div className="flex items-center justify-between px-2 py-1 border-b border-border-subtle last:border-0">
      <span className="text-xxs text-text-muted">{label}</span>
      <span className={`font-mono tabular-nums text-xs font-semibold ${colorClass}`}>
        {value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sparkline — realized P&L chart from tracker entries
// ---------------------------------------------------------------------------

function Sparkline({ entries }: { entries: PnLTrackerEntry[] }) {
  if (entries.length < 2) return null;

  const values = entries.map((e) => e.total_pnl);
  const lastVal  = values[values.length - 1];
  const positive = lastVal >= 0;

  return (
    <FlintMiniSparkline
      points={values}
      positive={positive}
      ariaLabel="Realized P&L tracker trend"
      className="h-7 w-[120px]"
    />
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function PnLSummary() {
  const seriesQuery = useQuery<PnLTrackerEntry[]>({
    queryKey: ["ft", "pnl-tracker"],
    queryFn: getPnLTracker,
    refetchInterval: () => (isMarketHours() ? 10_000 : 60_000),
  });

  const query = useQuery<PnLSummaryType>({
    queryKey: ["ft", "pnl-tracker", "summary"],
    queryFn: getPnLSummary,
    refetchInterval: () => (isMarketHours() ? 10_000 : 60_000),
  });

  if (query.isLoading) {
    return (
      <div className="flex items-center gap-1.5 px-2 py-1 text-xxs text-text-muted">
        <RefreshCw size={10} className="animate-spin" />
        Loading P&L…
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="flex items-center gap-1.5 px-2 py-1 text-xxs text-text-muted">
        <AlertTriangle size={10} className="text-warning" />
        P&L tracker offline
      </div>
    );
  }

  const d = query.data;
  if (!d) return null;

  const totalColor = d.total >= 0 ? "text-profit" : "text-loss";
  const rlColor    = d.realized >= 0 ? "text-profit" : "text-loss";
  const urColor    = d.unrealized >= 0 ? "text-profit" : "text-loss";

  return (
    <div className="border-t border-border-default bg-surface-card">
      {/* Header row */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-border-default">
        <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">
          P&L Tracker
        </span>
        <div className="flex items-center gap-2">
          {(seriesQuery.data ?? []).length > 0 && <Sparkline entries={seriesQuery.data ?? []} />}
          {query.isFetching && (
            <RefreshCw size={9} className="animate-spin text-text-muted" />
          )}
        </div>
      </div>

      {/* Metrics */}
      <div>
        <MetricRow label="Realized P&L"   value={fmt(d.realized)}   colorClass={rlColor}    />
        <MetricRow label="Unrealized P&L" value={fmt(d.unrealized)} colorClass={urColor}    />
        <MetricRow label="Total P&L"      value={fmt(d.total)}      colorClass={totalColor} />
        <MetricRow
          label="Max Drawdown"
          value={fmt(Math.abs(d.max_total - d.min_total))}
          colorClass="text-warning"
        />
      </div>
    </div>
  );
}

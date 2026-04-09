/**
 * GlobalIndicesWidget — World market indices tracker for FlintTrade.
 *
 * Features:
 *   - Table of 10 global indices grouped by region: India, US, Europe, Asia
 *   - Columns: name, LTP, change, change%, sparkline
 *   - Positive change highlighted green, negative red
 *   - Auto-refresh every 30s when connected
 *   - Sample data in explore mode; REST polling in live mode
 */

import { useEffect, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Globe, RefreshCw, Loader2 } from "lucide-react";
import { getGlobalIndices } from "@/services/ftApi";
import type { GlobalIndexEntry } from "@/services/ftApi";
import { SAMPLE_INDICES, SAMPLE_UPDATED_AT } from "./sampleData";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REGIONS = ["India", "US", "Europe", "Asia"] as const;
type Region = (typeof REGIONS)[number];

// ---------------------------------------------------------------------------
// Sparkline (inline SVG)
// ---------------------------------------------------------------------------

interface SparklineProps {
  data: number[];
  positive: boolean;
}

function Sparkline({ data, positive }: SparklineProps) {
  if (data.length < 2) return null;
  const w = 60;
  const h = 20;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 0.0001;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const colour = positive ? "#22c55e" : "#ef4444";
  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      aria-label="30-day index sparkline"
      role="img"
    >
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={colour}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Index row
// ---------------------------------------------------------------------------

interface IndexRowProps {
  entry: GlobalIndexEntry;
}

function IndexRow({ entry }: IndexRowProps) {
  const positive = entry.change_pct >= 0;
  const changeClass = positive ? "text-profit" : "text-loss";

  return (
    <tr className="border-b border-border-subtle hover:bg-surface-hover/40 transition-colors">
      <td className="px-2 py-1.5">
        <span className="text-xs font-medium text-text-primary">{entry.name}</span>
      </td>
      <td className="px-2 py-1.5 text-right">
        <span className="text-xs font-mono tabular-nums text-text-primary">
          {entry.ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
        </span>
      </td>
      <td className="px-2 py-1.5 text-right">
        <span className={cn("text-xs font-mono tabular-nums", changeClass)}>
          {positive ? "+" : ""}{entry.change.toFixed(2)}
        </span>
      </td>
      <td className="px-2 py-1.5 text-right">
        <span className={cn("text-xs font-mono tabular-nums font-semibold", changeClass)}>
          {positive ? "+" : ""}{entry.change_pct.toFixed(2)}%
        </span>
      </td>
      <td className="px-2 py-1.5">
        <Sparkline data={entry.history} positive={positive} />
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Region group header
// ---------------------------------------------------------------------------

interface RegionHeaderProps {
  region: Region;
}

function RegionHeader({ region }: RegionHeaderProps) {
  return (
    <tr>
      <td
        colSpan={5}
        className="px-2 pt-2 pb-0.5 text-xxs font-semibold uppercase tracking-wider text-text-muted bg-surface-elevated border-b border-border-default"
      >
        {region}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function GlobalIndicesWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  useEffect(() => {
    track("trade", "widget_view_global_indices");
  }, [track]);

  const {
    data: liveData,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ["globalIndices"],
    queryFn: getGlobalIndices,
    enabled: isConnected,
    refetchInterval: isConnected ? 30_000 : false,
    staleTime: 25_000,
  });

  const indices: GlobalIndexEntry[] = isConnected
    ? (liveData?.indices ?? SAMPLE_INDICES)
    : SAMPLE_INDICES;

  const updatedAt: string = isConnected
    ? (liveData?.updated_at ?? SAMPLE_UPDATED_AT)
    : SAMPLE_UPDATED_AT;

  const byRegion = REGIONS.reduce<Record<Region, GlobalIndexEntry[]>>(
    (acc, r) => {
      acc[r] = indices.filter((e) => e.region === r);
      return acc;
    },
    { India: [], US: [], Europe: [], Asia: [] },
  );

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <Globe size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Global Indices</span>
        <div className="flex-1" />
        {isConnected && (
          <button
            onClick={() => void refetch()}
            disabled={isFetching}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            aria-label="Refresh global indices"
          >
            <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} aria-hidden="true" />
          </button>
        )}
      </div>

      {/* Loading */}
      {isConnected && isLoading && (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
          <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          Loading indices...
        </div>
      )}

      {/* Table */}
      {!isLoading && (
        <div className="flex-1 overflow-auto">
          <table className="w-full border-collapse" aria-label="Global market indices">
            <thead>
              <tr className="border-b border-border-default sticky top-0 bg-surface-card z-10">
                <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-left">Index</th>
                <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-right">LTP</th>
                <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-right">Chg</th>
                <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-right">Chg%</th>
                <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted">Trend</th>
              </tr>
            </thead>
            <tbody>
              {REGIONS.flatMap((region) =>
                byRegion[region].length > 0
                  ? [
                      <RegionHeader key={`hdr-${region}`} region={region} />,
                      ...byRegion[region].map((entry) => (
                        <IndexRow key={entry.id} entry={entry} />
                      )),
                    ]
                  : [],
              )}
            </tbody>
          </table>

          {/* Footer */}
          <div className="px-2 py-1.5 text-xxs text-text-muted border-t border-border-subtle">
            Updated: {new Date(updatedAt).toLocaleTimeString("en-IN", {
              timeZone: "Asia/Kolkata",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            })} IST
            {!isConnected && (
              <span className="ml-2 text-accent/70">(sample data)</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(GlobalIndicesWidget);

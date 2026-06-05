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
import { Globe, RefreshCw, Loader2, Inbox } from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import { Button } from "@/components/ui/button";
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

interface SparklineProps {
  data: number[];
  positive: boolean;
}

function Sparkline({ data, positive }: SparklineProps) {
  if (data.length < 2) return null;

  return (
    <FlintMiniSparkline
      points={data}
      positive={positive}
      ariaLabel="30-day index sparkline"
      className="h-5 w-[60px]"
    />
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

  // When connected, only ever show the live response — never the SAMPLE
  // constant. An empty/undefined live response renders an honest empty state
  // (see below), so a connected (live) user never sees fabricated rows.
  // The SAMPLE constant is reserved for the not-connected/explore branch and
  // is always paired with a visible "Sample data" affordance.
  const indices: GlobalIndexEntry[] = isConnected
    ? (liveData?.indices ?? [])
    : SAMPLE_INDICES;

  const isSample = !isConnected;

  const updatedAt: string = isConnected
    ? (liveData?.updated_at ?? "")
    : SAMPLE_UPDATED_AT;

  const isEmpty = indices.length === 0;

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
        {/* Honest disclosure — when disconnected the rows are SAMPLE_INDICES
            (indices = isConnected ? liveData : SAMPLE_INDICES). */}
        {!isConnected && (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing sample data; connect a broker for live global indices"
            title="Not connected — showing illustrative sample index values so the widget is usable in explore mode."
          >
            Sample data
          </span>
        )}
        <div className="flex-1" />
        {isConnected && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="h-6 w-6 p-0 text-text-muted hover:text-text-primary disabled:opacity-40"
            aria-label="Refresh global indices"
          >
            <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} aria-hidden="true" />
          </Button>
        )}
      </div>

      {/* Loading */}
      {isConnected && isLoading && (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
          <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          Loading indices...
        </div>
      )}

      {/* Honest empty state — connected but the live response had no indices.
          A connected (live) user must never see fabricated sample rows. */}
      {!isLoading && isEmpty && (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-text-muted text-sm px-4 text-center">
          <Inbox size={18} aria-hidden="true" />
          <span>No global indices available</span>
        </div>
      )}

      {/* Table */}
      {!isLoading && !isEmpty && (
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
            {isSample && (
              <span className="ml-2 text-accent/70">(sample data)</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(GlobalIndicesWidget);

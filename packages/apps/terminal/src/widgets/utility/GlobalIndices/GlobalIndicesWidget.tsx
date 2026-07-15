/**
 * GlobalIndicesWidget — World market indices tracker for FlintTrade.
 *
 * Features:
 *   - Table of 10 global indices grouped by region: India, US, Europe, Asia
 *   - Columns: name, LTP, change, change%, sparkline
 *   - Positive change highlighted green, negative red
 *   - Auto-refresh every 30s for explicitly live responses
 *   - Local sample data in explore mode; REST polling in live mode
 *   - "Sample data" badge derives from the response's is_sample_data flag,
 *     not from connection state — the backend endpoint is currently a stub
 *     serving fabricated prices even to connected users, and those rows must
 *     never render as live
 */

import { useEffect, useState, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Globe, RefreshCw, Loader2, Inbox } from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import { Button } from "@/components/ui/button";
import { getGlobalIndices } from "@/services/ftApi";
import type { GlobalIndexEntry } from "@/services/ftApi";
import { SAMPLE_INDICES } from "./sampleData";
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
  const [isRetrying, setIsRetrying] = useState(false);

  useEffect(() => {
    track("trade", "widget_view_global_indices");
  }, [track]);

  const {
    data: liveData,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["globalIndices"],
    queryFn: getGlobalIndices,
    enabled: isConnected,
    refetchInterval: (query) =>
      isConnected && query.state.data?.is_sample_data === false ? 30_000 : false,
    staleTime: 25_000,
  });

  // When connected, only ever show the live response — never the local
  // SAMPLE constant. But the backend endpoint is itself a hardcoded stub
  // that declares `is_sample_data: true`, so a connected response can STILL
  // be fabricated: the badge must key off the response flag, not off
  // connection state (badging on `!isConnected` alone rendered stub prices
  // as live the moment a broker connected).
  const indices: GlobalIndexEntry[] = isConnected
    ? (liveData?.indices ?? [])
    : SAMPLE_INDICES;

  // Live affordances fail closed: an omitted flag means unknown provenance.
  const isExplicitlyLive = isConnected && liveData?.is_sample_data === false;
  const isSample = !isExplicitlyLive;

  // A timestamp is a live freshness claim, so unknown/sample responses never
  // render one even if a malformed payload includes it.
  const updatedAt = isExplicitlyLive ? (liveData?.updated_at ?? "") : "";

  const isEmpty = indices.length === 0;

  const retry = async () => {
    setIsRetrying(true);
    try {
      await refetch();
    } finally {
      setIsRetrying(false);
    }
  };

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
        {/* Honest disclosure — shows whenever the rows on screen are
            fabricated: the local SAMPLE constant (disconnected) OR a backend
            payload flagged is_sample_data (the endpoint is currently a stub
            even for connected users). */}
        {isSample && (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing sample global indices or data with unknown provenance, not verified live prices"
            title="These index values are sample data or have unknown provenance, not verified live prices — do not base trading decisions on them."
          >
            Sample data
          </span>
        )}
        <div className="flex-1" />
        {isExplicitlyLive && !isLoading && !isError && (
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
          {isRetrying ? "Retrying global indices..." : "Loading indices..."}
        </div>
      )}

      {/* Request failure is distinct from a successful empty response. */}
      {isConnected && !isLoading && isError && (
        <div
          className="flex-1 flex flex-col items-center justify-center gap-2 px-4 text-center"
          role="alert"
        >
          <AlertCircle size={18} className="text-loss" aria-hidden="true" />
          <span className="text-sm font-medium text-text-primary">Could not load global indices</span>
          <span className="text-xs text-text-muted">
            {error instanceof Error ? error.message : "The request failed."}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void retry()}
            disabled={isRetrying}
            className="mt-1 h-7 px-2 text-xs"
            aria-label="Retry global indices"
          >
            <RefreshCw size={12} className={isRetrying ? "animate-spin" : ""} aria-hidden="true" />
            {isRetrying ? "Retrying..." : "Retry"}
          </Button>
        </div>
      )}

      {/* Honest empty state — connected but the live response had no indices.
          A connected (live) user must never see fabricated sample rows. */}
      {!isLoading && !isError && isEmpty && (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-text-muted text-sm px-4 text-center">
          <Inbox size={18} aria-hidden="true" />
          <span>No global indices available</span>
        </div>
      )}

      {/* Table */}
      {!isLoading && !isError && !isEmpty && (
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

          {/* Footer — sample payloads carry no timestamp, so never invent one. */}
          <div className="px-2 py-1.5 text-xxs text-text-muted border-t border-border-subtle">
            {updatedAt && (
              <>
                Updated: {new Date(updatedAt).toLocaleTimeString("en-IN", {
                  timeZone: "Asia/Kolkata",
                  hour: "2-digit",
                  minute: "2-digit",
                  hour12: false,
                })} IST
              </>
            )}
            {isSample && (
              <span className={updatedAt ? "ml-2 text-accent/70" : "text-accent/70"}>
                (sample data)
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(GlobalIndicesWidget);

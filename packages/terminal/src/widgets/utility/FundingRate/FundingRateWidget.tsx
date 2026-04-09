/**
 * FundingRateWidget — Crypto perpetual funding rate tracker for FlintTrade.
 *
 * Features:
 *   - Table of Delta Exchange perpetual pairs with current funding rate,
 *     predicted next rate, countdown to next funding event, and open interest
 *   - 7-day sparkline for each symbol (SVG, inline)
 *   - Positive rates highlighted green (longs pay shorts)
 *   - Negative rates highlighted red (shorts pay longs)
 *   - Sort by rate magnitude (default) or alphabetical
 *   - Auto-refresh every 60s
 *   - FeatureTeaser over sample data in explore/disconnected mode
 */

import { useState, useMemo, useCallback, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Loader2, AlertCircle, ArrowUpDown, TrendingUp, TrendingDown } from "lucide-react";
import { getCryptoFundingRates } from "@/services/ftApi";
import type { FundingRateEntry } from "@/services/ftApi";
import { SAMPLE_FUNDING_RATES } from "./sampleData";
import { useCountdown } from "./useCountdown";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/** Format a funding rate fraction as a percentage string with sign. */
function formatRate(r: number): string {
  const pct = r * 100;
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(4)}%`;
}

/** Format open interest in USD with K/M/B suffix. */
function formatOI(oi: number | null): string {
  if (oi == null) return "—";
  if (oi >= 1e9) return `$${(oi / 1e9).toFixed(2)}B`;
  if (oi >= 1e6) return `$${(oi / 1e6).toFixed(1)}M`;
  if (oi >= 1e3) return `$${(oi / 1e3).toFixed(0)}K`;
  return `$${oi}`;
}

// ---------------------------------------------------------------------------
// Sparkline (pure SVG, no deps)
// ---------------------------------------------------------------------------

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
}

function Sparkline({ data, width = 80, height = 24 }: SparklineProps) {
  if (!data.length) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 0.0001;

  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const lastVal = data[data.length - 1];
  const prevVal = data[data.length - 2] ?? lastVal;
  const lineColour = lastVal >= prevVal ? "#22c55e" : "#ef4444";

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-label="7-day funding rate sparkline"
      role="img"
    >
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={lineColour}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Single funding row with countdown
// ---------------------------------------------------------------------------

interface FundingRowProps {
  entry: FundingRateEntry;
}

function FundingRow({ entry }: FundingRowProps) {
  const countdown = useCountdown(entry.next_funding_ms);

  const rateClass =
    entry.rate > 0
      ? "text-profit"
      : entry.rate < 0
        ? "text-loss"
        : "text-text-secondary";

  const predictedClass =
    entry.predicted_rate > 0
      ? "text-profit/80"
      : entry.predicted_rate < 0
        ? "text-loss/80"
        : "text-text-muted";

  return (
    <tr className="border-b border-border-subtle hover:bg-surface-hover/40 transition-colors">
      {/* Symbol */}
      <td className="px-3 py-2">
        <div className="flex items-center gap-1.5">
          {entry.rate > 0 ? (
            <TrendingUp size={11} className="text-profit shrink-0" aria-hidden="true" />
          ) : entry.rate < 0 ? (
            <TrendingDown size={11} className="text-loss shrink-0" aria-hidden="true" />
          ) : null}
          <span className="text-xs font-mono font-semibold text-text-primary">
            {entry.symbol}
          </span>
        </div>
      </td>

      {/* Current rate */}
      <td className="px-3 py-2 text-right">
        <span className={`text-xs font-mono tabular-nums font-semibold ${rateClass}`}>
          {formatRate(entry.rate)}
        </span>
      </td>

      {/* Predicted rate */}
      <td className="px-3 py-2 text-right">
        <span className={`text-xs font-mono tabular-nums ${predictedClass}`}>
          {formatRate(entry.predicted_rate)}
        </span>
      </td>

      {/* Next funding countdown */}
      <td className="px-3 py-2 text-right">
        <span className="text-xs font-mono tabular-nums text-text-secondary">
          {countdown}
        </span>
      </td>

      {/* OI */}
      <td className="px-3 py-2 text-right">
        <span className="text-xs font-mono tabular-nums text-text-muted">
          {formatOI(entry.open_interest_usd)}
        </span>
      </td>

      {/* 7-day sparkline */}
      <td className="px-3 py-2">
        <Sparkline data={entry.history} />
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Sort controls
// ---------------------------------------------------------------------------

type SortMode = "magnitude" | "alpha" | "rate";

function sortEntries(entries: FundingRateEntry[], mode: SortMode): FundingRateEntry[] {
  return [...entries].sort((a, b) => {
    if (mode === "magnitude") return Math.abs(b.rate) - Math.abs(a.rate);
    if (mode === "rate") return b.rate - a.rate;
    return a.symbol.localeCompare(b.symbol);
  });
}

// ---------------------------------------------------------------------------
// Rate summary banner
// ---------------------------------------------------------------------------

interface SummaryBannerProps {
  entries: FundingRateEntry[];
}

function SummaryBanner({ entries }: SummaryBannerProps) {
  const positive = entries.filter((e) => e.rate > 0).length;
  const negative = entries.filter((e) => e.rate < 0).length;
  const avgRate = entries.reduce((s, e) => s + e.rate, 0) / (entries.length || 1);

  return (
    <div className="flex items-center gap-4 px-3 py-1.5 bg-surface-base border-b border-border-subtle text-xs">
      <div className="flex items-center gap-1.5">
        <span className="text-text-muted uppercase tracking-wide">Positive</span>
        <span className="font-mono font-semibold text-profit">{positive}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-text-muted uppercase tracking-wide">Negative</span>
        <span className="font-mono font-semibold text-loss">{negative}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-text-muted uppercase tracking-wide">Avg Rate</span>
        <span className={`font-mono font-semibold tabular-nums ${avgRate >= 0 ? "text-profit" : "text-loss"}`}>
          {formatRate(avgRate)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function FundingRateWidget() {
  const [sortMode, setSortMode] = useState<SortMode>("magnitude");

  const isConnected = useBrokerConnected();

  const {
    data: liveData,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["cryptoFundingRates"],
    queryFn: getCryptoFundingRates,
    enabled: isConnected,
    refetchInterval: isConnected ? 60_000 : false,
    staleTime: 55_000,
  });

  const rawData = isConnected ? liveData : SAMPLE_FUNDING_RATES;

  const sortedEntries = useMemo(() => {
    if (!rawData?.rates?.length) return [];
    return sortEntries(rawData.rates, sortMode);
  }, [rawData, sortMode]);

  const cycleSortMode = useCallback(() => {
    setSortMode((prev) =>
      prev === "magnitude" ? "rate" : prev === "rate" ? "alpha" : "magnitude",
    );
  }, []);

  const sortLabel: Record<SortMode, string> = {
    magnitude: "Sort: Magnitude",
    rate: "Sort: Rate ↑",
    alpha: "Sort: A–Z",
  };

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <span className="text-xs font-medium text-text-primary">Funding Rates</span>
        <span className="text-xxs text-text-muted px-1.5 py-0.5 rounded bg-surface-hover border border-border-subtle">
          Delta Exchange
        </span>

        <div className="flex-1" />

        <button
          onClick={cycleSortMode}
          className="flex items-center gap-1 px-2 py-0.5 text-xs text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors border border-border-subtle"
          aria-label="Cycle sort order"
        >
          <ArrowUpDown size={11} aria-hidden="true" />
          {sortLabel[sortMode]}
        </button>

        <button
          onClick={() => void refetch()}
          disabled={isFetching}
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
          title="Refresh"
          aria-label="Refresh funding rates"
        >
          <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Error banner */}
      {isError && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} aria-hidden="true" />
          <span>{(error as Error)?.message ?? "Failed to load funding rates"}</span>
        </div>
      )}

      {/* Loading */}
      {isConnected && isLoading && (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
          <Loader2 size={16} className="animate-spin" aria-hidden="true" />
          Loading funding rates...
        </div>
      )}

      {/* Summary + table */}
      {rawData && (() => {
        const tableContent = (
          <div className="flex-1 flex flex-col min-h-0 overflow-auto">
            {sortedEntries.length > 0 && (
              <SummaryBanner entries={sortedEntries} />
            )}

            <table className="w-full text-left border-collapse" aria-label="Crypto perpetual funding rates">
              <thead>
                <tr className="border-b border-border-default sticky top-0 bg-surface-card z-10">
                  <th className="px-3 py-2 text-xxs font-medium uppercase tracking-wide text-text-muted">Symbol</th>
                  <th className="px-3 py-2 text-xxs font-medium uppercase tracking-wide text-text-muted text-right">Rate (8h)</th>
                  <th className="px-3 py-2 text-xxs font-medium uppercase tracking-wide text-text-muted text-right">Predicted</th>
                  <th className="px-3 py-2 text-xxs font-medium uppercase tracking-wide text-text-muted text-right">Next Funding</th>
                  <th className="px-3 py-2 text-xxs font-medium uppercase tracking-wide text-text-muted text-right">OI (USD)</th>
                  <th className="px-3 py-2 text-xxs font-medium uppercase tracking-wide text-text-muted">7d History</th>
                </tr>
              </thead>
              <tbody>
                {sortedEntries.map((entry) => (
                  <FundingRow key={entry.symbol} entry={entry} />
                ))}
              </tbody>
            </table>

            {sortedEntries.length === 0 && !isLoading && (
              <div className="flex-1 flex items-center justify-center text-text-muted text-sm py-8">
                No funding rate data available
              </div>
            )}

            {/* Last updated */}
            {rawData.updated_at && (
              <div className="flex-none px-3 py-1.5 text-xxs text-text-muted border-t border-border-subtle">
                Updated: {new Date(rawData.updated_at).toLocaleTimeString("en-IN", {
                  timeZone: "Asia/Kolkata",
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                  hour12: false,
                })} IST
              </div>
            )}
          </div>
        );

        return isConnected ? (
          tableContent
        ) : (
          <FeatureTeaser
            status="preview"
            featureName="Funding Rates"
            version="v0.6.0"
          >
            {tableContent}
          </FeatureTeaser>
        );
      })()}
    </div>
  );
}

export default memo(FundingRateWidget);

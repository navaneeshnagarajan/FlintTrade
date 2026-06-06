/**
 * CorrelationPairsWidget — Correlated instrument pair signals for FlintTrade terminal.
 *
 * Features:
 *   - Table of pre-built correlated instrument pairs
 *   - Columns: pair, correlation coefficient, divergence (current spread vs mean), signal
 *   - Signal: Converging / Diverging / Neutral based on spread z-score
 *   - Colour-coded rows; sortable by correlation or divergence
 *
 * DATA HONESTY: when a broker is connected, the widget fetches live daily bars
 * for the preset legs (NSE equities/indices) via `/api/v1/history`, derives
 * each symbol's price + returns series, and runs them through the pair-
 * correlation engine (`/v1/analytics/pairs`) — showing a "Live" badge. The
 * commodity/currency presets (GOLD/USDINR) are skipped server-side when their
 * legs are absent. When no broker is connected, or the engine returns no
 * pairs, the widget falls back to the deterministic SAMPLE_PAIRS with an amber
 * "Sample data" badge so nothing implies the figures are live.
 */

import { useState, useMemo, memo } from "react";
import { Link, ArrowUp, ArrowDown, Minus, TrendingUp, TrendingDown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getHistory } from "@/services/api";
import { getPairCorrelation } from "@/services/ftApi.analysis";
import type { PairSignal, PairSeries } from "@/services/ftApi.analysis";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Signal = "Converging" | "Diverging" | "Neutral";
type SortKey = "correlation" | "divergence";

interface PairData {
  id: string;
  assetA: string;
  assetB: string;
  correlation: number;    // -1 to +1
  spreadMean: number;     // historical mean spread
  spreadCurrent: number;  // current spread
  spreadStd: number;      // historical std of spread
  signal: Signal;
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const SAMPLE_PAIRS: PairData[] = [
  {
    id: "nifty-banknifty",
    assetA: "NIFTY",
    assetB: "BANKNIFTY",
    correlation: 0.94,
    spreadMean: 25_700,
    spreadCurrent: 26_150,
    spreadStd: 380,
    signal: "Diverging",
  },
  {
    id: "gold-usdinr",
    assetA: "GOLD",
    assetB: "USDINR",
    correlation: 0.81,
    spreadMean: 53_200,
    spreadCurrent: 53_050,
    spreadStd: 420,
    signal: "Converging",
  },
  {
    id: "reliance-nifty",
    assetA: "RELIANCE",
    assetB: "NIFTY",
    correlation: 0.76,
    spreadMean: 19_560,
    spreadCurrent: 19_480,
    spreadStd: 210,
    signal: "Converging",
  },
  {
    id: "hdfcbank-banknifty",
    assetA: "HDFCBANK",
    assetB: "BANKNIFTY",
    correlation: 0.89,
    spreadMean: 46_520,
    spreadCurrent: 46_890,
    spreadStd: 340,
    signal: "Diverging",
  },
  {
    id: "tcs-infy",
    assetA: "TCS",
    assetB: "INFY",
    correlation: 0.72,
    spreadMean: 1_890,
    spreadCurrent: 1_910,
    spreadStd: 85,
    signal: "Neutral",
  },
  {
    id: "crude-usdinr",
    assetA: "CRUDE",
    assetB: "USDINR",
    correlation: -0.68,
    spreadMean: -5_720,
    spreadCurrent: -5_840,
    spreadStd: 290,
    signal: "Diverging",
  },
];

// ---------------------------------------------------------------------------
// Live data (daily history per leg → /v1/analytics/pairs engine)
// ---------------------------------------------------------------------------

/** Preset legs we can source live from NSE history. The engine skips any
 *  preset pair (e.g. GOLD/USDINR) whose legs are absent from the payload. */
const LIVE_LEGS: ReadonlyArray<{ symbol: string; exchange: string }> = [
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "RELIANCE", exchange: "NSE" },
  { symbol: "HDFCBANK", exchange: "NSE" },
  { symbol: "TCS", exchange: "NSE" },
  { symbol: "INFY", exchange: "NSE" },
];

function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 24 * 3600 * 1000).toISOString().slice(0, 10);
}

/** Derive simple returns from a close-price series. */
function toReturns(prices: number[]): number[] {
  const returns: number[] = [];
  for (let i = 1; i < prices.length; i += 1) {
    const prev = prices[i - 1];
    returns.push(prev !== 0 ? (prices[i] - prev) / prev : 0);
  }
  return returns;
}

/** Fetch daily history for every live leg and run the pair-correlation engine. */
async function fetchPairSignals(): Promise<PairSignal[]> {
  const end = new Date().toISOString().slice(0, 10);
  const start = isoDaysAgo(120);
  const entries = await Promise.all(
    LIVE_LEGS.map(async ({ symbol, exchange }) => {
      const bars = await getHistory(symbol, exchange, "1D", start, end);
      const prices = (bars ?? []).map((bar) => bar.close);
      const series: PairSeries = { prices, returns: toReturns(prices) };
      return [symbol, series] as const;
    }),
  );
  const data = Object.fromEntries(entries) as Record<string, PairSeries>;
  const result = await getPairCorrelation(data);
  return result.signals ?? [];
}

/** Map an engine signal to the widget's display row. */
function toPairData(sig: PairSignal): PairData {
  const [assetA, assetB] = sig.pair;
  const signal: Signal =
    sig.signal === "diverging" ? "Diverging" : sig.signal === "converging" ? "Converging" : "Neutral";
  return {
    id: `${assetA}-${assetB}`.toLowerCase(),
    assetA,
    assetB,
    correlation: sig.correlation,
    spreadMean: sig.mean_spread,
    spreadCurrent: sig.current_spread,
    spreadStd: sig.std_spread,
    signal,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function zScore(current: number, mean: number, std: number): number {
  if (std === 0) return 0;
  return (current - mean) / std;
}

function signalColour(signal: Signal): string {
  switch (signal) {
    case "Converging": return "text-profit bg-profit/10 border-profit/30";
    case "Diverging":  return "text-loss bg-loss/10 border-loss/30";
    default:           return "text-text-muted bg-surface-hover border-border-default";
  }
}

function SignalIcon({ signal }: { signal: Signal }) {
  if (signal === "Converging") return <TrendingUp size={10} aria-hidden="true" />;
  if (signal === "Diverging")  return <TrendingDown size={10} aria-hidden="true" />;
  return <Minus size={10} aria-hidden="true" />;
}

function corrColour(corr: number): string {
  if (corr >= 0.8) return "text-profit";
  if (corr >= 0.5) return "text-warning";
  if (corr >= 0) return "text-text-secondary";
  return "text-loss";
}

// ---------------------------------------------------------------------------
// Sort arrow component
// ---------------------------------------------------------------------------

interface SortArrowProps {
  active: boolean;
  direction: "asc" | "desc";
}

function SortArrow({ active, direction }: SortArrowProps) {
  if (!active) return <Minus size={9} className="text-text-muted opacity-40" aria-hidden="true" />;
  return direction === "asc"
    ? <ArrowUp size={9} className="text-accent" aria-hidden="true" />
    : <ArrowDown size={9} className="text-accent" aria-hidden="true" />;
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function CorrelationPairsWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();
  const [sortKey, setSortKey] = useState<SortKey>("correlation");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // Live pair signals — only fetched once a broker is connected.
  const { data: liveSignals } = useQuery({
    queryKey: ["correlation-pairs"],
    queryFn: fetchPairSignals,
    enabled: isConnected,
    staleTime: 5 * 60_000,
    refetchInterval: isConnected ? 5 * 60_000 : false,
    retry: false,
  });

  const livePairs = useMemo(() => (liveSignals ?? []).map(toPairData), [liveSignals]);
  const isLive = isConnected && livePairs.length >= 1;
  const pairs = isLive ? livePairs : SAMPLE_PAIRS;

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
    track("trade", `correlationpairs_sort_${key}`);
  };

  const sortedPairs = useMemo(() => {
    const copy = [...pairs];
    copy.sort((a, b) => {
      let va: number;
      let vb: number;
      if (sortKey === "correlation") {
        va = Math.abs(a.correlation);
        vb = Math.abs(b.correlation);
      } else {
        va = Math.abs(zScore(a.spreadCurrent, a.spreadMean, a.spreadStd));
        vb = Math.abs(zScore(b.spreadCurrent, b.spreadMean, b.spreadStd));
      }
      return sortDir === "desc" ? vb - va : va - vb;
    });
    return copy;
  }, [pairs, sortKey, sortDir]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Link size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Correlation Pairs</span>
        {/* Data-source badge — flips to "Live" only when a broker is connected
            AND the engine returned at least one real pair. Otherwise it stays on
            the honest amber "Sample data" affordance so a connected user is
            never misled into trusting fabricated figures. */}
        {isLive ? (
          <span
            className="ml-1 px-1.5 py-0.5 text-xxs bg-profit/10 text-profit border border-profit/30 rounded"
            role="status"
            aria-label="Showing live correlation signals from the connected broker"
            title="Live pair-correlation signals computed from the connected broker's daily bars."
          >
            Live
          </span>
        ) : (
          <span
            className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
            role="status"
            aria-label="Showing sample data; no live correlation data source is wired yet"
            title="No live data wired yet — showing sample correlation pairs so the widget is usable in explore mode."
          >
            Sample data
          </span>
        )}
        <div className="flex-1" />
      </div>

      {/* Table */}
      <div className="flex-1 min-h-0 overflow-auto">
        <table className="w-full text-xs" aria-label="Correlation pairs table">
          <thead className="sticky top-0 bg-surface-card border-b border-border-default z-10">
            <tr>
              <th className="text-left px-2 py-1.5 text-text-muted font-medium whitespace-nowrap">
                Pair
              </th>
              <th
                className="text-right px-2 py-1.5 text-text-muted font-medium whitespace-nowrap cursor-pointer hover:text-text-primary select-none"
                onClick={() => handleSort("correlation")}
                aria-sort={sortKey === "correlation" ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
              >
                <span className="flex items-center justify-end gap-1">
                  Corr
                  <SortArrow active={sortKey === "correlation"} direction={sortDir} />
                </span>
              </th>
              <th
                className="text-right px-2 py-1.5 text-text-muted font-medium whitespace-nowrap cursor-pointer hover:text-text-primary select-none"
                onClick={() => handleSort("divergence")}
                aria-sort={sortKey === "divergence" ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
              >
                <span className="flex items-center justify-end gap-1">
                  Z-Score
                  <SortArrow active={sortKey === "divergence"} direction={sortDir} />
                </span>
              </th>
              <th className="text-center px-2 py-1.5 text-text-muted font-medium whitespace-nowrap">
                Signal
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedPairs.map((pair) => {
              const z = zScore(pair.spreadCurrent, pair.spreadMean, pair.spreadStd);
              const zSign = z >= 0 ? "+" : "";
              return (
                <tr
                  key={pair.id}
                  className="border-b border-border-default hover:bg-surface-hover transition-colors"
                >
                  <td className="px-2 py-2 font-medium text-text-primary whitespace-nowrap">
                    <span>{pair.assetA}</span>
                    <span className="text-text-muted mx-1">↔</span>
                    <span>{pair.assetB}</span>
                  </td>
                  <td className={`px-2 py-2 text-right font-mono tabular-nums font-semibold ${corrColour(pair.correlation)}`}>
                    {pair.correlation.toFixed(2)}
                  </td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-text-secondary">
                    {zSign}{z.toFixed(2)}σ
                  </td>
                  <td className="px-2 py-2 text-center">
                    <span
                      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-xxs font-medium ${signalColour(pair.signal)}`}
                    >
                      <SignalIcon signal={pair.signal} />
                      {pair.signal}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer note */}
      <div className="flex-none px-2 py-1.5 border-t border-border-default">
        <p className="text-xxs text-text-muted">
          Z-score &gt; +1.5 = Diverging · Z &lt; -1.5 = Converging · Correlation based on 20-day rolling returns
        </p>
      </div>
    </div>
  );
}

export default memo(CorrelationPairsWidget);

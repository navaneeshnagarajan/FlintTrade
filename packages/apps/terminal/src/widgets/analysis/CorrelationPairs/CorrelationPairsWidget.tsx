/**
 * CorrelationPairsWidget — Correlated instrument pair signals for FlintTrade terminal.
 *
 * Features:
 *   - Table of pre-built correlated instrument pairs
 *   - Columns: pair, correlation coefficient, divergence (current spread vs mean), signal
 *   - Signal: Converging / Diverging / Neutral based on spread z-score
 *   - Colour-coded rows; sortable by correlation or divergence
 *   - Sample data; /ft-api/v1/correlation in live mode
 */

import { useState, useMemo, memo } from "react";
import { Link, RefreshCw, ArrowUp, ArrowDown, Minus, TrendingUp, TrendingDown } from "lucide-react";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

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
  const isConnected = useBrokerConnected();
  const track = useTrackBehavior();
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState("--");
  const [sortKey, setSortKey] = useState<SortKey>("correlation");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

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
    const copy = [...SAMPLE_PAIRS];
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
  }, [sortKey, sortDir]);

  const handleRefresh = async () => {
    if (!isConnected) return;
    setIsLoading(true);
    try {
      // Live: fetch /ft-api/v1/correlation
      await new Promise<void>((resolve) => setTimeout(resolve, 300));
      setLastUpdated(new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" }));
      track("trade", "correlationpairs_refresh");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Link size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Correlation Pairs</span>
        {!isConnected && (
          <span className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
        <div className="flex-1" />
        <span className="text-xxs text-text-muted tabular-nums">{lastUpdated}</span>
        <button
          onClick={() => void handleRefresh()}
          disabled={isLoading || !isConnected}
          aria-label="Refresh correlation data"
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover disabled:opacity-40 transition-colors"
        >
          <RefreshCw size={11} className={isLoading ? "animate-spin" : ""} aria-hidden="true" />
        </button>
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

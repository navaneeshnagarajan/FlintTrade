/**
 * MultiTimeframeWidget — Signal alignment across 5m/15m/1h/1D timeframes.
 *
 * Features:
 *   - Trend direction (arrow), RSI, MACD histogram sign, EMA position per timeframe
 *   - Row colour: all bullish = green, all bearish = red, mixed = amber
 *   - Confluence score: count of agreeing timeframes
 *   - Symbol selector
 *
 * DATA HONESTY: when a broker is connected, the widget fetches live OHLCV bars
 * for each timeframe via the shared `/api/v1/history` path and runs them
 * through the screener's multi-timeframe analyser (`/v1/analytics/mtf`, which
 * computes RSI/MACD/EMA server-side) — showing a "Live" badge. When no broker
 * is connected, or the analyser returns no usable timeframes, it falls back to
 * the deterministic SAMPLE map with an amber "Sample data" badge so signals are
 * never mistaken for live.
 */

import { useState, useMemo, memo } from "react";
import { Layers, ChevronDown, ArrowUp, ArrowDown, Minus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getHistory } from "@/services/api";
import { getMultiTimeframe } from "@/services/ftApi.analysis";
import type { MtfBar, MtfSignal } from "@/services/ftApi.analysis";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Direction = "bullish" | "bearish" | "neutral";

interface TimeframeSignal {
  tf: string;
  trend: Direction;
  rsi: number;
  macdSign: "positive" | "negative" | "flat";
  emaPosition: "above" | "below" | "at";
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const SAMPLE: Record<string, TimeframeSignal[]> = {
  NIFTY: [
    { tf: "5m",  trend: "bullish", rsi: 58.4, macdSign: "positive", emaPosition: "above" },
    { tf: "15m", trend: "bullish", rsi: 62.1, macdSign: "positive", emaPosition: "above" },
    { tf: "1h",  trend: "neutral", rsi: 51.7, macdSign: "negative", emaPosition: "at"    },
    { tf: "1D",  trend: "bearish", rsi: 44.3, macdSign: "negative", emaPosition: "below" },
  ],
  BANKNIFTY: [
    { tf: "5m",  trend: "bearish", rsi: 42.1, macdSign: "negative", emaPosition: "below" },
    { tf: "15m", trend: "bearish", rsi: 39.8, macdSign: "negative", emaPosition: "below" },
    { tf: "1h",  trend: "bearish", rsi: 36.5, macdSign: "negative", emaPosition: "below" },
    { tf: "1D",  trend: "bearish", rsi: 33.2, macdSign: "negative", emaPosition: "below" },
  ],
  RELIANCE: [
    { tf: "5m",  trend: "bullish", rsi: 65.2, macdSign: "positive", emaPosition: "above" },
    { tf: "15m", trend: "bullish", rsi: 68.4, macdSign: "positive", emaPosition: "above" },
    { tf: "1h",  trend: "bullish", rsi: 61.7, macdSign: "positive", emaPosition: "above" },
    { tf: "1D",  trend: "bullish", rsi: 57.9, macdSign: "positive", emaPosition: "above" },
  ],
  HDFCBANK: [
    { tf: "5m",  trend: "neutral", rsi: 50.1, macdSign: "flat",     emaPosition: "at"    },
    { tf: "15m", trend: "bullish", rsi: 55.6, macdSign: "positive", emaPosition: "above" },
    { tf: "1h",  trend: "neutral", rsi: 48.9, macdSign: "negative", emaPosition: "at"    },
    { tf: "1D",  trend: "bearish", rsi: 43.1, macdSign: "negative", emaPosition: "below" },
  ],
  INFY: [
    { tf: "5m",  trend: "bullish", rsi: 60.3, macdSign: "positive", emaPosition: "above" },
    { tf: "15m", trend: "bullish", rsi: 63.8, macdSign: "positive", emaPosition: "above" },
    { tf: "1h",  trend: "bullish", rsi: 57.2, macdSign: "positive", emaPosition: "above" },
    { tf: "1D",  trend: "neutral", rsi: 52.4, macdSign: "flat",     emaPosition: "at"    },
  ],
};

const SYMBOLS = Object.keys(SAMPLE);

// ---------------------------------------------------------------------------
// Live data (via /api/v1/history per timeframe → /v1/analytics/mtf analyser)
// ---------------------------------------------------------------------------

const INDEX_SYMBOLS = new Set(["NIFTY", "BANKNIFTY"]);

/** OpenAlgo history needs the index exchange for index underlyings. */
function exchangeFor(symbol: string): string {
  return INDEX_SYMBOLS.has(symbol) ? "NSE_INDEX" : "NSE";
}

/** Per-timeframe lookback (calendar days) chosen so each timeframe clears the
 *  analyser's 30-bar minimum even across weekends and holidays. */
const TF_CONFIG: ReadonlyArray<{ tf: string; days: number }> = [
  { tf: "5m", days: 7 },
  { tf: "15m", days: 21 },
  { tf: "1h", days: 90 },
  { tf: "1D", days: 500 },
];

function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 24 * 3600 * 1000).toISOString().slice(0, 10);
}

/** Fetch live bars for every configured timeframe and run the analyser. */
async function fetchMtfAnalysis(symbol: string) {
  const exchange = exchangeFor(symbol);
  const end = new Date().toISOString().slice(0, 10);
  const entries = await Promise.all(
    TF_CONFIG.map(async ({ tf, days }) => {
      const bars = await getHistory(symbol, exchange, tf, isoDaysAgo(days), end);
      return [tf, (bars ?? []) as MtfBar[]] as const;
    }),
  );
  const data = Object.fromEntries(entries) as Record<string, MtfBar[]>;
  return getMultiTimeframe(symbol, data);
}

/** Map an analyser signal to the widget's display row. */
function toDisplaySignal(sig: MtfSignal): TimeframeSignal {
  const macdSign: TimeframeSignal["macdSign"] =
    sig.macd_histogram > 1e-9 ? "positive" : sig.macd_histogram < -1e-9 ? "negative" : "flat";
  const emaPosition: TimeframeSignal["emaPosition"] =
    sig.ema_position === "above" ? "above" : sig.ema_position === "below" ? "below" : "at";
  const trend: Direction =
    sig.trend === "bullish" || sig.trend === "bearish" ? sig.trend : "neutral";
  return {
    tf: sig.timeframe,
    trend,
    rsi: Number.isFinite(sig.rsi) ? sig.rsi : 0,
    macdSign,
    emaPosition,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function confluenceScore(signals: TimeframeSignal[]): { bullish: number; bearish: number; total: number } {
  const bullish = signals.filter((s) => s.trend === "bullish").length;
  const bearish = signals.filter((s) => s.trend === "bearish").length;
  return { bullish, bearish, total: signals.length };
}

function rowBgClass(signal: TimeframeSignal): string {
  switch (signal.trend) {
    case "bullish": return "bg-profit/5 border-profit/20";
    case "bearish": return "bg-loss/5 border-loss/20";
    default:        return "bg-surface-hover/30 border-border-default";
  }
}

function rsiColour(rsi: number): string {
  if (rsi >= 70) return "text-loss";
  if (rsi >= 55) return "text-profit";
  if (rsi <= 30) return "text-loss";
  if (rsi <= 45) return "text-warning";
  return "text-text-secondary";
}

function macdColour(sign: TimeframeSignal["macdSign"]): string {
  if (sign === "positive") return "text-profit";
  if (sign === "negative") return "text-loss";
  return "text-text-muted";
}

function macdLabel(sign: TimeframeSignal["macdSign"]): string {
  if (sign === "positive") return "+";
  if (sign === "negative") return "−";
  return "~";
}

function emaColour(pos: TimeframeSignal["emaPosition"]): string {
  if (pos === "above") return "text-profit";
  if (pos === "below") return "text-loss";
  return "text-text-muted";
}

function emaLabel(pos: TimeframeSignal["emaPosition"]): string {
  if (pos === "above") return "Above";
  if (pos === "below") return "Below";
  return "At";
}

function TrendArrow({ trend }: { trend: Direction }) {
  if (trend === "bullish") return <ArrowUp size={12} className="text-profit" aria-label="Bullish" />;
  if (trend === "bearish") return <ArrowDown size={12} className="text-loss" aria-label="Bearish" />;
  return <Minus size={12} className="text-text-muted" aria-label="Neutral" />;
}

// ---------------------------------------------------------------------------
// Confluence badge
// ---------------------------------------------------------------------------

interface ConfluenceBadgeProps {
  bullish: number;
  bearish: number;
  total: number;
}

function ConfluenceBadge({ bullish, bearish, total }: ConfluenceBadgeProps) {
  const dominant = bullish >= bearish ? bullish : bearish;
  const pct = Math.round((dominant / total) * 100);
  const isBull = bullish >= bearish;
  const colourClass = isBull ? "text-profit bg-profit/10 border-profit/30" : "text-loss bg-loss/10 border-loss/30";
  const label = isBull ? "Bullish" : "Bearish";

  return (
    <div className="flex items-center gap-2">
      <div
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-semibold ${colourClass}`}
        aria-label={`Confluence: ${dominant} of ${total} timeframes ${label}`}
      >
        {isBull ? <ArrowUp size={11} aria-hidden="true" /> : <ArrowDown size={11} aria-hidden="true" />}
        {dominant}/{total} {label}
      </div>
      <div className="flex-1 h-2 bg-surface-hover rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${isBull ? "bg-profit" : "bg-loss"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xxs text-text-muted tabular-nums">{pct}%</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function MultiTimeframeWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();
  const [symbol, setSymbol] = useState("NIFTY");
  const [showMenu, setShowMenu] = useState(false);

  // Live multi-timeframe analysis — only fetched once a broker is connected.
  const { data: liveAnalysis } = useQuery({
    queryKey: ["mtf", symbol],
    queryFn: () => fetchMtfAnalysis(symbol),
    enabled: isConnected,
    staleTime: 60_000,
    refetchInterval: isConnected ? 60_000 : false,
    retry: false,
  });

  const liveSignals = useMemo(
    () => (liveAnalysis?.signals ?? []).map(toDisplaySignal),
    [liveAnalysis],
  );
  // Require at least two timeframes for a meaningful confluence read.
  const isLive = isConnected && liveSignals.length >= 2;

  const signals = useMemo(
    () => (isLive ? liveSignals : SAMPLE[symbol] ?? SAMPLE["NIFTY"]),
    [isLive, liveSignals, symbol],
  );
  const conf = useMemo(() => confluenceScore(signals), [signals]);

  const handleSymbolSelect = (s: string) => {
    setSymbol(s);
    setShowMenu(false);
    track("trade", "multitimeframe_symbol_change");
  };

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Layers size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Multi-Timeframe</span>
        {/* Data-source badge — flips to "Live" only when a broker is connected
            AND the analyser returned at least two timeframes of real signals.
            Otherwise it stays on the honest amber "Sample data" affordance so a
            connected user is never misled into trusting fabricated signals. */}
        {isLive ? (
          <span
            className="ml-1 px-1.5 py-0.5 text-xxs bg-profit/10 text-profit border border-profit/30 rounded"
            role="status"
            aria-label="Showing live multi-timeframe signals from the connected broker"
            title="Live multi-timeframe signals computed from the connected broker's intraday bars."
          >
            Live
          </span>
        ) : (
          <span
            className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
            role="status"
            aria-label="Showing sample data; no live multi-timeframe source is wired yet"
            title="No live data wired yet — showing sample multi-timeframe signals so the widget is usable in explore mode."
          >
            Sample data
          </span>
        )}
        <div className="flex-1" />

        {/* Symbol selector */}
        <div className="relative">
          <button
            onClick={() => setShowMenu((v) => !v)}
            aria-label={`Selected symbol: ${symbol}`}
            aria-expanded={showMenu}
            className="flex items-center gap-1 px-2 py-0.5 text-xs text-text-primary bg-surface-hover rounded border border-border-default hover:border-accent transition-colors"
          >
            {symbol}
            <ChevronDown size={10} aria-hidden="true" />
          </button>
          {showMenu && (
            <div
              className="absolute right-0 top-full mt-1 z-30 bg-surface-card border border-border-default rounded shadow-lg min-w-27.5"
              role="listbox"
              aria-label="Symbol selection"
            >
              {SYMBOLS.map((s) => (
                <button
                  key={s}
                  role="option"
                  aria-selected={s === symbol}
                  onClick={() => handleSymbolSelect(s)}
                  className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${s === symbol ? "text-accent" : "text-text-primary"}`}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-2">

        {/* Confluence score */}
        <div className="bg-surface-card border border-border-default rounded p-2 space-y-1">
          <div className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">Confluence</div>
          <ConfluenceBadge bullish={conf.bullish} bearish={conf.bearish} total={conf.total} />
        </div>

        {/* Column headers */}
        <div className="grid grid-cols-[48px_1fr_52px_44px_52px] gap-1 px-1">
          <span className="text-xxs text-text-muted font-medium uppercase">TF</span>
          <span className="text-xxs text-text-muted font-medium uppercase">Trend</span>
          <span className="text-xxs text-text-muted font-medium uppercase text-right">RSI</span>
          <span className="text-xxs text-text-muted font-medium uppercase text-center">MACD</span>
          <span className="text-xxs text-text-muted font-medium uppercase text-right">EMA</span>
        </div>

        {/* Timeframe rows */}
        <div className="space-y-1">
          {signals.map((sig) => (
            <div
              key={sig.tf}
              className={`grid grid-cols-[48px_1fr_52px_44px_52px] gap-1 items-center px-2 py-2 rounded border ${rowBgClass(sig)}`}
              aria-label={`${sig.tf} timeframe: ${sig.trend}`}
            >
              <span className="text-xs font-mono font-semibold text-text-primary">{sig.tf}</span>
              <span className="flex items-center gap-1">
                <TrendArrow trend={sig.trend} />
                <span className={`text-xs font-medium capitalize ${sig.trend === "bullish" ? "text-profit" : sig.trend === "bearish" ? "text-loss" : "text-text-muted"}`}>
                  {sig.trend.charAt(0).toUpperCase() + sig.trend.slice(1)}
                </span>
              </span>
              <span className={`text-xs font-mono tabular-nums text-right ${rsiColour(sig.rsi)}`}>
                {sig.rsi.toFixed(1)}
              </span>
              <span className={`text-sm font-mono font-bold text-center ${macdColour(sig.macdSign)}`}
                aria-label={`MACD ${sig.macdSign}`}
              >
                {macdLabel(sig.macdSign)}
              </span>
              <span className={`text-xs font-medium text-right ${emaColour(sig.emaPosition)}`}>
                {emaLabel(sig.emaPosition)}
              </span>
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="bg-surface-card border border-border-default rounded p-2">
          <div className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">Legend</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xxs text-text-muted">
            <span>RSI &gt;70 — Overbought</span>
            <span>RSI &lt;30 — Oversold</span>
            <span>MACD + — Histogram positive</span>
            <span>EMA — Price vs 20 EMA</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default memo(MultiTimeframeWidget);

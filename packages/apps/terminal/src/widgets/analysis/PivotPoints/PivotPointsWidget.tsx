/**
 * PivotPointsWidget — Pivot point calculator for FlintTrade terminal.
 *
 * Calculates Standard, Fibonacci, Woodie's, Camarilla, and DeMark pivots
 * from previous day OHLC data. Auto-populates from history API when a symbol
 * is selected. Shows current price position relative to levels.
 */

import { useState, useEffect, useMemo, memo } from "react";
import { GitFork, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useModeStore } from "@/stores/modeStore";
import { getHistory, getQuotes } from "@/services/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  calcPivots,
  getPriceZone,
  PIVOT_METHODS,
  METHOD_LABELS,
} from "./pivotCalc";
import type { PivotMethod, PivotLevels } from "./pivotCalc";
import {
  SAMPLE_PREV_DAY,
  SAMPLE_CURRENT_PRICE,
} from "./sampleData";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "NIFTYIT", "MIDCPNIFTY"];
const EXCHANGES: Record<string, string> = {
  NIFTY: "NSE_INDEX",
  BANKNIFTY: "NSE_INDEX",
  FINNIFTY: "NSE_INDEX",
  NIFTYIT: "NSE_INDEX",
  MIDCPNIFTY: "NSE_INDEX",
};

const LEVEL_KEYS = ["r4", "r3", "r2", "r1", "p", "s1", "s2", "s3", "s4"] as const;
type LevelKey = (typeof LEVEL_KEYS)[number];

const LEVEL_LABELS: Record<LevelKey, string> = {
  r4: "R4", r3: "R3", r2: "R2", r1: "R1",
  p: "P",
  s1: "S1", s2: "S2", s3: "S3", s4: "S4",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(v: number): string {
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(v);
}

function levelColour(key: LevelKey): string {
  if (key === "p") return "text-accent";
  if (key.startsWith("r")) return "text-loss";
  return "text-profit";
}

// ---------------------------------------------------------------------------
// Visual price-position bar
// ---------------------------------------------------------------------------

interface PriceBarProps {
  price: number;
  levels: PivotLevels;
}

function PriceBar({ price, levels }: PriceBarProps) {
  const min = levels.s4;
  const max = levels.r4;
  const span = max - min || 1;
  const pct = Math.max(0, Math.min(100, ((price - min) / span) * 100));

  return (
    <div className="relative h-3 bg-surface-hover rounded-full overflow-visible" aria-label="Price position between S4 and R4">
      {/* Resistance zone — top half */}
      <div className="absolute inset-y-0 left-1/2 right-0 bg-loss/15 rounded-r-full" />
      {/* Support zone — bottom half */}
      <div className="absolute inset-y-0 left-0 right-1/2 bg-profit/15 rounded-l-full" />
      {/* Pivot line */}
      <div className="absolute inset-y-0 left-1/2 w-px bg-accent/60" aria-hidden="true" />
      {/* Price cursor */}
      <div
        className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full bg-warning border-2 border-surface-base shadow z-10 transition-all duration-300"
        style={{ left: `${pct}%` }}
        title={`Price: ${fmt(price)}`}
        aria-hidden="true"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function PivotPointsWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();
  const mode = useModeStore((state) => state.mode);

  const [symbol, setSymbol] = useState("NIFTY");
  const [high, setHigh] = useState(String(SAMPLE_PREV_DAY.high));
  const [low, setLow] = useState(String(SAMPLE_PREV_DAY.low));
  const [close, setClose] = useState(String(SAMPLE_PREV_DAY.close));
  const [open, setOpen] = useState(String(SAMPLE_PREV_DAY.open ?? SAMPLE_PREV_DAY.close));
  const [currentPrice, setCurrentPrice] = useState(SAMPLE_CURRENT_PRICE);
  const [activeMethod, setActiveMethod] = useState<PivotMethod>("standard");
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [historyIsLive, setHistoryIsLive] = useState(false);
  const [quoteIsLive, setQuoteIsLive] = useState(false);

  useEffect(() => {
    track("trade", "widget_view_pivot_points");
  }, [track]);

  // Auto-load previous day data when connected and symbol changes
  useEffect(() => {
    setHigh(String(SAMPLE_PREV_DAY.high));
    setLow(String(SAMPLE_PREV_DAY.low));
    setClose(String(SAMPLE_PREV_DAY.close));
    setOpen(String(SAMPLE_PREV_DAY.open ?? SAMPLE_PREV_DAY.close));
    setCurrentPrice(SAMPLE_CURRENT_PRICE);
    setHistoryIsLive(false);
    setQuoteIsLive(false);
    setLoadError(null);

    const shouldLoadApiData = mode === "practice" || (mode === "live" && isConnected);
    if (!shouldLoadApiData) {
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    const exchange = EXCHANGES[symbol] ?? "NSE_INDEX";
    setIsLoading(true);

    const today = new Date();
    const endDate = today.toISOString().slice(0, 10);
    const startDate = new Date(today.getTime() - 5 * 24 * 60 * 60 * 1000)
      .toISOString()
      .slice(0, 10);

    getHistory(symbol, exchange, "D", startDate, endDate)
      .then((bars) => {
        if (cancelled || !Array.isArray(bars) || bars.length < 2) return;
        const prev = bars[bars.length - 2];
        const nextOhlc = [prev.high, prev.low, prev.close, prev.open].map(Number);
        if (!nextOhlc.every((value) => Number.isFinite(value) && value > 0)) return;
        setHigh(String(nextOhlc[0]));
        setLow(String(nextOhlc[1]));
        setClose(String(nextOhlc[2]));
        setOpen(String(nextOhlc[3]));
        setHistoryIsLive(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : "Failed to load history");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    // Also pull current price
    getQuotes(symbol, exchange)
      .then((q) => {
        if (cancelled) return;
        const nextPrice = Number(q.ltp);
        if (!Number.isFinite(nextPrice) || nextPrice <= 0) return;
        setCurrentPrice(nextPrice);
        setQuoteIsLive(true);
      })
      .catch(() => { /* price stays as last known */ });

    return () => {
      cancelled = true;
    };
  }, [symbol, isConnected, mode]);

  const hasApiInputs = historyIsLive && quoteIsLive;
  const isLive = mode === "live" && isConnected && hasApiInputs;
  const isPractice = mode === "practice" && hasApiInputs;

  const h = parseFloat(high) || 0;
  const l = parseFloat(low) || 0;
  const c = parseFloat(close) || 0;
  const o = parseFloat(open) || 0;

  const allLevels = useMemo<Record<PivotMethod, PivotLevels | null>>(() => {
    if (!h || !l || !c) {
      return Object.fromEntries(PIVOT_METHODS.map((m) => [m, null])) as Record<PivotMethod, null>;
    }
    return Object.fromEntries(
      PIVOT_METHODS.map((m) => [m, calcPivots(h, l, c, o, m)])
    ) as Record<PivotMethod, PivotLevels>;
  }, [h, l, c, o]);

  const levels = allLevels[activeMethod];
  const zone = levels ? getPriceZone(currentPrice, levels) : null;

  const inputClass =
    "w-full px-2 py-1 text-xs bg-surface-hover border border-border-default rounded text-text-primary font-mono focus:outline-none focus:border-accent/50";

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div
        className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default"
        role="banner"
      >
        <GitFork size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Pivot Points</span>
        <div className="flex-1" />
        {isLive ? (
          <span
            className="text-xxs text-profit border border-profit/30 bg-profit/10 rounded px-1.5 py-0.5"
            role="status"
            aria-label="Live pivot inputs from successful history and quote responses"
          >
            Live
          </span>
        ) : isPractice ? (
          <span
            className="text-xxs text-warning border border-warning/30 bg-warning/10 rounded px-1.5 py-0.5"
            role="status"
            aria-label="Practice pivot inputs from successful sandbox history and quote responses"
          >
            Practice
          </span>
        ) : (
          <span className="text-xxs text-text-muted border border-border-subtle rounded px-1.5 py-0.5">
            sample data
          </span>
        )}
        {isLoading && <Loader2 size={12} className="animate-spin text-text-muted" aria-label="Loading" />}
      </div>

      {/* Symbol selector */}
      <div className="flex-none flex items-center gap-2 px-3 py-1.5 bg-surface-elevated border-b border-border-subtle">
        <span className="text-xxs text-text-muted uppercase tracking-wide shrink-0">
          Symbol
        </span>
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger className="h-6 px-2 text-xs w-36" aria-label="Select symbol">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SYMBOLS.map((s) => <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>)}
          </SelectContent>
        </Select>
        {loadError && (
          <span className="text-xxs text-loss ml-auto truncate max-w-40" title={loadError}>
            {loadError}
          </span>
        )}
      </div>

      {/* OHLC inputs */}
      <div className="flex-none grid grid-cols-4 gap-1.5 px-3 py-2 bg-surface-base border-b border-border-subtle">
        {(
          [
            { id: "pp-high", label: "High", value: high, set: setHigh },
            { id: "pp-low", label: "Low", value: low, set: setLow },
            { id: "pp-close", label: "Close", value: close, set: setClose },
            { id: "pp-open", label: "Open", value: open, set: setOpen },
          ] as const
        ).map(({ id, label, value, set }) => (
          <div key={id} className="flex flex-col gap-0.5">
            <label htmlFor={id} className="text-xxs text-text-muted uppercase tracking-wide">
              {label}
            </label>
            <input
              id={id}
              type="number"
              value={value}
              onChange={(e) => {
                set(e.target.value);
                setHistoryIsLive(false);
              }}
              className={inputClass}
              aria-label={`Previous day ${label}`}
            />
          </div>
        ))}
      </div>

      {/* Method tabs */}
      <div
        className="flex-none flex items-center gap-px px-3 py-1.5 bg-surface-card border-b border-border-default overflow-x-auto"
        role="tablist"
        aria-label="Pivot calculation method"
      >
        {PIVOT_METHODS.map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={m === activeMethod}
            onClick={() => setActiveMethod(m)}
            className={cn(
              "px-2.5 py-1 text-xxs font-medium rounded transition-colors whitespace-nowrap",
              m === activeMethod
                ? "bg-accent/15 text-accent border border-accent/30"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
            )}
          >
            {METHOD_LABELS[m]}
          </button>
        ))}
      </div>

      {/* Current price bar */}
      {levels && (
        <div className="flex-none px-3 py-2 border-b border-border-subtle bg-surface-elevated">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xxs text-text-muted uppercase tracking-wide">
              Current price
            </span>
            <span className="text-xs font-mono tabular-nums font-semibold text-warning">
              {fmt(currentPrice)}
            </span>
            <span className="text-xxs text-text-muted">{zone?.replace(/_/g, " ")}</span>
          </div>
          <PriceBar price={currentPrice} levels={levels} />
          <div className="flex justify-between mt-1">
            <span className="text-xxs text-text-muted font-mono">S4 {fmt(levels.s4)}</span>
            <span className="text-xxs text-accent font-mono">P {fmt(levels.p)}</span>
            <span className="text-xxs text-text-muted font-mono">R4 {fmt(levels.r4)}</span>
          </div>
        </div>
      )}

      {/* Levels table */}
      <div className="flex-1 overflow-auto">
        {levels ? (
          <table className="w-full text-xs" aria-label={`${METHOD_LABELS[activeMethod]} pivot levels`}>
            <thead>
              <tr className="sticky top-0 bg-surface-card border-b border-border-default">
                <th className="text-left px-3 py-1.5 text-xxs font-medium text-text-muted uppercase tracking-wide">Level</th>
                <th className="text-right px-3 py-1.5 text-xxs font-medium text-text-muted uppercase tracking-wide">Price</th>
                <th className="text-right px-3 py-1.5 text-xxs font-medium text-text-muted uppercase tracking-wide">Dist</th>
              </tr>
            </thead>
            <tbody>
              {LEVEL_KEYS.map((key) => {
                const val = levels[key];
                const dist = val - currentPrice;
                const isActive = zone !== null && (() => {
                  if (key === "p" && (zone === "p_r1" || zone === "s1_p")) return true;
                  if (key === "r1" && zone === "p_r1") return true;
                  if (key === "s1" && zone === "s1_p") return true;
                  return false;
                })();
                return (
                  <tr
                    key={key}
                    className={cn(
                      "border-b border-border-subtle transition-colors",
                      isActive ? "bg-accent/5" : "hover:bg-surface-hover",
                      key === "p" && "bg-accent/5",
                    )}
                  >
                    <td className={cn("px-3 py-1.5 font-semibold tabular-nums", levelColour(key))}>
                      {LEVEL_LABELS[key]}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-text-primary">
                      {fmt(val)}
                    </td>
                    <td className={cn(
                      "px-3 py-1.5 text-right font-mono tabular-nums text-xxs",
                      dist > 0 ? "text-loss" : dist < 0 ? "text-profit" : "text-text-muted",
                    )}>
                      {dist > 0 ? "+" : ""}{fmt(dist)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="flex items-center justify-center h-full text-text-muted text-sm">
            Enter OHLC values to calculate pivots
          </div>
        )}
      </div>

      {/* Footer: all methods summary */}
      {h > 0 && l > 0 && c > 0 && (
        <div className="flex-none px-3 py-1.5 bg-surface-card border-t border-border-default">
          <div className="flex items-center gap-3 overflow-x-auto">
            {PIVOT_METHODS.map((m) => {
              const lv = allLevels[m];
              return lv ? (
                <div key={m} className="shrink-0 text-center">
                  <div className="text-xxs text-text-muted mb-0.5">{METHOD_LABELS[m]}</div>
                  <div className="text-xs font-mono tabular-nums text-accent">{fmt(lv.p)}</div>
                </div>
              ) : null;
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(PivotPointsWidget);

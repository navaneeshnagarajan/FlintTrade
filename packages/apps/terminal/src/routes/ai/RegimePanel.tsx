/**
 * Regime Detector Display Panel
 *
 * Fetches the current market regime from the FlintTrade backend
 * (GET /ft-api/v1/ai/regime?symbol=NIFTY) and renders:
 *   - Big regime state badge with colour coding
 *   - Is Tradeable indicator (green tick / red cross)
 *   - ADX value + interpretation, BB Width, ATR current + slope
 *   - +DI / -DI comparison bar
 *   - Symbol selector to check different instruments
 *
 * Regime states from regime_detector.py:
 *   TRENDING_UP        — green
 *   TRENDING_DOWN      — red
 *   RANGING            — blue
 *   VOLATILE_DIRECTIONAL    — amber
 *   VOLATILE_DIRECTIONLESS  — red pulsing
 *   LOW_VOLATILITY     — grey
 */

import { useState, useCallback } from "react";
import { motion } from "framer-motion";
import { useQuery } from "@tanstack/react-query";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Zap,
  ZapOff,
  Wind,
  CheckCircle2,
  XCircle,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getRegimeDetector,
  type RegimeState,
} from "@/services/ftApi";
import { motionConfig } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Regime metadata
// ---------------------------------------------------------------------------

interface RegimeMeta {
  label: string;
  description: string;
  badgeClass: string;
  iconClass: string;
  Icon: typeof TrendingUp;
  pulse?: boolean;
}

const REGIME_META: Record<RegimeState, RegimeMeta> = {
  TRENDING_UP: {
    label: "Trending Up",
    description: "ADX-confirmed uptrend. Directional strategies appropriate.",
    badgeClass: "bg-profit/20 text-profit border-profit/40",
    iconClass: "text-profit",
    Icon: TrendingUp,
  },
  TRENDING_DOWN: {
    label: "Trending Down",
    description: "ADX-confirmed downtrend. Bearish directional strategies appropriate.",
    badgeClass: "bg-loss/20 text-loss border-loss/40",
    iconClass: "text-loss",
    Icon: TrendingDown,
  },
  RANGING: {
    label: "Ranging",
    description: "Low ADX, tight BB. No clear direction. Mean-reversion strategies preferred.",
    badgeClass: "bg-blue-500/20 text-blue-400 border-blue-500/40",
    iconClass: "text-blue-400",
    Icon: Activity,
  },
  VOLATILE_DIRECTIONAL: {
    label: "Volatile Directional",
    description: "High ADX + expanding ATR. Trending with increasing volatility — breakout/impulse in progress.",
    badgeClass: "bg-warning/20 text-warning border-warning/40",
    iconClass: "text-warning",
    Icon: Zap,
  },
  VOLATILE_DIRECTIONLESS: {
    label: "Volatile Directionless",
    description: "Low ADX + wide BB. Pre-expiry manipulation zone. Avoid directional bets.",
    badgeClass: "bg-loss/20 text-loss border-loss/40",
    iconClass: "text-loss",
    Icon: ZapOff,
    pulse: true,
  },
  LOW_VOLATILITY: {
    label: "Low Volatility",
    description: "Tight BB + declining ATR. Compression phase — anticipate breakout.",
    badgeClass: "bg-surface-base text-text-muted border-border-default",
    iconClass: "text-text-muted",
    Icon: Wind,
  },
};

// ---------------------------------------------------------------------------
// Tradeable indicator
// ---------------------------------------------------------------------------

const NON_TRADEABLE: RegimeState[] = ["VOLATILE_DIRECTIONLESS", "LOW_VOLATILITY"];

function isTradeableState(state: RegimeState): boolean {
  return !NON_TRADEABLE.includes(state);
}

function TradeableIndicator({ state }: { state: RegimeState }) {
  const tradeable = isTradeableState(state);
  return (
    <div
      className="flex items-center gap-2"
      role="status"
      aria-label={tradeable ? "Tradeable" : "Not tradeable"}
    >
      {tradeable ? (
        <>
          <CheckCircle2 className="w-5 h-5 text-profit" />
          <span className="text-sm font-semibold text-profit">Tradeable</span>
        </>
      ) : (
        <>
          <XCircle className="w-5 h-5 text-loss" />
          <span className="text-sm font-semibold text-loss">Avoid Directional</span>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ADX interpretation
// ---------------------------------------------------------------------------

function adxInterpretation(adx: number): string {
  if (adx >= 50) return "Extremely strong trend";
  if (adx >= 40) return "Very strong trend";
  if (adx >= 25) return "Strong trend";
  if (adx >= 20) return "Weakening trend";
  return "No trend / ranging";
}

// ---------------------------------------------------------------------------
// ATR slope interpretation
// ---------------------------------------------------------------------------

function atrSlopeText(slope: number): string {
  if (slope > 0.5) return "Strongly expanding";
  if (slope > 0) return "Expanding";
  if (slope < -0.5) return "Strongly contracting";
  if (slope < 0) return "Contracting";
  return "Flat";
}

function atrSlopeClass(slope: number): string {
  if (slope > 0) return "text-warning";
  if (slope < 0) return "text-profit";
  return "text-text-muted";
}

// ---------------------------------------------------------------------------
// Indicator stat row
// ---------------------------------------------------------------------------

function StatRow({
  label,
  value,
  valueClass = "text-text-primary",
  subtitle,
}: {
  label: string;
  value: string;
  valueClass?: string;
  subtitle?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 py-2 border-b border-border-default last:border-0">
      <div>
        <p className="text-xs font-medium text-text-secondary">{label}</p>
        {subtitle && <p className="text-xxs text-text-muted mt-0.5">{subtitle}</p>}
      </div>
      <p className={`text-sm font-mono font-bold shrink-0 ${valueClass}`}>{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// +DI / -DI comparison bar
// ---------------------------------------------------------------------------

function DiBar({ plusDi, minusDi }: { plusDi: number; minusDi: number }) {
  const total = plusDi + minusDi;
  const plusPct = total > 0 ? (plusDi / total) * 100 : 50;
  const minusPct = 100 - plusPct;

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xxs text-text-muted">
        <span className="text-profit font-mono">+DI {plusDi.toFixed(1)}</span>
        <span className="text-loss font-mono">-DI {minusDi.toFixed(1)}</span>
      </div>
      <div
        className="flex h-2.5 rounded-full overflow-hidden"
        role="meter"
        aria-label={`+DI ${plusDi.toFixed(1)} vs -DI ${minusDi.toFixed(1)}`}
        aria-valuenow={plusPct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <motion.div
          className="bg-profit h-full"
          initial={{ width: "50%" }}
          animate={{ width: `${plusPct}%` }}
          transition={{ type: "spring", stiffness: 100, damping: 20 }}
        />
        <motion.div
          className="bg-loss h-full"
          initial={{ width: "50%" }}
          animate={{ width: `${minusPct}%` }}
          transition={{ type: "spring", stiffness: 100, damping: 20 }}
        />
      </div>
      <div className="flex justify-between text-xxs text-text-muted">
        <span>Bullish pressure</span>
        <span>Bearish pressure</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Default symbols for quick-select
// ---------------------------------------------------------------------------

const QUICK_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function RegimePanel() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [inputValue, setInputValue] = useState("NIFTY");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["regime-detector", symbol],
    queryFn: () => getRegimeDetector(symbol),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const handleSearch = useCallback(() => {
    const val = inputValue.trim().toUpperCase();
    if (val) setSymbol(val);
  }, [inputValue]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") handleSearch();
    },
    [handleSearch],
  );

  const meta = data ? REGIME_META[data.state] : null;
  const RegimeIcon = meta?.Icon ?? Activity;

  return (
    <div className="space-y-4" data-tour-target="ai-regime-detector">
      {/* Header */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-heading font-semibold text-base text-text-primary">
            Regime Detector
          </h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            disabled={isLoading}
            aria-label="Refresh regime data"
            className="text-text-muted hover:text-text-primary gap-1.5 h-7 text-xs"
          >
            <RefreshCw className={`w-3 h-3 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
        <p className="text-xs text-text-secondary leading-relaxed">
          ADX, Bollinger Band width, and ATR determine one of six market regimes
          to guide strategy selection.
        </p>
      </Card>

      {/* Symbol selector */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3">
        <h4 className="text-sm font-semibold text-text-primary">Select Instrument</h4>
        <div className="flex gap-2">
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value.toUpperCase())}
            onKeyDown={handleKeyDown}
            placeholder="e.g. NIFTY"
            aria-label="Instrument symbol for regime detection"
            className="bg-surface-base border-border-default text-text-primary font-mono text-sm uppercase"
          />
          <Button
            onClick={handleSearch}
            disabled={!inputValue.trim() || isLoading}
            size="sm"
            className="shrink-0"
            aria-label="Search regime for symbol"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Search className="w-4 h-4" />
            )}
          </Button>
        </div>
        {/* Quick symbols */}
        <div className="flex flex-wrap gap-1.5">
          {QUICK_SYMBOLS.map((sym) => (
            <button
              key={sym}
              onClick={() => {
                setInputValue(sym);
                setSymbol(sym);
              }}
              aria-pressed={symbol === sym}
              className={`text-xxs font-mono px-2 py-1 rounded border transition-colors ${
                symbol === sym
                  ? "bg-accent text-white border-accent"
                  : "bg-surface-base border-border-default text-text-muted hover:text-text-secondary"
              }`}
            >
              {sym}
            </button>
          ))}
        </div>
      </Card>

      {/* Loading */}
      {isLoading && (
        <div className="flex flex-col items-center gap-3 py-10 text-text-muted">
          <Loader2 className="w-6 h-6 animate-spin" />
          <span className="text-sm">Detecting regime for {symbol}…</span>
        </div>
      )}

      {/* Unavailable state — honest "coming soon" rather than an error.
          Regime detection is not yet enabled in this build (the endpoint is
          not wired / historical data is unavailable), so the request fails
          closed. We degrade to a calm preview placeholder instead of
          surfacing a raw backend error. */}
      {isError && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-5">
          <div className="flex items-start gap-3 text-text-secondary">
            <Activity className="w-4 h-4 shrink-0 mt-0.5 text-text-muted" />
            <div>
              <p className="text-sm font-semibold mb-1 text-text-primary">
                Regime detection coming soon
              </p>
              <p className="text-xs text-text-muted">
                Market regime detection is not yet available in this build.
                Once the AI backend is enabled and historical data is available
                for {symbol}, the live regime will appear here.
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            className="mt-3 text-text-muted hover:text-text-primary text-xs"
          >
            Check again
          </Button>
        </Card>
      )}

      {/* Result */}
      {data && meta && (
        <motion.div
          className="space-y-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={motionConfig.transitions.tab}
        >
          {/* Regime state badge */}
          <Card className="bg-surface-card border border-border-default rounded-lg p-5">
            <div className="flex flex-col items-center gap-3 text-center">
              {/* Icon with optional pulse for VOLATILE_DIRECTIONLESS */}
              <div
                className={`w-14 h-14 rounded-full flex items-center justify-center ${meta.badgeClass} border-2 ${meta.pulse ? "animate-pulse" : ""}`}
              >
                <RegimeIcon className={`w-7 h-7 ${meta.iconClass}`} aria-hidden />
              </div>

              {/* State badge */}
              <Badge
                variant="outline"
                className={`text-sm font-bold px-4 py-1.5 border rounded-full ${meta.badgeClass}`}
              >
                {meta.label}
              </Badge>

              <p className="text-xs text-text-secondary leading-relaxed max-w-xs">
                {meta.description}
              </p>

              {/* Tradeable indicator */}
              <TradeableIndicator state={data.state} />

              {/* Symbol + bars badge */}
              <div className="flex items-center gap-2 text-xxs text-text-muted font-mono">
                <span>{symbol}</span>
                <span>·</span>
                <span>{data.n_bars} bars</span>
              </div>
            </div>
          </Card>

          {/* Regime-appropriate strategy suggestion (closes the loop on
              detection — the backend maps the regime to a strategy style). */}
          {data.suggested_strategy && (
            <Card className="bg-surface-card border border-accent/30 rounded-lg p-4 space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <h4 className="text-sm font-semibold text-text-primary">Suggested Strategy</h4>
                <Badge
                  variant="outline"
                  className="text-xs font-semibold px-2.5 py-0.5 border-accent/40 text-accent bg-accent/10 rounded-full"
                >
                  {data.suggested_strategy.label}
                </Badge>
              </div>
              <p className="text-xs text-text-secondary leading-relaxed">
                {data.suggested_strategy.rationale}
              </p>
            </Card>
          )}

          {/* +DI / -DI bar */}
          {!isNaN(data.plus_di) && !isNaN(data.minus_di) && (
            <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-2">
              <h4 className="text-sm font-semibold text-text-primary">
                Directional Pressure
              </h4>
              <DiBar plusDi={data.plus_di} minusDi={data.minus_di} />
            </Card>
          )}

          {/* Indicator stats */}
          <Card className="bg-surface-card border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Indicators</h4>
            <div>
              <StatRow
                label="ADX"
                value={data.adx.toFixed(1)}
                valueClass={data.adx >= 25 ? "text-profit" : "text-text-muted"}
                subtitle={adxInterpretation(data.adx)}
              />
              <StatRow
                label="BB Width"
                value={`${(data.bb_width * 100).toFixed(2)}%`}
                valueClass={
                  data.bb_width > 0.04
                    ? "text-warning"
                    : data.bb_width < 0.02
                      ? "text-text-muted"
                      : "text-text-primary"
                }
                subtitle={
                  data.bb_width > 0.04
                    ? "Wide bands — elevated volatility"
                    : data.bb_width < 0.02
                      ? "Tight bands — compression"
                      : "Normal band width"
                }
              />
              <StatRow
                label="ATR"
                value={data.atr_current.toFixed(2)}
                valueClass="text-text-primary"
              />
              <StatRow
                label="ATR Slope"
                value={atrSlopeText(data.atr_slope)}
                valueClass={atrSlopeClass(data.atr_slope)}
                subtitle={`Slope: ${data.atr_slope.toFixed(4)}`}
              />
              <StatRow
                label="Last Close"
                value={data.close.toLocaleString("en-IN")}
                valueClass="text-text-primary"
              />
            </div>
          </Card>
        </motion.div>
      )}
    </div>
  );
}

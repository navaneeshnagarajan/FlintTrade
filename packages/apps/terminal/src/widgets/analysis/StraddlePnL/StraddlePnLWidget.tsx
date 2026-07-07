/**
 * StraddlePnLWidget — Straddle P&L Simulator for FlintTrade terminal.
 *
 * Features:
 *   - Base ATM straddle (CE + PE) always shown
 *   - Add/remove adjustment legs (strike, CE/PE, BUY/SELL, premium)
 *   - Plotly area chart: green fill above zero, red fill below zero
 *   - Break-even points annotated with vertical dashed lines
 *   - Summary: Max Loss, Break-Even Low/High, Total Premium
 *   - FeatureTeaser with sample data when no broker is connected
 */

import { useState, useMemo, memo } from "react";
import { RefreshCw, AlertCircle, Loader2, Plus, X } from "lucide-react";
import { useStraddlePnL } from "./useStraddlePnL";
import { SAMPLE_STRADDLE_PNL_DATA } from "./sampleData";
import { PlotlyChart } from "@/components/charts/PlotlyChart";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { StraddleLeg } from "@/types/api";
import type { Data, Layout } from "plotly.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];
const SYMBOL_EXCHANGE: Record<string, string> = {
  NIFTY: "NFO",
  BANKNIFTY: "NFO",
  FINNIFTY: "NFO",
  MIDCPNIFTY: "NFO",
  SENSEX: "BFO",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtPnL(v: number): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : v > 0 ? "+" : "";
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

/**
 * True when the payload carries the backend's `is_sample_data: true` honesty
 * flag (propagated onto object payloads by the ftApi response unwrapper).
 */
function carriesSampleFlag(payload: unknown): boolean {
  return (
    typeof payload === "object" &&
    payload !== null &&
    (payload as { is_sample_data?: unknown }).is_sample_data === true
  );
}

// ---------------------------------------------------------------------------
// Leg row sub-component
// ---------------------------------------------------------------------------

interface LegRowProps {
  leg: StraddleLeg;
  index: number;
  onRemove: (index: number) => void;
  onChange: (index: number, updated: StraddleLeg) => void;
  removable: boolean;
}

function LegRow({ leg, index, onRemove, onChange, removable }: LegRowProps) {
  return (
    <div className="flex items-center gap-1 py-1 border-b border-border-subtle last:border-0">
      <input
        type="number"
        value={leg.strike}
        onChange={(e) => onChange(index, { ...leg, strike: Number(e.target.value) })}
        className="w-20 px-1.5 py-0.5 text-xs bg-surface-hover border border-border-default rounded font-mono text-text-primary focus:outline-none focus:border-accent/50"
        placeholder="Strike"
        step={50}
      />
      <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
        {(["CE", "PE"] as const).map((t) => (
          <button
            key={t}
            onClick={() => onChange(index, { ...leg, type: t })}
            className={`px-1.5 py-0.5 text-xxs font-medium transition-colors ${
              t === leg.type
                ? t === "CE" ? "bg-profit/15 text-profit" : "bg-loss/15 text-loss"
                : "text-text-muted hover:text-text-primary"
            }`}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
        {(["BUY", "SELL"] as const).map((a) => (
          <button
            key={a}
            onClick={() => onChange(index, { ...leg, action: a })}
            className={`px-1.5 py-0.5 text-xxs font-medium transition-colors ${
              a === leg.action
                ? a === "BUY" ? "bg-profit/15 text-profit" : "bg-loss/15 text-loss"
                : "text-text-muted hover:text-text-primary"
            }`}
          >
            {a}
          </button>
        ))}
      </div>
      <input
        type="number"
        value={leg.premium}
        onChange={(e) => onChange(index, { ...leg, premium: Number(e.target.value) })}
        className="w-16 px-1.5 py-0.5 text-xs bg-surface-hover border border-border-default rounded font-mono text-text-primary focus:outline-none focus:border-accent/50"
        placeholder="Prem"
        min={0}
        step={1}
      />
      {removable && (
        <button
          onClick={() => onRemove(index)}
          className="p-0.5 rounded text-text-muted hover:text-loss transition-colors"
          title="Remove leg"
        >
          <X size={11} />
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function StraddlePnLWidget() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiry, setExpiry] = useState("");
  const [adjustments, setAdjustments] = useState<StraddleLeg[]>([]);

  const isConnected = useBrokerConnected();
  const exchange = SYMBOL_EXCHANGE[symbol] ?? "NFO";

  const { data: liveData, isLoading, isError, error, refetch, isFetching } =
    useStraddlePnL(symbol, exchange, expiry, adjustments, isConnected);

  const data = isConnected ? liveData : SAMPLE_STRADDLE_PNL_DATA;
  // Honesty affordance keyed on the payload FLAG, not connection state alone:
  // the backend serves clearly-flagged sample premiums (is_sample_data) when
  // it has no live chain, even while a broker is connected.
  const isSample = !isConnected || carriesSampleFlag(liveData);

  // Build Plotly traces
  const { plotData, plotLayout } = useMemo<{
    plotData: Data[];
    plotLayout: Partial<Layout>;
  }>(() => {
    if (!data?.curve?.length) return { plotData: [], plotLayout: {} };

    const spots = data.curve.map((p) => p.spot_price);
    const pnls = data.curve.map((p) => p.pnl);

    const posY = pnls.map((v) => (v >= 0 ? v : 0));
    const negY = pnls.map((v) => (v < 0 ? v : 0));

    const shapes: Partial<Layout>["shapes"] = [];
    const annotations: Partial<Layout>["annotations"] = [];

    if (data.break_even_low > 0) {
      shapes.push({
        type: "line",
        x0: data.break_even_low,
        x1: data.break_even_low,
        y0: 0,
        y1: 1,
        yref: "paper" as const,
        line: { color: "#6366f1", width: 1, dash: "dash" },
      });
      annotations.push({
        x: data.break_even_low,
        y: 0.95,
        yref: "paper" as const,
        text: `BE ${data.break_even_low.toFixed(0)}`,
        showarrow: false,
        font: { size: 9, color: "#6366f1" },
      });
    }

    if (data.break_even_high > 0 && data.break_even_high !== data.break_even_low) {
      shapes.push({
        type: "line",
        x0: data.break_even_high,
        x1: data.break_even_high,
        y0: 0,
        y1: 1,
        yref: "paper" as const,
        line: { color: "#6366f1", width: 1, dash: "dash" },
      });
      annotations.push({
        x: data.break_even_high,
        y: 0.95,
        yref: "paper" as const,
        text: `BE ${data.break_even_high.toFixed(0)}`,
        showarrow: false,
        font: { size: 9, color: "#6366f1" },
      });
    }

    // ATM line
    if (data.atm_strike > 0) {
      shapes.push({
        type: "line",
        x0: data.atm_strike,
        x1: data.atm_strike,
        y0: 0,
        y1: 1,
        yref: "paper" as const,
        line: { color: "#a0a0b8", width: 1, dash: "dot" },
      });
    }

    const plotData: Data[] = [
      {
        type: "scatter",
        mode: "none",
        name: "P&L (pos)",
        x: spots,
        y: posY,
        fill: "tozeroy",
        fillcolor: "rgba(34,197,94,0.2)",
        hoverinfo: "skip",
      } as Data,
      {
        type: "scatter",
        mode: "none",
        name: "P&L (neg)",
        x: spots,
        y: negY,
        fill: "tozeroy",
        fillcolor: "rgba(239,68,68,0.2)",
        hoverinfo: "skip",
      } as Data,
      {
        type: "scatter",
        mode: "lines",
        name: "P&L",
        x: spots,
        y: pnls,
        line: { color: "#a0a0b8", width: 2 },
        hovertemplate: "Spot: %{x:.0f}<br>P&L: %{y:.0f}<extra></extra>",
      } as Data,
    ];

    const plotLayout: Partial<Layout> = {
      xaxis: { title: { text: "Spot Price" }, tickformat: ",.0f" },
      yaxis: { title: { text: "P&L (₹)" } },
      margin: { t: 20, r: 10, b: 45, l: 60 },
      shapes,
      annotations,
    };

    return { plotData, plotLayout };
  }, [data]);

  const addLeg = () => {
    const newLeg: StraddleLeg = {
      strike: data?.atm_strike ?? 0,
      type: "CE",
      action: "SELL",
      premium: 0,
      lots: 1,
    };
    setAdjustments((prev) => [...prev, newLeg]);
  };

  const removeLeg = (idx: number) => {
    setAdjustments((prev) => prev.filter((_, i) => i !== idx));
  };

  const updateLeg = (idx: number, updated: StraddleLeg) => {
    setAdjustments((prev) => prev.map((l, i) => (i === idx ? updated : l)));
  };

  const totalPremium = data
    ? data.call_premium + data.put_premium
    : null;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        {isSample && (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing demo data, not live straddle premiums"
            title="Demo data — fabricated sample premiums, not a live option chain."
          >
            Demo data
          </span>
        )}
        <Select value={symbol} onValueChange={(v) => { setSymbol(v); setAdjustments([]); }}>
          <SelectTrigger className="h-7 px-2 text-xs w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SYMBOLS.map((s) => (
              <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="px-1.5 py-0.5 text-xs text-text-muted bg-surface-base border border-border-default rounded">
          {exchange}
        </span>
        <input
          value={expiry}
          onChange={(e) => setExpiry(e.target.value)}
          placeholder="Expiry (YYYY-MM-DD)"
          className="w-32 px-2 py-0.5 text-xs bg-surface-hover border border-border-default rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent/50"
        />
        <div className="flex-1" />
        <button
          onClick={() => void refetch()}
          disabled={isFetching}
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Error */}
      {isError && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{(error as Error)?.message ?? "Failed to load P&L simulation"}</span>
        </div>
      )}

      {/* Body: chart + adjustment panel */}
      <div className="flex-1 min-h-0 flex">

        {/* Chart side */}
        <div className="flex-1 min-w-0 flex flex-col">
          {isConnected && isLoading && (
            <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
              <Loader2 size={16} className="animate-spin" />
              Simulating P&L...
            </div>
          )}
          {isConnected && !isLoading && !liveData && !isError && (
            <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
              Enter symbol and expiry to simulate straddle P&L
            </div>
          )}
          {data && (() => {
            const chart = (
              <div className="flex-1 min-h-0">
                <PlotlyChart data={plotData} layout={plotLayout} />
              </div>
            );
            return isConnected ? (
              chart
            ) : (
              <FeatureTeaser
                status="in_dev"
                featureName="Straddle P&L Simulator"
                version={APP_VERSION_TAG}
              >
                {chart}
              </FeatureTeaser>
            );
          })()}
        </div>

        {/* Adjustment panel */}
        <div className="flex-none w-44 border-l border-border-default bg-surface-card flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-2 py-1.5 border-b border-border-default">
            <span className="text-xs font-medium text-text-secondary uppercase tracking-wide">Legs</span>
            <button
              onClick={addLeg}
              className="flex items-center gap-0.5 px-1.5 py-0.5 text-xxs font-medium text-accent bg-accent/10 border border-accent/30 rounded hover:bg-accent/15 transition-colors"
              title="Add adjustment leg"
            >
              <Plus size={9} />
              Add Leg
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-2 py-1">
            {/* Base straddle (display only) */}
            {data && (
              <div className="mb-2 pb-2 border-b border-border-subtle">
                <div className="text-xxs text-text-muted uppercase tracking-wide mb-1">Base Straddle</div>
                <div className="text-xs text-text-secondary font-mono">
                  {data.atm_strike} CE BUY {data.call_premium.toFixed(0)}
                </div>
                <div className="text-xs text-text-secondary font-mono">
                  {data.atm_strike} PE BUY {data.put_premium.toFixed(0)}
                </div>
              </div>
            )}

            {/* Adjustments */}
            {adjustments.length > 0 && (
              <div>
                <div className="text-xxs text-text-muted uppercase tracking-wide mb-1">Adjustments</div>
                {adjustments.map((leg, idx) => (
                  <LegRow
                    key={idx}
                    leg={leg}
                    index={idx}
                    onRemove={removeLeg}
                    onChange={updateLeg}
                    removable
                  />
                ))}
              </div>
            )}

            {adjustments.length === 0 && !data && (
              <div className="text-xxs text-text-muted text-center py-2">
                Load data then add legs
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Summary footer */}
      {data && (
        <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1.5 flex items-center gap-4 text-xs flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="text-text-muted uppercase tracking-wide">Max Loss</span>
            <span className="font-mono tabular-nums text-loss font-semibold">
              {fmtPnL(data.max_loss)}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-text-muted uppercase tracking-wide">BE</span>
            <span className="font-mono tabular-nums text-accent">
              {data.break_even_low.toFixed(0)} / {data.break_even_high.toFixed(0)}
            </span>
          </div>
          {totalPremium != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-text-muted uppercase tracking-wide">Premium</span>
              <span className="font-mono tabular-nums text-warning">
                {totalPremium.toFixed(0)}
              </span>
            </div>
          )}
          {data.atm_strike > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-text-muted uppercase tracking-wide">ATM</span>
              <span className="font-mono tabular-nums text-text-secondary">
                {new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(data.atm_strike)}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default memo(StraddlePnLWidget);

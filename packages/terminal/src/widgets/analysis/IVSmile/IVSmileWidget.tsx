/**
 * IVSmileWidget — IV Smile Curves for FlintTrade terminal.
 *
 * Features:
 *   - Multi-expiry overlay (up to 3 curves per expiry)
 *   - Call IV (solid line) and Put IV (dashed line) per expiry
 *   - ATM vertical reference line
 *   - ATM IV and 25-delta skew in header
 *   - X-axis toggle: Strike / Moneyness
 *   - Auto-refresh: 30s market hours (when broker connected)
 *   - FeatureTeaser with sample data when no broker is connected
 */

import { useState, useMemo } from "react";
import { RefreshCw, AlertCircle, Loader2, TrendingDown, TrendingUp } from "lucide-react";
import { useIVSmile } from "./useIVSmile";
import { SAMPLE_IV_SMILE_DATA } from "./sampleData";
import { PlotlyChart } from "@/components/charts/PlotlyChart";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
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

// Color palette: up to 3 expiries
const EXPIRY_COLORS = ["#6366f1", "#f59e0b", "#22c55e"];

type OptionTypeFilter = "Both" | "CE" | "PE";
type XAxisMode = "Strike" | "Moneyness";

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

export default function IVSmileWidget() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiriesInput, setExpiriesInput] = useState("");
  const [optionType, setOptionType] = useState<OptionTypeFilter>("Both");
  const [xMode, setXMode] = useState<XAxisMode>("Strike");

  const isConnected = useBrokerConnected();
  const exchange = SYMBOL_EXCHANGE[symbol] ?? "NFO";

  const expiryDates = useMemo(
    () =>
      expiriesInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .slice(0, 3),
    [expiriesInput],
  );

  const { data: liveData, isLoading, isError, error, refetch, isFetching } = useIVSmile(
    symbol,
    exchange,
    expiryDates.length > 0 ? expiryDates : undefined,
    isConnected,
  );

  const data = isConnected ? liveData : SAMPLE_IV_SMILE_DATA;

  const { plotData, plotLayout, atmIV, skew25d } = useMemo<{
    plotData: Data[];
    plotLayout: Partial<Layout>;
    atmIV: number | null;
    skew25d: number | null;
  }>(() => {
    if (!data?.curves?.length) {
      return { plotData: [], plotLayout: {}, atmIV: null, skew25d: null };
    }

    const traces: Data[] = [];
    let atmIV: number | null = null;
    let skew25d: number | null = null;

    data.curves.forEach((curve, idx) => {
      const color = EXPIRY_COLORS[idx % EXPIRY_COLORS.length];
      const pts = curve.points.filter(
        (p) => (p.call_iv > 0 || p.put_iv > 0),
      );

      // Pick X axis values
      const xVals = pts.map((p) =>
        xMode === "Moneyness" ? p.moneyness : p.strike,
      );

      if (idx === 0) {
        atmIV = curve.atm_iv;
        skew25d = curve.skew_25delta;
      }

      if (optionType === "CE" || optionType === "Both") {
        traces.push({
          type: "scatter",
          mode: "lines+markers",
          name: `${curve.expiry} CE`,
          x: xVals,
          y: pts.map((p) => (p.call_iv > 0 ? p.call_iv * 100 : null)),
          line: { color, width: 1.5, dash: "solid" },
          marker: { size: 3 },
          hovertemplate: `${curve.expiry} CE<br>${xMode}: %{x}<br>IV: %{y:.1f}%<extra></extra>`,
        } as Data);
      }

      if (optionType === "PE" || optionType === "Both") {
        traces.push({
          type: "scatter",
          mode: "lines+markers",
          name: `${curve.expiry} PE`,
          x: xVals,
          y: pts.map((p) => (p.put_iv > 0 ? p.put_iv * 100 : null)),
          line: { color, width: 1.5, dash: "dash" },
          marker: { size: 3 },
          hovertemplate: `${curve.expiry} PE<br>${xMode}: %{x}<br>IV: %{y:.1f}%<extra></extra>`,
        } as Data);
      }
    });

    const firstCurve = data.curves[0];
    const atmX =
      xMode === "Moneyness" ? 1.0 : (firstCurve?.atm_strike ?? null);

    const plotLayout: Partial<Layout> = {
      xaxis: {
        title: { text: xMode },
        tickformat: xMode === "Moneyness" ? ".3f" : ",.0f",
      },
      yaxis: { title: { text: "IV (%)" }, ticksuffix: "%" },
      margin: { t: 20, r: 10, b: 45, l: 55 },
      shapes:
        atmX != null
          ? [
              {
                type: "line",
                x0: atmX,
                x1: atmX,
                y0: 0,
                y1: 1,
                yref: "paper" as const,
                line: { color: "#6366f1", width: 1, dash: "dash" },
              },
            ]
          : [],
      annotations:
        atmX != null && firstCurve
          ? [
              {
                x: atmX,
                y: 1,
                yref: "paper" as const,
                text: `ATM ${firstCurve.atm_strike}`,
                showarrow: false,
                font: { size: 9, color: "#6366f1" },
                yanchor: "top",
              },
            ]
          : [],
    };

    return { plotData: traces, plotLayout, atmIV, skew25d };
  }, [data, optionType, xMode]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default flex-wrap">
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="px-2 py-1 text-xs bg-surface-hover border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/50"
        >
          {SYMBOLS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <span className="px-1.5 py-0.5 text-xs text-text-muted bg-surface-base border border-border-default rounded">
          {exchange}
        </span>
        <input
          value={expiriesInput}
          onChange={(e) => setExpiriesInput(e.target.value)}
          placeholder="Expiries (comma-sep)"
          className="flex-1 min-w-36 px-2 py-0.5 text-xs bg-surface-hover border border-border-default rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent/50"
        />
        {/* Option type toggle */}
        <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
          {(["CE", "PE", "Both"] as OptionTypeFilter[]).map((t) => (
            <button
              key={t}
              onClick={() => setOptionType(t)}
              className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                t === optionType
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        {/* X-axis toggle */}
        <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
          {(["Strike", "Moneyness"] as XAxisMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setXMode(m)}
              className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                m === xMode
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
        <button
          onClick={() => void refetch()}
          disabled={isFetching}
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Metrics header */}
      {(atmIV != null || skew25d != null) && (
        <div className="flex-none flex items-center gap-4 px-3 py-1 bg-surface-base border-b border-border-subtle text-xs">
          {atmIV != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-text-muted uppercase tracking-wide">ATM IV</span>
              <span className="font-mono tabular-nums font-semibold text-text-primary">
                {(atmIV * 100).toFixed(1)}%
              </span>
            </div>
          )}
          {skew25d != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-text-muted uppercase tracking-wide">25d Skew</span>
              <span className={`font-mono tabular-nums font-semibold flex items-center gap-0.5 ${
                skew25d > 0 ? "text-loss" : skew25d < 0 ? "text-profit" : "text-text-secondary"
              }`}>
                {skew25d > 0 ? <TrendingDown size={10} /> : <TrendingUp size={10} />}
                {skew25d > 0 ? "+" : ""}{(skew25d * 100).toFixed(2)}%
              </span>
              <span className="text-text-muted text-xxs">
                {skew25d > 0 ? "(Put skew)" : "(Call skew)"}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{(error as Error)?.message ?? "Failed to load IV smile data"}</span>
        </div>
      )}

      {/* Loading — only shown when connected and query is running */}
      {isConnected && isLoading && (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
          <Loader2 size={16} className="animate-spin" />
          Loading IV smile...
        </div>
      )}

      {/* Empty state — only when connected but no data yet */}
      {isConnected && !isLoading && !liveData && !isError && (
        <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
          Select symbol to view IV smile curves
        </div>
      )}

      {/* Chart */}
      {data && plotData.length > 0 && (() => {
        const chartContent = (
          <div className="flex-1 min-h-0">
            <PlotlyChart data={plotData} layout={plotLayout} />
          </div>
        );
        return isConnected ? (
          chartContent
        ) : (
          <FeatureTeaser
            status="preview"
            featureName="IV Smile"
            version="v0.3.0"
          >
            {chartContent}
          </FeatureTeaser>
        );
      })()}

      {isConnected && data && plotData.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
          No IV data available for the selected parameters
        </div>
      )}
    </div>
  );
}

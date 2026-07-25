/**
 * GEXWidget — Gamma Exposure Dashboard for FlintTrade terminal.
 *
 * Features:
 *   - Grouped bar chart: Call GEX (green) vs Put GEX (red) per strike
 *   - Net GEX line chart with zero-fill (green above, red below)
 *   - Dealer zone label: Long Gamma / Short Gamma
 *   - Gamma flip strike annotation
 *   - ATM strike vertical reference line
 *   - Summary badges: Net GEX, Gamma Flip Strike, Dealer Zone
 *   - Auto-refresh: 30s market hours (when broker connected)
 *   - FeatureTeaser with sample data when no broker is connected
 */

import { useState, useMemo, memo } from "react";
import { RefreshCw, ChevronDown, AlertCircle, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useGEX } from "./useGEX";
import { SAMPLE_GEX_DATA } from "./sampleData";
import { PlotlyChart } from "@/components/charts/PlotlyChart";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
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

/** Read a CSS custom property from the document root at call time. */
function getThemeColor(varName: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || fallback;
}

function fmtGEX(v: number): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "+";
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

function fmtStrike(v: number): string {
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(v);
}

/**
 * True when a present payload is NOT explicitly flagged live.
 *
 * Fail-closed: a payload must carry `is_sample_data: false` to be treated as
 * real. Matches GammaDensity's `carriesExplicitLiveFlag`, the reference
 * implementation in this family.
 */
function carriesSampleFlag(payload: unknown): boolean {
  // Nothing has arrived yet — the loading state covers this, not the badge.
  if (typeof payload !== "object" || payload === null) return false;
  // Fail CLOSED once a payload is present: only an explicit
  // `is_sample_data: false` counts as evidence of live data. This used to
  // test `=== true`, so a payload that omitted the flag entirely — a backend
  // stub, a shape change, a proxy that dropped it — rendered as live.
  return (payload as { is_sample_data?: unknown }).is_sample_data !== false;
}

// ---------------------------------------------------------------------------
// Selector sub-component
// ---------------------------------------------------------------------------

interface SelectorProps {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  placeholder?: string;
}

function Selector({ value, options, onChange, placeholder }: SelectorProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors min-w-16"
      >
        <span className="flex-1 text-left">{value || placeholder || "Select"}</span>
        <ChevronDown size={10} className={`transition-transform flex-none ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full max-h-48 overflow-y-auto">
          {options.map((opt) => (
            <button
              key={opt}
              onClick={() => { onChange(opt); setOpen(false); }}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${
                opt === value ? "text-accent" : "text-text-primary"
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function GEXWidget() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiry, setExpiry] = useState("");

  const isConnected = useBrokerConnected();
  const exchange = SYMBOL_EXCHANGE[symbol] ?? "NFO";

  const { data: liveData, isLoading, isError, error, refetch, isFetching } = useGEX(
    symbol,
    exchange,
    expiry,
    isConnected,
  );

  const data = isConnected ? liveData : SAMPLE_GEX_DATA;
  // Honesty affordance keyed on the payload FLAG, not connection state alone:
  // the backend serves a clearly-flagged sample GEX payload (is_sample_data)
  // when it has no live chain, even while a broker is connected.
  const isSample = !isConnected || carriesSampleFlag(liveData);

  // Build Plotly traces for grouped bar chart (Call GEX green, Put GEX red)
  const { barData, lineData, barLayout, lineLayout } = useMemo<{
    barData: Data[];
    lineData: Data[];
    barLayout: Partial<Layout>;
    lineLayout: Partial<Layout>;
  }>(() => {
    if (!data?.strikes?.length) {
      return { barData: [], lineData: [], barLayout: {}, lineLayout: {} };
    }

    const strikes = data.strikes.map((s) => s.strike);
    const callGex = data.strikes.map((s) => s.call_gex);
    const putGex = data.strikes.map((s) => s.put_gex);
    const netGex = data.strikes.map((s) => s.net_gex);
    const atmIdx = strikes.indexOf(data.atm_strike);

    const barData: Data[] = [
      {
        type: "bar",
        name: "Call GEX",
        x: strikes,
        y: callGex,
        marker: { color: "rgba(34,197,94,0.75)" },
        hovertemplate: "Strike: %{x}<br>Call GEX: %{y:.2e}<extra></extra>",
      } as Data,
      {
        type: "bar",
        name: "Put GEX",
        x: strikes,
        y: putGex,
        marker: { color: "rgba(239,68,68,0.75)" },
        hovertemplate: "Strike: %{x}<br>Put GEX: %{y:.2e}<extra></extra>",
      } as Data,
    ];

    const barLayout: Partial<Layout> = {
      barmode: "group",
      xaxis: { title: { text: "Strike" }, tickformat: ",.0f" },
      yaxis: { title: { text: "GEX" }, tickformat: ".2s" },
      margin: { t: 20, r: 10, b: 40, l: 55 },
      shapes:
        atmIdx >= 0
          ? [
              {
                type: "line",
                x0: data.atm_strike,
                x1: data.atm_strike,
                y0: 0,
                y1: 1,
                yref: "paper" as const,
                line: { color: "#6366f1", width: 1, dash: "dash" },
              },
            ]
          : [],
      annotations:
        atmIdx >= 0
          ? [
              {
                x: data.atm_strike,
                y: 1,
                yref: "paper" as const,
                text: "ATM",
                showarrow: false,
                font: { size: 9, color: "#6366f1" },
                yanchor: "top",
              },
            ]
          : [],
    };

    // Net GEX line — split into above-zero (green) and below-zero (red) fills
    const positiveY = netGex.map((v) => (v >= 0 ? v : 0));
    const negativeY = netGex.map((v) => (v < 0 ? v : 0));

    const lineData: Data[] = [
      {
        type: "scatter",
        mode: "none",
        name: "Net GEX (pos)",
        x: strikes,
        y: positiveY,
        fill: "tozeroy",
        fillcolor: "rgba(34,197,94,0.25)",
        hoverinfo: "skip",
      } as Data,
      {
        type: "scatter",
        mode: "none",
        name: "Net GEX (neg)",
        x: strikes,
        y: negativeY,
        fill: "tozeroy",
        fillcolor: "rgba(239,68,68,0.25)",
        hoverinfo: "skip",
      } as Data,
      {
        type: "scatter",
        mode: "lines",
        name: "Net GEX",
        x: strikes,
        y: netGex,
        line: { color: "#a0a0b8", width: 1.5 },
        hovertemplate: "Strike: %{x}<br>Net GEX: %{y:.2e}<extra></extra>",
      } as Data,
    ];

    const flipAnnotations: Partial<Layout>["annotations"] = [];
    if (data.gamma_flip_strike != null) {
      flipAnnotations.push({
        x: data.gamma_flip_strike,
        y: 0,
        text: `Flip: ${fmtStrike(data.gamma_flip_strike)}`,
        showarrow: true,
        arrowhead: 2,
        arrowcolor: "#f59e0b",
        font: { size: 9, color: "#f59e0b" },
      });
    }

    const lineLayout: Partial<Layout> = {
      xaxis: { tickformat: ",.0f" },
      yaxis: { title: { text: "Net GEX" }, tickformat: ".2s" },
      margin: { t: 10, r: 10, b: 40, l: 55 },
      shapes: [
        {
          type: "line",
          x0: 0,
          x1: 1,
          xref: "paper" as const,
          y0: 0,
          y1: 0,
          line: { color: getThemeColor("--color-border", "#2a2a3a"), width: 1 },
        },
        ...(data.gamma_flip_strike != null
          ? [
              {
                type: "line" as const,
                x0: data.gamma_flip_strike,
                x1: data.gamma_flip_strike,
                y0: 0,
                y1: 1,
                yref: "paper" as const,
                line: { color: "#f59e0b", width: 1, dash: "dot" as const },
              },
            ]
          : []),
      ],
      annotations: flipAnnotations,
    };

    return { barData, lineData, barLayout, lineLayout };
  }, [data]);

  const isLong = data?.dealer_zone?.toLowerCase().includes("long");

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Controls bar */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        {isSample && (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing demo data, not live gamma exposure"
            title="Demo data — fabricated sample values, not a live option chain."
          >
            Demo data
          </span>
        )}
        <Selector
          value={symbol}
          options={SYMBOLS}
          onChange={(v) => { setSymbol(v); setExpiry(""); }}
        />
        <span className="px-1.5 py-0.5 text-xs text-text-muted bg-surface-base border border-border-default rounded">
          {exchange}
        </span>
        <Input
          value={expiry}
          onChange={(e) => setExpiry(e.target.value)}
          placeholder="Expiry (YYYY-MM-DD)"
          className="w-32 h-7 text-xs"
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
          <span>{(error as Error)?.message ?? "Failed to load GEX data"}</span>
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
          <Loader2 size={16} className="animate-spin" />
          Loading GEX data...
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !data && !isError && (
        <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
          Enter symbol and expiry to view Gamma Exposure
        </div>
      )}

      {/* Charts */}
      {data && (() => {
        const chartContent = (
          <>
            {/* Bar chart — Call GEX vs Put GEX */}
            <div className="flex-1 min-h-0">
              <PlotlyChart data={barData} layout={barLayout} />
            </div>

            {/* Net GEX line chart */}
            <div className="flex-none h-[30%] border-t border-border-default">
              <PlotlyChart data={lineData} layout={lineLayout} />
            </div>

            {/* Summary footer */}
            <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1.5 flex items-center gap-4 text-xs flex-wrap">
              <div className="flex items-center gap-1.5">
                <span className="text-text-muted uppercase tracking-wide">Net GEX</span>
                <span className={`font-mono tabular-nums font-semibold ${data.net_gex >= 0 ? "text-profit" : "text-loss"}`}>
                  {fmtGEX(data.net_gex)}
                </span>
              </div>

              {data.gamma_flip_strike != null && (
                <div className="flex items-center gap-1.5">
                  <span className="text-text-muted uppercase tracking-wide">Flip</span>
                  <span className="font-mono tabular-nums text-warning">
                    {fmtStrike(data.gamma_flip_strike)}
                  </span>
                </div>
              )}

              <div className="flex items-center gap-1.5">
                <span className={`px-1.5 py-0.5 text-xxs font-medium rounded border ${
                  isLong
                    ? "text-profit bg-profit/10 border-profit/30"
                    : "text-loss bg-loss/10 border-loss/30"
                }`}>
                  {data.dealer_zone ?? "—"}
                </span>
              </div>

              {data.atm_strike > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-text-muted uppercase tracking-wide">ATM</span>
                  <span className="font-mono tabular-nums text-accent">
                    {fmtStrike(data.atm_strike)}
                  </span>
                </div>
              )}
            </div>
          </>
        );

        return isConnected ? (
          chartContent
        ) : (
          <FeatureTeaser
            status="preview"
            featureName="GEX Dashboard"
            version={APP_VERSION_TAG}
          >
            {chartContent}
          </FeatureTeaser>
        );
      })()}
    </div>
  );
}

export default memo(GEXWidget);

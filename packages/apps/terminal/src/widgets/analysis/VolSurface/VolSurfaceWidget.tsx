/**
 * VolSurfaceWidget — 3D Implied Volatility Surface for FlintTrade terminal.
 *
 * Features:
 *   - 3D Plotly surface chart: X=strike, Y=days-to-expiry, Z=implied volatility
 *   - Color scale: RdYlBu_r (blue=low IV, red=high IV)
 *   - Multi-expiry support: enter comma-separated expiry dates
 *   - IV range and ATM IV shown in footer
 *   - Auto-refresh: 30s market hours (when broker connected)
 *   - FeatureTeaser with sample data when no broker is connected
 */

import { useState, useMemo, memo } from "react";
import { RefreshCw, AlertCircle, Loader2 } from "lucide-react";
import { useVolSurface } from "./useVolSurface";
import { SAMPLE_VOL_SURFACE_DATA } from "./sampleData";
import { PlotlyChart } from "@/components/charts/PlotlyChart";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
// Main widget
// ---------------------------------------------------------------------------

function VolSurfaceWidget() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiriesInput, setExpiriesInput] = useState("");
  const [strikeCount, setStrikeCount] = useState(20);

  const isConnected = useBrokerConnected();
  const exchange = SYMBOL_EXCHANGE[symbol] ?? "NFO";

  const expiryDates = useMemo(
    () =>
      expiriesInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    [expiriesInput],
  );

  const { data: liveData, isLoading, isError, error, refetch, isFetching } =
    useVolSurface(symbol, exchange, expiryDates, strikeCount, isConnected);

  const data = isConnected ? liveData : SAMPLE_VOL_SURFACE_DATA;
  // Honesty affordance keyed on the payload FLAG, not connection state alone:
  // the backend serves a clearly-flagged sample surface (is_sample_data) when
  // it has no live chain, even while a broker is connected.
  const isSample = !isConnected || carriesSampleFlag(liveData);

  const plotData = useMemo<Data[]>(() => {
    if (!data?.iv_matrix?.length) return [];

    return [
      {
        type: "surface",
        x: data.strikes,
        y: data.days_to_expiry,
        z: data.iv_matrix,
        colorscale: "RdYlBu",
        reversescale: true,
        colorbar: {
          title: { text: "IV %" },
          thickness: 12,
          len: 0.7,
        },
        hovertemplate:
          "Strike: %{x}<br>DTE: %{y}d<br>IV: %{z:.1f}%<extra></extra>",
        contours: {
          z: { show: true, usecolormap: true, highlightcolor: "#fff", project: { z: true } },
        },
      } as Data,
    ];
  }, [data]);

  const plotLayout = useMemo<Partial<Layout>>(() => {
    return {
      scene: {
        xaxis: { title: { text: "Strike" }, tickformat: ",.0f" },
        yaxis: { title: { text: "Days to Expiry" } },
        zaxis: { title: { text: "IV (%)" } },
        camera: {
          eye: { x: 1.5, y: -1.5, z: 0.8 },
        },
        bgcolor: "transparent",
      },
      margin: { t: 10, r: 10, b: 10, l: 10 },
    };
  }, []);

  // Stats
  const ivStats = useMemo(() => {
    if (!data?.iv_matrix?.length) return null;
    const flat = data.iv_matrix.flat().filter((v) => v > 0);
    if (!flat.length) return null;
    const min = Math.min(...flat);
    const max = Math.max(...flat);
    return { min, max };
  }, [data]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default flex-wrap">
        {isSample && (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing demo data, not a live volatility surface"
            title="Demo data — fabricated sample values, not a live option chain."
          >
            Demo data
          </span>
        )}
        <Select value={symbol} onValueChange={setSymbol}>
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
          value={expiriesInput}
          onChange={(e) => setExpiriesInput(e.target.value)}
          placeholder="Expiries (comma-sep, YYYY-MM-DD)"
          className="flex-1 min-w-44 px-2 py-0.5 text-xs bg-surface-hover border border-border-default rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent/50"
        />
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-text-muted">Strikes</span>
          <input
            type="range"
            min={10}
            max={40}
            value={strikeCount}
            onChange={(e) => setStrikeCount(Number(e.target.value))}
            className="w-20 accent-accent"
          />
          <span className="text-xs font-mono text-text-secondary w-5">{strikeCount}</span>
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

      {/* Error */}
      {isError && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{(error as Error)?.message ?? "Failed to load vol surface"}</span>
        </div>
      )}

      {/* Loading — only shown when connected and query is running */}
      {isConnected && isLoading && (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
          <Loader2 size={16} className="animate-spin" />
          Building volatility surface...
        </div>
      )}

      {/* Empty state — only when connected but no data yet */}
      {isConnected && !isLoading && !liveData && !isError && (
        <div className="flex-1 flex items-center justify-center text-center text-text-muted text-sm px-4">
          Enter symbol and at least one expiry date to view the volatility surface
        </div>
      )}

      {/* 3D Surface chart */}
      {data && plotData.length > 0 && (() => {
        const chartContent = (
          <>
            <div className="flex-1 min-h-0">
              <PlotlyChart
                data={plotData}
                layout={plotLayout}
                config={{ displayModeBar: true, responsive: true }}
              />
            </div>

            {/* Footer stats */}
            <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1.5 flex items-center gap-4 text-xs">
              {data.atm_strike > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-text-muted uppercase tracking-wide">ATM</span>
                  <span className="font-mono tabular-nums text-accent">
                    {new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(data.atm_strike)}
                  </span>
                </div>
              )}
              {ivStats && (
                <>
                  <div className="flex items-center gap-1.5">
                    <span className="text-text-muted uppercase tracking-wide">IV Range</span>
                    <span className="font-mono tabular-nums text-text-secondary">
                      {ivStats.min.toFixed(1)}% – {ivStats.max.toFixed(1)}%
                    </span>
                  </div>
                </>
              )}
              <div className="ml-auto text-text-muted">
                {data.expiries.length} expir{data.expiries.length === 1 ? "y" : "ies"} · {data.strikes.length} strikes
              </div>
            </div>
          </>
        );

        return isConnected ? (
          chartContent
        ) : (
          <FeatureTeaser
            status="preview"
            featureName="Volatility Surface"
            version={APP_VERSION_TAG}
          >
            {chartContent}
          </FeatureTeaser>
        );
      })()}
    </div>
  );
}

export default memo(VolSurfaceWidget);

/**
 * OIProfileWidget — OI Profile with Futures Candlestick for FlintTrade terminal.
 *
 * Two-pane layout:
 *   Top (40%): Futures OHLCV candlestick (Lightweight Charts v5)
 *   Bottom (60%): OI Butterfly horizontal bar chart (Plotly)
 *     - CE OI bars extend right (red)
 *     - PE OI bars extend left (green)
 *     - ATM strike highlighted
 *     - Max pain strike annotated
 *
 * Auto-refresh: 30s market hours (when broker connected)
 * FeatureTeaser with sample data when no broker is connected
 */

import { useState, useEffect, useRef, useMemo, memo } from "react";
import type { CandlestickData, HistogramData, IChartApi, ISeriesApi, MouseEventParams, Time } from "lightweight-charts";
import {
  createFlintCandlestickChart,
  FlintChartLegend,
  getFlintChartCrosshairReadout,
} from "@flinttrade/design-system";
import type { FlintChartLegendState } from "@flinttrade/design-system";
import { RefreshCw, AlertCircle, Loader2 } from "lucide-react";
import { useOIProfile } from "./useOIProfile";
import { SAMPLE_OI_PROFILE_DATA } from "./sampleData";
import { PlotlyChart } from "@/components/charts/PlotlyChart";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import { useModeStore } from "@/stores/modeStore";
import { getHistory } from "@/services/api";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { lightweightCandlestickRuntime } from "@/lib/lightweightChartRuntime";
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
const SPOT_EXCHANGE: Record<string, string> = {
  NIFTY: "NSE_INDEX",
  BANKNIFTY: "NSE_INDEX",
  FINNIFTY: "NSE_INDEX",
  MIDCPNIFTY: "NSE_INDEX",
  SENSEX: "BSE_INDEX",
};

const INTERVALS = ["5m", "15m", "1h", "1D"];
const INTERVAL_MAP: Record<string, string> = {
  "5m": "5",
  "15m": "15",
  "1h": "60",
  "1D": "D",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Read a CSS custom property from the document root at call time. */
function getThemeColor(varName: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || fallback;
}

function fmtOI(v: number): string {
  if (v >= 1e7) return `${(v / 1e7).toFixed(1)}Cr`;
  if (v >= 1e5) return `${(v / 1e5).toFixed(1)}L`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(v);
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function OIProfileWidget() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiry, setExpiry] = useState("");
  const [interval, setInterval] = useState("15m");

  const isConnected = useBrokerConnected();
  const mode = useModeStore((s) => s.mode);
  const exchange = SYMBOL_EXCHANGE[symbol] ?? "NFO";
  const spotExchange = SPOT_EXCHANGE[symbol] ?? "NSE_INDEX";

  const { data: liveData, isLoading, isError, error, refetch, isFetching } = useOIProfile(
    symbol,
    exchange,
    expiry,
    undefined,
    isConnected && mode !== "explore",
  );

  // Explore mode is the documented boundary for sample data — it must not be
  // gated on broker connection, since an Explore user with a live broker
  // connection would otherwise get production data instead of the demo set.
  const data = mode === "explore" ? SAMPLE_OI_PROFILE_DATA : liveData;

  // ---------------------------------------------------------------------------
  // Lightweight Charts — futures candlestick (top pane)
  // ---------------------------------------------------------------------------

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const flintChartRef = useRef<ReturnType<typeof createFlintCandlestickChart<IChartApi, ISeriesApi<"Candlestick">, ISeriesApi<"Histogram">>> | null>(null);
  const [legend, setLegend] = useState<FlintChartLegendState | null>(null);
  const chartTheme = useLightweightChartTheme();

  useEffect(() => {
    const el = chartContainerRef.current;
    if (!el) return;

    const flintChart = createFlintCandlestickChart(
      lightweightCandlestickRuntime,
      el,
      chartTheme,
      {
        ariaLabel: `${symbol} futures price chart`,
        layout: {
          background: { color: "transparent" },
          fontFamily: "Inter, system-ui, sans-serif",
          fontSize: 11,
        },
        timeScale: { timeVisible: true, secondsVisible: false },
      },
    );
    const { chart, candleSeries, volumeSeries } = flintChart;

    chartRef.current = chart;
    seriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    flintChartRef.current = flintChart;

    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      setLegend(getFlintChartCrosshairReadout(param, candleSeries, volumeSeries));
    });

    return () => {
      flintChart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volumeSeriesRef.current = null;
      flintChartRef.current = null;
      setLegend(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    flintChartRef.current?.applyTheme(chartTheme, {
      layout: {
        background: { color: "transparent" },
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: 11,
      },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
  }, [chartTheme]);

  // Fetch and set OHLCV data when symbol/interval changes
  useEffect(() => {
    if (!seriesRef.current || !volumeSeriesRef.current) return;
    let cancelled = false;

    const iv = INTERVAL_MAP[interval] ?? "15";
    const today = new Date();
    const endDate = today.toISOString().slice(0, 10);
    const startDate = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000)
      .toISOString()
      .slice(0, 10);

    getHistory(symbol, spotExchange, iv, startDate, endDate)
      .then((bars) => {
        if (cancelled || !seriesRef.current || !volumeSeriesRef.current || !Array.isArray(bars)) return;
        const candles: CandlestickData[] = bars
          .filter((b) => b.timestamp && b.open && b.high && b.low && b.close)
          .map((b) => ({
            time: Math.floor(b.timestamp / 1000) as Time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          }))
          .sort((a, b) => Number(a.time) - Number(b.time));
        const volumes: HistogramData[] = bars
          .filter((b) => b.timestamp && Number.isFinite(b.volume))
          .map((b) => ({
            time: Math.floor(b.timestamp / 1000) as Time,
            value: b.volume,
            color: b.close >= b.open ? "rgba(34,197,94,0.22)" : "rgba(239,68,68,0.22)",
          }))
          .sort((a, b) => Number(a.time) - Number(b.time));
        seriesRef.current.setData(candles);
        volumeSeriesRef.current.setData(volumes);
        chartRef.current?.timeScale().fitContent();
      })
      .catch(() => {
        // Chart fails silently — OI butterfly is the main feature
      });

    return () => { cancelled = true; };
  }, [symbol, spotExchange, interval]);

  // ---------------------------------------------------------------------------
  // OI Butterfly Plotly chart (bottom pane)
  // ---------------------------------------------------------------------------

  const { butterflyData, butterflyLayout } = useMemo<{
    butterflyData: Data[];
    butterflyLayout: Partial<Layout>;
  }>(() => {
    if (!data?.strikes?.length) return { butterflyData: [], butterflyLayout: {} };

    const strikes = data.strikes.map((s) => s.strike);
    // CE OI bars go right (positive), PE OI bars go left (negative)
    const ceOI = data.strikes.map((s) => s.ce_oi);
    const peOI = data.strikes.map((s) => -s.pe_oi); // negative = left

    const butterflyData: Data[] = [
      {
        type: "bar",
        name: "CE OI",
        x: ceOI,
        y: strikes,
        orientation: "h",
        marker: { color: "rgba(239,68,68,0.65)" },
        hovertemplate: "Strike: %{y}<br>CE OI: %{x:.3s}<extra></extra>",
      } as Data,
      {
        type: "bar",
        name: "PE OI",
        x: peOI,
        y: strikes,
        orientation: "h",
        marker: { color: "rgba(34,197,94,0.65)" },
        hovertemplate: "Strike: %{y}<br>PE OI: %{x:.3s}<extra></extra>",
      } as Data,
    ];

    const annotations: Partial<Layout>["annotations"] = [];
    if (data.max_pain_strike > 0) {
      annotations.push({
        y: data.max_pain_strike,
        x: 0,
        xref: "x" as const,
        text: `Max Pain ${data.max_pain_strike}`,
        showarrow: true,
        arrowhead: 2,
        arrowcolor: "#f59e0b",
        font: { size: 9, color: "#f59e0b" },
        ax: 50,
        ay: 0,
      });
    }

    const shapes: Partial<Layout>["shapes"] = [];
    if (data.atm_strike > 0) {
      shapes.push({
        type: "line",
        y0: data.atm_strike,
        y1: data.atm_strike,
        x0: 0,
        x1: 1,
        xref: "paper" as const,
        line: { color: "#6366f1", width: 1, dash: "dash" },
      });
    }

    const butterflyLayout: Partial<Layout> = {
      barmode: "overlay",
      xaxis: {
        title: { text: "Open Interest" },
        tickformat: ".3s",
        zeroline: true,
        zerolinecolor: getThemeColor("--color-border", "#2a2a3a"),
        zerolinewidth: 1,
        automargin: true,
      },
      yaxis: {
        title: { text: "Strike", standoff: 6 },
        tickformat: ",.0f",
        tickmode: "auto",
        nticks: 8,
        automargin: true,
      },
      margin: { t: 10, r: 10, b: 45, l: 68 },
      annotations,
      shapes,
    };

    return { butterflyData, butterflyLayout };
  }, [data]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default flex-wrap">
        <Select value={symbol} onValueChange={(v) => { setSymbol(v); setExpiry(""); }}>
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
        {/* Interval selector */}
        <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
          {INTERVALS.map((iv) => (
            <button
              key={iv}
              onClick={() => setInterval(iv)}
              className={`px-1.5 py-0.5 text-xxs font-medium transition-colors ${
                iv === interval
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              {iv}
            </button>
          ))}
        </div>
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
          <span>{(error as Error)?.message ?? "Failed to load OI profile"}</span>
        </div>
      )}

      {/* Top: Futures candlestick */}
      <div className="relative flex-none h-[38%] border-b border-border-default">
        <div ref={chartContainerRef} className="w-full h-full" />
        {legend && (
          <FlintChartLegend
            legend={legend}
            className="pointer-events-none absolute left-2 top-2 z-10 max-w-[calc(100%-1rem)] overflow-x-auto"
          />
        )}
      </div>

      {/* Bottom: OI Butterfly */}
      <div className="flex-1 min-h-0 flex flex-col">
        {isConnected && isLoading && (
          <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
            <Loader2 size={16} className="animate-spin" />
            Loading OI profile...
          </div>
        )}
        {isConnected && !isLoading && !liveData && !isError && (
          <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
            Enter symbol and expiry to view OI profile
          </div>
        )}
        {data && butterflyData.length > 0 && (() => {
          const chart = (
            <div className="flex-1 min-h-0">
              <PlotlyChart data={butterflyData} layout={butterflyLayout} />
            </div>
          );
          return isConnected ? (
            chart
          ) : (
            <FeatureTeaser
              status="in_dev"
              featureName="OI Profile"
              version={APP_VERSION_TAG}
            >
              {chart}
            </FeatureTeaser>
          );
        })()}
      </div>

      {/* Footer */}
      {data && (
        <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1.5 flex items-center gap-4 text-xs flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="text-text-muted uppercase tracking-wide">PCR</span>
            <span className={`font-mono tabular-nums font-semibold px-1 py-0.5 rounded border ${
              data.pcr >= 1.2
                ? "text-profit bg-profit/10 border-profit/30"
                : data.pcr <= 0.8
                  ? "text-loss bg-loss/10 border-loss/30"
                  : "text-warning bg-warning/10 border-warning/30"
            }`}>
              {data.pcr.toFixed(2)}
            </span>
          </div>
          {data.max_pain_strike > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-text-muted uppercase tracking-wide">Max Pain</span>
              <span className="font-mono tabular-nums text-warning">
                {new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(data.max_pain_strike)}
              </span>
            </div>
          )}
          <div className="flex items-center gap-1.5">
            <span className="text-loss font-mono tabular-nums">CE {fmtOI(data.total_ce_oi)}</span>
            <span className="text-text-muted">·</span>
            <span className="text-profit font-mono tabular-nums">PE {fmtOI(data.total_pe_oi)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(OIProfileWidget);

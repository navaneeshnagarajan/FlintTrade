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
 * Auto-refresh: 30s market hours
 */

import { useState, useEffect, useRef, useMemo } from "react";
import { createChart, CandlestickSeries } from "lightweight-charts";
import type { IChartApi, ISeriesApi, CandlestickData, Time } from "lightweight-charts";
import { RefreshCw, AlertCircle, Loader2 } from "lucide-react";
import { useOIProfile } from "./useOIProfile";
import { PlotlyChart } from "@/components/charts/PlotlyChart";
import { getHistory } from "@/services/api";
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

function fmtOI(v: number): string {
  if (v >= 1e7) return `${(v / 1e7).toFixed(1)}Cr`;
  if (v >= 1e5) return `${(v / 1e5).toFixed(1)}L`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(v);
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

export default function OIProfileWidget() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiry, setExpiry] = useState("");
  const [interval, setInterval] = useState("15m");

  const exchange = SYMBOL_EXCHANGE[symbol] ?? "NFO";
  const spotExchange = SPOT_EXCHANGE[symbol] ?? "NSE_INDEX";

  const { data, isLoading, isError, error, refetch, isFetching } = useOIProfile(
    symbol,
    exchange,
    expiry,
  );

  // ---------------------------------------------------------------------------
  // Lightweight Charts — futures candlestick (top pane)
  // ---------------------------------------------------------------------------

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    const el = chartContainerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      width: el.clientWidth,
      height: el.clientHeight,
      layout: {
        background: { color: "transparent" },
        textColor: "#a0a0b0",
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#1e1e2e" },
        horzLines: { color: "#1e1e2e" },
      },
      rightPriceScale: { borderColor: "#2a2a3a" },
      timeScale: { borderColor: "#2a2a3a", timeVisible: true, secondsVisible: false },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver(() => {
      chart.resize(el.clientWidth, el.clientHeight);
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Fetch and set OHLCV data when symbol/interval changes
  useEffect(() => {
    if (!seriesRef.current) return;
    let cancelled = false;

    const iv = INTERVAL_MAP[interval] ?? "15";
    const today = new Date();
    const endDate = today.toISOString().slice(0, 10);
    const startDate = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000)
      .toISOString()
      .slice(0, 10);

    getHistory(symbol, spotExchange, iv, startDate, endDate)
      .then((bars) => {
        if (cancelled || !seriesRef.current || !Array.isArray(bars)) return;
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
        seriesRef.current.setData(candles);
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
        zerolinecolor: "#2a2a3a",
        zerolinewidth: 1,
      },
      yaxis: {
        title: { text: "Strike" },
        tickformat: ",.0f",
        dtick: data.strikes.length > 1
          ? (data.strikes[1].strike - data.strikes[0].strike)
          : undefined,
      },
      margin: { t: 10, r: 10, b: 45, l: 60 },
      annotations,
      shapes,
    };

    return { butterflyData, butterflyLayout };
  }, [data]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default flex-wrap">
        <select
          value={symbol}
          onChange={(e) => { setSymbol(e.target.value); setExpiry(""); }}
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
      <div className="flex-none h-[38%] border-b border-border-default">
        <div ref={chartContainerRef} className="w-full h-full" />
      </div>

      {/* Bottom: OI Butterfly */}
      <div className="flex-1 min-h-0 flex flex-col">
        {isLoading && (
          <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
            <Loader2 size={16} className="animate-spin" />
            Loading OI profile...
          </div>
        )}
        {!isLoading && !data && !isError && (
          <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
            Enter symbol and expiry to view OI profile
          </div>
        )}
        {data && butterflyData.length > 0 && (
          <div className="flex-1 min-h-0">
            <PlotlyChart data={butterflyData} layout={butterflyLayout} />
          </div>
        )}
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

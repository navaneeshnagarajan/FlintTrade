/**
 * SpotPricePane — the optional price candlestick strip above the OI views.
 *
 * MISLABEL FIX. The retired OI Profile widget titled this pane "futures price
 * chart" (header text and `aria-label`) while fetching
 * `getHistory(symbol, spotExchange)` with `spotExchange` = NSE_INDEX / BSE_INDEX
 * — index SPOT, not the futures contract. The data was never futures. Rather
 * than resolve and fetch a rolling futures symbol (a different instrument, a
 * different roll policy and a different set of failure modes), the pane now
 * says what it actually shows: spot.
 *
 * Loaded lazily so an OI panel that never opens the pane does not pull
 * lightweight-charts into its chunk.
 */

import { useEffect, useRef, useState } from "react";
import type {
  CandlestickData,
  HistogramData,
  IChartApi,
  ISeriesApi,
  MouseEventParams,
  Time,
} from "lightweight-charts";
import {
  createFlintCandlestickChart,
  FlintChartLegend,
  getFlintChartCrosshairReadout,
} from "@flinttrade/design-system";
import type { FlintChartLegendState } from "@flinttrade/design-system";
import { getHistory } from "@/services/api";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { lightweightCandlestickRuntime } from "@/lib/lightweightChartRuntime";
import { SPOT_INTERVAL_RESOLUTIONS, type SpotInterval } from "./spotIntervals";

interface SpotPricePaneProps {
  /** Underlying label, e.g. NIFTY. */
  symbol: string;
  /** The SPOT exchange (NSE_INDEX / BSE_INDEX / MCX …), not the F&O one. */
  spotExchange: string;
  interval: SpotInterval;
}

export function SpotPricePane({ symbol, spotExchange, interval }: SpotPricePaneProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const flintChartRef = useRef<ReturnType<
    typeof createFlintCandlestickChart<IChartApi, ISeriesApi<"Candlestick">, ISeriesApi<"Histogram">>
  > | null>(null);
  const [legend, setLegend] = useState<FlintChartLegendState | null>(null);
  const chartTheme = useLightweightChartTheme();

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const flintChart = createFlintCandlestickChart(
      lightweightCandlestickRuntime,
      el,
      chartTheme,
      {
        ariaLabel: `${symbol} spot price chart`,
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

  useEffect(() => {
    if (!seriesRef.current || !volumeSeriesRef.current) return;
    let cancelled = false;

    const resolution = SPOT_INTERVAL_RESOLUTIONS[interval] ?? "15";
    const today = new Date();
    const endDate = today.toISOString().slice(0, 10);
    const startDate = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000)
      .toISOString()
      .slice(0, 10);

    getHistory(symbol, spotExchange, resolution, startDate, endDate)
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
        // The price strip fails silently — the OI view is the main feature.
      });

    return () => { cancelled = true; };
  }, [symbol, spotExchange, interval]);

  return (
    <div className="relative h-full w-full" data-testid="spot-price-pane">
      <div ref={containerRef} className="w-full h-full" />
      {/* Visible provenance for the series: this is index spot, not futures. */}
      <span
        className="pointer-events-none absolute right-2 top-2 z-10 rounded border border-border-default bg-surface-card/80 px-1.5 py-0.5 text-xxs text-text-muted"
        data-testid="spot-price-caption"
      >
        {symbol} spot · {interval}
      </span>
      {legend && (
        <FlintChartLegend
          legend={legend}
          className="pointer-events-none absolute left-2 top-2 z-10 max-w-[calc(100%-1rem)] overflow-x-auto"
        />
      )}
    </div>
  );
}

export default SpotPricePane;

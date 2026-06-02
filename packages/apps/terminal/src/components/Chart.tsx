import { useEffect, useRef } from "react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import {
  applyFlintCandlestickTheme,
  createFlintCandlestickChart,
} from "@flinttrade/design-system";
import { getHistory } from "../services/api";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { lightweightCandlestickRuntime } from "@/lib/lightweightChartRuntime";

interface ChartProps {
  symbol?: string;
  exchange?: string;
  interval?: string;
  height?: number;
  className?: string;
}

/**
 * TradingView Lightweight Charts v5 wrapper.
 * Fetches historical OHLCV via API. Live ticks are routed through Jotai
 * atoms (useWsBridge) — no direct window event listeners needed here.
 */
export default function Chart({
  symbol = "NIFTY",
  exchange = "NSE_INDEX",
  interval = "5m",
  height = 400,
  className = "",
}: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const chartTheme = useLightweightChartTheme();

  // Create chart
  useEffect(() => {
    if (!containerRef.current) return;
    const flintChart = createFlintCandlestickChart(
      lightweightCandlestickRuntime,
      containerRef.current,
      chartTheme,
      {
        ariaLabel: `${symbol} price chart`,
        height,
      },
    );
    const { chart, candleSeries, volumeSeries } = flintChart;

    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;

    return () => {
      flintChart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
    };
  }, [height, symbol]);

  // Re-apply theme whenever it changes (without recreating the chart)
  useEffect(() => {
    if (!chartRef.current || !candleRef.current) return;
    applyFlintCandlestickTheme(chartRef.current, candleRef.current, chartTheme);
  }, [chartTheme]);

  // Fetch historical data
  useEffect(() => {
    if (!candleRef.current || !volumeRef.current) return;
    let cancelled = false;
    const candleSeries = candleRef.current;
    const volumeSeries = volumeRef.current;

    (async () => {
      try {
        const endDate = new Date().toISOString().slice(0, 10);
        const start = new Date();
        start.setDate(start.getDate() - 30);
        const startDate = start.toISOString().slice(0, 10);

        const data = await getHistory(symbol, exchange, interval, startDate, endDate);
        if (cancelled || !Array.isArray(data)) return;

        const candles = data.map((b) => ({
          time: b.timestamp as unknown as import("lightweight-charts").Time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }));
        const volumes = data.map((b) => ({
          time: b.timestamp as unknown as import("lightweight-charts").Time,
          value: b.volume || 0,
          color: b.close >= b.open ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)",
        }));

        candleSeries.setData(candles);
        volumeSeries.setData(volumes);
      } catch {
        /* API may not be available */
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [symbol, exchange, interval]);

  return <div ref={containerRef} className={`w-full ${className}`} />;
}

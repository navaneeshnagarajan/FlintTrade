import { useEffect, useRef } from "react";
import { createChart, CandlestickSeries, HistogramSeries } from "lightweight-charts";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import { getHistory } from "../services/api";

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

  // Create chart
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: { background: { color: "#0a0a0a" }, textColor: "#e5e5e5" },
      grid: { vertLines: { color: "#1a1a2e" }, horzLines: { color: "#1a1a2e" } },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: "#2a2a3e" },
      timeScale: { borderColor: "#2a2a3e", timeVisible: true, secondsVisible: false },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [height]);

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
          time: Math.floor(new Date(String(b.time)).getTime() / 1000) as unknown as import("lightweight-charts").Time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }));
        const volumes = data.map((b) => ({
          time: Math.floor(new Date(String(b.time)).getTime() / 1000) as unknown as import("lightweight-charts").Time,
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

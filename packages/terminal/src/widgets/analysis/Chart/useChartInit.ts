// Chart initialisation hook.
// Creates the lightweight-charts instance, attaches it to the container,
// sets up the resize observer, wires the crosshair legend, and returns
// stable refs to the chart and its primary series.

import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  createSeriesMarkers,
} from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  MouseEventParams,
  CandlestickData,
  HistogramData,
  Time,
} from "lightweight-charts";
import type { LegendState } from "./ChartLegend";
import type { IndicatorSeriesRefs } from "./types";

export type { IndicatorSeriesRefs };

// ---------------------------------------------------------------------------
// Constants (chart theme + candle colours)
// ---------------------------------------------------------------------------

const CHART_THEME = {
  layout: {
    background: { color: "#0a0a0a" },
    textColor: "#e5e5e5",
    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
    fontSize: 11,
  },
  grid: {
    vertLines: { color: "#1a1a2e" },
    horzLines: { color: "#1a1a2e" },
  },
  crosshair: { mode: 0 },
  rightPriceScale: { borderColor: "#2a2a3e" },
  timeScale: {
    borderColor: "#2a2a3e",
    timeVisible: true,
    secondsVisible: false,
  },
} as const;

const CANDLE_OPTIONS = {
  upColor: "#22c55e",
  downColor: "#ef4444",
  borderUpColor: "#22c55e",
  borderDownColor: "#ef4444",
  wickUpColor: "#22c55e",
  wickDownColor: "#ef4444",
};

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface ChartInitRefs {
  containerRef: React.RefObject<HTMLDivElement | null>;
  chartRef: React.MutableRefObject<IChartApi | null>;
  candleRef: React.MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  volumeRef: React.MutableRefObject<ISeriesApi<"Histogram"> | null>;
  markersPluginRef: React.MutableRefObject<ISeriesMarkersPluginApi<Time> | null>;
  indRef: React.MutableRefObject<IndicatorSeriesRefs>;
}

/**
 * Initialises the lightweight-charts instance once, wires the resize
 * observer, and subscribes the crosshair-move event to keep the OHLCV
 * legend state up to date.
 *
 * The caller owns the `setLegend` state setter so the legend value can
 * live in the component tree without this hook holding React state itself.
 */
export function useChartInit(
  setLegend: (state: LegendState | null) => void,
): ChartInitRefs {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  const indRef = useRef<IndicatorSeriesRefs>({
    ema20: null,
    ema50: null,
    sma: null,
    wma: null,
    bbUpper: null,
    bbMiddle: null,
    bbLower: null,
    stUp: null,
    stDown: null,
    vwap: null,
    ichTenkan: null,
    ichKijun: null,
    ichSenkouA: null,
    ichSenkouB: null,
    ichChikou: null,
    rsi: null,
    macdLine: null,
    macdSignal: null,
    macdHist: null,
    stochK: null,
    stochD: null,
    atr: null,
    adx: null,
    adxPlus: null,
    adxMinus: null,
    williamsR: null,
    cci: null,
    dema: null,
    hullMA: null,
    parSar: null,
    obv: null,
    keltnerUpper: null,
    keltnerMiddle: null,
    keltnerLower: null,
    vwma: null,
  });

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      ...CHART_THEME,
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, CANDLE_OPTIONS);

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    markersPluginRef.current = createSeriesMarkers(candleSeries, []);

    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;

    // Crosshair OHLCV legend
    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      if (!param || !param.time || !candleSeries) {
        setLegend(null);
        return;
      }
      const bar = param.seriesData.get(candleSeries) as CandlestickData | undefined;
      const vol = param.seriesData.get(volumeSeries) as HistogramData | undefined;
      if (bar) {
        setLegend({
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
          volume: vol?.value ?? null,
          bull: bar.close >= bar.open,
        });
      }
    });

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        chart.applyOptions({ width, height });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      markersPluginRef.current = null;
      indRef.current = {
        ema20: null,
        ema50: null,
        sma: null,
        wma: null,
        bbUpper: null,
        bbMiddle: null,
        bbLower: null,
        stUp: null,
        stDown: null,
        vwap: null,
        ichTenkan: null,
        ichKijun: null,
        ichSenkouA: null,
        ichSenkouB: null,
        ichChikou: null,
        rsi: null,
        macdLine: null,
        macdSignal: null,
        macdHist: null,
        stochK: null,
        stochD: null,
        atr: null,
        adx: null,
        adxPlus: null,
        adxMinus: null,
        williamsR: null,
        cci: null,
        dema: null,
        hullMA: null,
        parSar: null,
        obv: null,
        keltnerUpper: null,
        keltnerMiddle: null,
        keltnerLower: null,
        vwma: null,
      };
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // chart created once; setLegend is stable (state setter)

  return { containerRef, chartRef, candleRef, volumeRef, markersPluginRef, indRef };
}

// Chart initialisation hook.
// Creates the lightweight-charts instance, attaches it to the container,
// sets up the resize observer, wires the crosshair legend, and returns
// stable refs to the chart and its primary series.

import { useEffect, useRef } from "react";
import type {
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  MouseEventParams,
  Time,
} from "lightweight-charts";
import {
  createFlintCandlestickChart,
  getFlintChartCrosshairReadout,
} from "@flinttrade/design-system";
import type { LegendState } from "./ChartLegend";
import type { IndicatorSeriesRefs } from "./types";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { lightweightCandlestickRuntime } from "@/lib/lightweightChartRuntime";

export type { IndicatorSeriesRefs };

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
  const chartTheme = useLightweightChartTheme();

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

    const flintChart = createFlintCandlestickChart(
      lightweightCandlestickRuntime,
      containerRef.current,
      chartTheme,
      { ariaLabel: "Price chart" },
    );
    const chart = flintChart.chart;
    const candleSeries = flintChart.candleSeries;
    const volumeSeries = flintChart.volumeSeries;

    markersPluginRef.current = flintChart.markersPlugin;

    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;

    // Crosshair OHLCV readout is normalised in the shared chart core so every
    // chart surface can converge on the same behaviour.
    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      setLegend(getFlintChartCrosshairReadout(param, candleSeries, volumeSeries));
    });

    return () => {
      flintChart.remove();
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
  }, []); // mount once; ChartWidget.tsx's dedicated theme effect handles theme changes via applyOptions

  return { containerRef, chartRef, candleRef, volumeRef, markersPluginRef, indRef };
}

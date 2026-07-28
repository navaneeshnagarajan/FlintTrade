// Indicator series lifecycle hook.
// Manages adding / updating / removing indicator series on the chart
// whenever indicator toggles or periods change.

import { useEffect, useCallback, useRef } from "react";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import {
  createFlintChartIndicatorPaneOptions,
  createFlintChartIndicatorSeriesRenderPlan,
  createFlintChartIndicatorSeriesRenderPlanDiff,
  createFlintChartPivotPriceLineSpecs,
  calcEMA, calcSMA, calcWMA, calcDEMA, calcHullMA,
  calcBollingerBands, calcKeltnerChannels,
  calcSupertrend, calcParabolicSAR, calcPivotPoints,
  calcVWAP, calcVWMA, calcOBV,
  calcRSI, calcMACD, calcStochastic, calcATR, calcADX,
  calcWilliamsR, calcCCI, calcIchimoku,
  buildLineData, buildHistData,
} from "@flinttrade/design-system";
import {
  lightweightHistogramRuntime,
  lightweightLineRuntime,
} from "@/lib/lightweightChartRuntime";
import type {
  FlintChartIndicatorColor,
  FlintChartIndicatorKey,
  FlintChartIndicatorLineStyle,
  FlintChartIndicatorPaneSize,
  FlintChartIndicatorPaneStretchFactors,
  FlintChartIndicatorHistogramSeriesRenderSpec,
  FlintChartIndicatorLineSeriesRenderSpec,
  FlintChartIndicatorSeriesRenderPlan,
  FlintChartIndicatorSeriesRefKey,
  FlintChartOhlcvBar as OhlcvBar,
} from "@flinttrade/design-system";
import type {
  IndicatorState,
  IndicatorPeriods,
  IndicatorSeriesRefs,
  PivotRefs,
} from "./types";
import { serverIndicatorName, type ServerIndicatorData } from "./useServerIndicators";

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

interface UseIndicatorsOptions {
  chartRef: React.MutableRefObject<IChartApi | null>;
  candleRef: React.MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  volumeRef: React.MutableRefObject<ISeriesApi<"Histogram"> | null>;
  indRef: React.MutableRefObject<IndicatorSeriesRefs>;
  barsRef: React.MutableRefObject<OhlcvBar[]>;
  timesRef: React.MutableRefObject<Time[]>;
  indicators: IndicatorState;
  periods: IndicatorPeriods;
  indicatorColors: Record<FlintChartIndicatorKey, FlintChartIndicatorColor>;
  indicatorLineStyles: Record<FlintChartIndicatorKey, FlintChartIndicatorLineStyle>;
  indicatorPaneSizes: Record<string, FlintChartIndicatorPaneSize>;
  indicatorPaneStretchFactors: FlintChartIndicatorPaneStretchFactors;
  /** Server-computed series keyed by compute-route request name. */
  serverData: ServerIndicatorData;
}

export function useIndicators({
  chartRef,
  candleRef,
  volumeRef,
  indRef,
  barsRef,
  timesRef,
  indicators,
  periods,
  indicatorColors,
  indicatorLineStyles,
  indicatorPaneSizes,
  indicatorPaneStretchFactors,
  serverData,
}: UseIndicatorsOptions) {
  const pivotRef = useRef<PivotRefs>({ lines: [], series: null });
  const previousIndicatorRenderPlanRef = useRef<FlintChartIndicatorSeriesRenderPlan | null>(null);

  const refresh = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const bars = barsRef.current;
    const times = timesRef.current;
    if (bars.length === 0 || times.length === 0) return;

    const closes = bars.map((b) => b.close);
    const highs = bars.map((b) => b.high);
    const lows = bars.map((b) => b.low);
    const ind: IndicatorSeriesRefs = indRef.current;
    const safeChart: IChartApi = chart;
    const indicatorRenderPlan = createFlintChartIndicatorSeriesRenderPlan({
      colors: indicatorColors,
      indicators,
      lineStyles: indicatorLineStyles,
      paneSizes: indicatorPaneSizes,
      paneStretchFactors: indicatorPaneStretchFactors,
      periods,
    });
    const lifecyclePlan = indicatorRenderPlan.lifecyclePlan;
    const paneLayoutPlan = indicatorRenderPlan.paneLayoutPlan;
    const lineSpecByRefKey = new Map(indicatorRenderPlan.lineSeries.map((spec) => [spec.refKey, spec]));
    const histogramSpecByRefKey = new Map(indicatorRenderPlan.histogramSeries.map((spec) => [spec.refKey, spec]));
    const previousIndicatorRenderPlan = previousIndicatorRenderPlanRef.current;
    const indicatorRenderPlanDiff = previousIndicatorRenderPlan
      ? createFlintChartIndicatorSeriesRenderPlanDiff(previousIndicatorRenderPlan, indicatorRenderPlan)
      : null;
    const previousLineSpecByKey = new Map(
      previousIndicatorRenderPlan?.lineSeries.map((spec) => [spec.key, spec]) ?? [],
    );
    const previousHistogramSpecByKey = new Map(
      previousIndicatorRenderPlan?.histogramSeries.map((spec) => [spec.key, spec]) ?? [],
    );
    const paneSpecByScaleId = new Map(
      paneLayoutPlan.panes.map((spec) => [spec.scaleId, spec]),
    );

    function addLineSeries(options: unknown) {
      const paneIndex = paneIndexForOptions(options);
      if (typeof paneIndex === "number") ensureIndicatorPanes();
      return lightweightLineRuntime.addLineSeries(safeChart, options, paneIndex);
    }

    function addHistogramSeries(options: unknown) {
      const paneIndex = paneIndexForOptions(options);
      if (typeof paneIndex === "number") ensureIndicatorPanes();
      return lightweightHistogramRuntime.addHistogramSeries(safeChart, options, paneIndex);
    }

    function removeSeries(s: ISeriesApi<"Line"> | ISeriesApi<"Histogram"> | null) {
      if (!s) return;
      try { safeChart.removeSeries(s); } catch { /* ignore */ }
    }

    function removeIndicatorSeriesRef(refKey: FlintChartIndicatorSeriesRefKey) {
      const series = ind[refKey];
      if (!series) return;
      removeSeries(series);
      ind[refKey] = null;
    }

    function shouldReplaceLineSeries(spec: FlintChartIndicatorLineSeriesRenderSpec) {
      const previousSpec = previousLineSpecByKey.get(spec.key);
      if (!previousSpec) return false;
      return previousSpec.paneIndex !== spec.paneIndex || previousSpec.paneScaleId !== spec.paneScaleId;
    }

    function shouldReplaceHistogramSeries(spec: FlintChartIndicatorHistogramSeriesRenderSpec) {
      const previousSpec = previousHistogramSpecByKey.get(spec.key);
      if (!previousSpec) return false;
      return previousSpec.paneIndex !== spec.paneIndex || previousSpec.paneScaleId !== spec.paneScaleId;
    }

    function applyPaneScale(scaleId: string) {
      const spec = paneSpecByScaleId.get(scaleId);
      if (!spec) return;
      safeChart.priceScale(spec.scaleId, spec.paneIndex).applyOptions(createFlintChartIndicatorPaneOptions(spec));
    }

    function ensureIndicatorPanes() {
      const paneChart = safeChart as IChartApi & {
        addPane?: IChartApi["addPane"];
        panes?: IChartApi["panes"];
      };
      if (typeof paneChart.panes !== "function" || typeof paneChart.addPane !== "function") return;

      let panes = paneChart.panes();
      const maxPaneIndex = Math.max(0, ...paneLayoutPlan.panes.map((pane) => pane.paneIndex));
      while (panes.length <= maxPaneIndex) {
        paneChart.addPane(true);
        panes = paneChart.panes();
      }

      panes[paneLayoutPlan.mainPaneIndex]?.setStretchFactor(paneLayoutPlan.mainPaneStretchFactor);
      for (const paneSpec of paneLayoutPlan.panes) {
        panes[paneSpec.paneIndex]?.setStretchFactor(paneSpec.stretchFactor);
      }
    }

    function paneIndexForOptions(options: unknown): number | undefined {
      if (typeof options !== "object" || options === null) return undefined;
      const priceScaleId = (options as { priceScaleId?: unknown }).priceScaleId;
      if (typeof priceScaleId !== "string") return undefined;
      return paneSpecByScaleId.get(priceScaleId)?.paneIndex;
    }

    function lineOptions(refKey: FlintChartIndicatorSeriesRefKey) {
      return lineSpecByRefKey.get(refKey)?.options;
    }

    function histogramOptions(refKey: FlintChartIndicatorSeriesRefKey) {
      return histogramSpecByRefKey.get(refKey)?.options;
    }

    if (indicatorRenderPlanDiff) {
      for (const spec of indicatorRenderPlanDiff.lineSeries.removed) {
        removeIndicatorSeriesRef(spec.refKey);
      }
      for (const spec of indicatorRenderPlanDiff.histogramSeries.removed) {
        removeIndicatorSeriesRef(spec.refKey);
      }
      for (const spec of indicatorRenderPlanDiff.lineSeries.updated) {
        if (shouldReplaceLineSeries(spec)) removeIndicatorSeriesRef(spec.refKey);
      }
      for (const spec of indicatorRenderPlanDiff.histogramSeries.updated) {
        if (shouldReplaceHistogramSeries(spec)) removeIndicatorSeriesRef(spec.refKey);
      }
    }
    previousIndicatorRenderPlanRef.current = indicatorRenderPlan;

    // --- Overlays ---
    if (indicators.showEMA20) {
      const options = lineOptions("ema20");
      if (!options) return;
      if (!ind.ema20) ind.ema20 = addLineSeries(options);
      ind.ema20.applyOptions(options);
      ind.ema20.setData(buildLineData(times, calcEMA(closes, periods.ema1)));
    } else if (ind.ema20) { removeSeries(ind.ema20); ind.ema20 = null; }

    if (indicators.showEMA50) {
      const options = lineOptions("ema50");
      if (!options) return;
      if (!ind.ema50) ind.ema50 = addLineSeries(options);
      ind.ema50.applyOptions(options);
      ind.ema50.setData(buildLineData(times, calcEMA(closes, periods.ema2)));
    } else if (ind.ema50) { removeSeries(ind.ema50); ind.ema50 = null; }

    if (indicators.showSMA) {
      const options = lineOptions("sma");
      if (!options) return;
      if (!ind.sma) ind.sma = addLineSeries(options);
      ind.sma.applyOptions(options);
      ind.sma.setData(buildLineData(times, calcSMA(closes, periods.sma)));
    } else if (ind.sma) { removeSeries(ind.sma); ind.sma = null; }

    if (indicators.showWMA) {
      const options = lineOptions("wma");
      if (!options) return;
      if (!ind.wma) ind.wma = addLineSeries(options);
      ind.wma.applyOptions(options);
      ind.wma.setData(buildLineData(times, calcWMA(closes, periods.wma)));
    } else if (ind.wma) { removeSeries(ind.wma); ind.wma = null; }

    if (indicators.showBB) {
      const bb = calcBollingerBands(closes, periods.bbPeriod, periods.bbMult);
      const bbUpperOptions = lineOptions("bbUpper");
      const bbMiddleOptions = lineOptions("bbMiddle");
      const bbLowerOptions = lineOptions("bbLower");
      if (!bbUpperOptions || !bbMiddleOptions || !bbLowerOptions) return;
      if (!ind.bbUpper) ind.bbUpper = addLineSeries(bbUpperOptions);
      if (!ind.bbMiddle) ind.bbMiddle = addLineSeries(bbMiddleOptions);
      if (!ind.bbLower) ind.bbLower = addLineSeries(bbLowerOptions);
      ind.bbUpper.setData(buildLineData(times, bb.upper));
      ind.bbMiddle.setData(buildLineData(times, bb.middle));
      ind.bbLower.setData(buildLineData(times, bb.lower));
    } else { for (const key of ["bbUpper", "bbMiddle", "bbLower"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showSupertrend) {
      const st = calcSupertrend(highs, lows, closes, periods.stPeriod, periods.stFactor);
      const stUpOptions = lineOptions("stUp");
      const stDownOptions = lineOptions("stDown");
      if (!stUpOptions || !stDownOptions) return;
      if (!ind.stUp) ind.stUp = addLineSeries(stUpOptions);
      if (!ind.stDown) ind.stDown = addLineSeries(stDownOptions);
      ind.stUp.setData(buildLineData(times, st.up));
      ind.stDown.setData(buildLineData(times, st.down));
    } else { for (const key of ["stUp", "stDown"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showVWAP) {
      const options = lineOptions("vwap");
      if (!options) return;
      if (!ind.vwap) ind.vwap = addLineSeries(options);
      ind.vwap.applyOptions(options);
      ind.vwap.setData(buildLineData(times, calcVWAP(bars, times)));
    } else if (ind.vwap) { removeSeries(ind.vwap); ind.vwap = null; }

    if (indicators.showIchimoku) {
      const ichi = calcIchimoku(highs, lows, closes);
      const ichTenkanOptions = lineOptions("ichTenkan");
      const ichKijunOptions = lineOptions("ichKijun");
      const ichSenkouAOptions = lineOptions("ichSenkouA");
      const ichSenkouBOptions = lineOptions("ichSenkouB");
      const ichChikouOptions = lineOptions("ichChikou");
      if (!ichTenkanOptions || !ichKijunOptions || !ichSenkouAOptions || !ichSenkouBOptions || !ichChikouOptions) return;
      if (!ind.ichTenkan) ind.ichTenkan = addLineSeries(ichTenkanOptions);
      if (!ind.ichKijun) ind.ichKijun = addLineSeries(ichKijunOptions);
      if (!ind.ichSenkouA) ind.ichSenkouA = addLineSeries(ichSenkouAOptions);
      if (!ind.ichSenkouB) ind.ichSenkouB = addLineSeries(ichSenkouBOptions);
      if (!ind.ichChikou) ind.ichChikou = addLineSeries(ichChikouOptions);
      ind.ichTenkan.setData(buildLineData(times, ichi.tenkan));
      ind.ichKijun.setData(buildLineData(times, ichi.kijun));
      ind.ichSenkouA.setData(buildLineData(times, ichi.senkouA));
      ind.ichSenkouB.setData(buildLineData(times, ichi.senkouB));
      const chikouValues: (number | null)[] = new Array(closes.length).fill(null);
      for (let i = 26; i < closes.length; i++) chikouValues[i - 26] = closes[i];
      ind.ichChikou.setData(buildLineData(times, chikouValues));
    } else { for (const key of ["ichTenkan", "ichKijun", "ichSenkouA", "ichSenkouB", "ichChikou"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showPivot) {
      const pivots = calcPivotPoints(bars);
      if (pivotRef.current.series && pivotRef.current.lines.length > 0) {
        for (const pl of pivotRef.current.lines) { try { pivotRef.current.series.removePriceLine(pl); } catch { /* ignore */ } }
        pivotRef.current.lines = [];
      }
      const candle = candleRef.current;
      if (pivots && candle) {
        pivotRef.current.series = candle;
        for (const spec of createFlintChartPivotPriceLineSpecs(pivots)) {
          try { const pl = candle.createPriceLine(spec); pivotRef.current.lines.push(pl); } catch { /* ignore */ }
        }
      }
    } else {
      if (pivotRef.current.series && pivotRef.current.lines.length > 0) {
        for (const pl of pivotRef.current.lines) { try { pivotRef.current.series.removePriceLine(pl); } catch { /* ignore */ } }
        pivotRef.current.lines = []; pivotRef.current.series = null;
      }
    }

    if (volumeRef.current) volumeRef.current.applyOptions({ visible: lifecyclePlan.volumeVisible });

    // --- Oscillators ---
    if (indicators.showRSI) {
      const options = lineOptions("rsi");
      if (!options) return;
      if (!ind.rsi) { ind.rsi = addLineSeries(options); applyPaneScale("rsi"); }
      ind.rsi.applyOptions(options);
      ind.rsi.setData(buildLineData(times, calcRSI(closes, periods.rsi).values));
    } else if (ind.rsi) { removeSeries(ind.rsi); ind.rsi = null; }

    if (indicators.showMACD) {
      const macdData = calcMACD(closes);
      const macdHistOptions = histogramOptions("macdHist");
      const macdLineOptions = lineOptions("macdLine");
      const macdSignalOptions = lineOptions("macdSignal");
      if (!macdHistOptions || !macdLineOptions || !macdSignalOptions) return;
      if (!ind.macdHist) { ind.macdHist = addHistogramSeries(macdHistOptions); applyPaneScale("macd"); }
      if (!ind.macdLine) ind.macdLine = addLineSeries(macdLineOptions);
      if (!ind.macdSignal) ind.macdSignal = addLineSeries(macdSignalOptions);
      ind.macdHist.setData(buildHistData(times, macdData.hist));
      ind.macdLine.setData(buildLineData(times, macdData.macd));
      ind.macdSignal.setData(buildLineData(times, macdData.signal));
    } else { for (const key of ["macdHist", "macdLine", "macdSignal"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showStoch) {
      const stoch = calcStochastic(highs, lows, closes);
      const stochKOptions = lineOptions("stochK");
      const stochDOptions = lineOptions("stochD");
      if (!stochKOptions || !stochDOptions) return;
      if (!ind.stochK) { ind.stochK = addLineSeries(stochKOptions); applyPaneScale("stoch"); }
      if (!ind.stochD) ind.stochD = addLineSeries(stochDOptions);
      ind.stochK.setData(buildLineData(times, stoch.k));
      ind.stochD.setData(buildLineData(times, stoch.d));
    } else { for (const key of ["stochK", "stochD"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showATR) {
      const options = lineOptions("atr");
      if (!options) return;
      if (!ind.atr) { ind.atr = addLineSeries(options); applyPaneScale("atr"); }
      ind.atr.applyOptions(options);
      ind.atr.setData(buildLineData(times, calcATR(highs, lows, closes, periods.atr).values));
    } else if (ind.atr) { removeSeries(ind.atr); ind.atr = null; }

    if (indicators.showADX) {
      const adxData = calcADX(highs, lows, closes, periods.adx);
      const adxOptions = lineOptions("adx");
      const adxPlusOptions = lineOptions("adxPlus");
      const adxMinusOptions = lineOptions("adxMinus");
      if (!adxOptions || !adxPlusOptions || !adxMinusOptions) return;
      if (!ind.adx) { ind.adx = addLineSeries(adxOptions); applyPaneScale("adx"); }
      if (!ind.adxPlus) ind.adxPlus = addLineSeries(adxPlusOptions);
      if (!ind.adxMinus) ind.adxMinus = addLineSeries(adxMinusOptions);
      ind.adx.setData(buildLineData(times, adxData.adx));
      ind.adxPlus.setData(buildLineData(times, adxData.plusDI));
      ind.adxMinus.setData(buildLineData(times, adxData.minusDI));
    } else { for (const key of ["adx", "adxPlus", "adxMinus"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showWilliamsR) {
      const options = lineOptions("williamsR");
      if (!options) return;
      if (!ind.williamsR) { ind.williamsR = addLineSeries(options); applyPaneScale("wr"); }
      ind.williamsR.applyOptions(options);
      ind.williamsR.setData(buildLineData(times, calcWilliamsR(highs, lows, closes, periods.wr)));
    } else if (ind.williamsR) { removeSeries(ind.williamsR); ind.williamsR = null; }

    if (indicators.showCCI) {
      const options = lineOptions("cci");
      if (!options) return;
      if (!ind.cci) { ind.cci = addLineSeries(options); applyPaneScale("cci"); }
      ind.cci.applyOptions(options);
      ind.cci.setData(buildLineData(times, calcCCI(highs, lows, closes, periods.cci)));
    } else if (ind.cci) { removeSeries(ind.cci); ind.cci = null; }

    if (indicators.showDEMA) {
      const options = lineOptions("dema");
      if (!options) return;
      if (!ind.dema) ind.dema = addLineSeries(options);
      ind.dema.applyOptions(options);
      ind.dema.setData(buildLineData(times, calcDEMA(closes, periods.dema)));
    } else if (ind.dema) { removeSeries(ind.dema); ind.dema = null; }

    if (indicators.showHullMA) {
      const options = lineOptions("hullMA");
      if (!options) return;
      if (!ind.hullMA) ind.hullMA = addLineSeries(options);
      ind.hullMA.applyOptions(options);
      ind.hullMA.setData(buildLineData(times, calcHullMA(closes, periods.hull)));
    } else if (ind.hullMA) { removeSeries(ind.hullMA); ind.hullMA = null; }

    if (indicators.showParabolicSAR) {
      const options = lineOptions("parSar");
      if (!options) return;
      if (!ind.parSar) ind.parSar = addLineSeries(options);
      ind.parSar.setData(buildLineData(times, calcParabolicSAR(highs, lows)));
    } else if (ind.parSar) { removeSeries(ind.parSar); ind.parSar = null; }

    if (indicators.showOBV) {
      const vols = bars.map((b) => b.volume ?? 0);
      const options = lineOptions("obv");
      if (!options) return;
      if (!ind.obv) { ind.obv = addLineSeries(options); applyPaneScale("obv"); }
      ind.obv.applyOptions(options);
      ind.obv.setData(buildLineData(times, calcOBV(closes, vols)));
    } else if (ind.obv) { removeSeries(ind.obv); ind.obv = null; }

    if (indicators.showKeltner) {
      const kc = calcKeltnerChannels(bars, periods.keltner, periods.keltnerMult);
      const keltnerUpperOptions = lineOptions("keltnerUpper");
      const keltnerMiddleOptions = lineOptions("keltnerMiddle");
      const keltnerLowerOptions = lineOptions("keltnerLower");
      if (!keltnerUpperOptions || !keltnerMiddleOptions || !keltnerLowerOptions) return;
      if (!ind.keltnerUpper) ind.keltnerUpper = addLineSeries(keltnerUpperOptions);
      if (!ind.keltnerMiddle) ind.keltnerMiddle = addLineSeries(keltnerMiddleOptions);
      if (!ind.keltnerLower) ind.keltnerLower = addLineSeries(keltnerLowerOptions);
      ind.keltnerUpper.setData(buildLineData(times, kc.upper));
      ind.keltnerMiddle.setData(buildLineData(times, kc.middle));
      ind.keltnerLower.setData(buildLineData(times, kc.lower));
    } else { for (const key of ["keltnerUpper", "keltnerMiddle", "keltnerLower"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showVWMA) {
      const options = lineOptions("vwma");
      if (!options) return;
      if (!ind.vwma) ind.vwma = addLineSeries(options);
      ind.vwma.applyOptions(options);
      ind.vwma.setData(buildLineData(times, calcVWMA(bars, periods.vwma)));
    } else if (ind.vwma) { removeSeries(ind.vwma); ind.vwma = null; }

    // --- Server-computed tier (data via useServerIndicators) ---
    // A missing entry means the fetch has not landed yet: keep whatever the
    // series already shows rather than clearing it, so a slow backend never
    // blanks an indicator mid-session.
    const serverLine = (name: string): (number | null)[] | null => {
      const entry = serverData[name];
      return Array.isArray(entry) ? entry : null;
    };
    const serverDict = (name: string): Record<string, (number | null)[] | boolean[]> | null => {
      const entry = serverData[name];
      return entry && !Array.isArray(entry) && !("error" in entry)
        ? (entry as Record<string, (number | null)[] | boolean[]>)
        : null;
    };
    const numeric = (values: (number | null)[] | boolean[] | undefined): (number | null)[] =>
      (values ?? []).map((v) => (typeof v === "number" ? v : null));

    if (indicators.showKAMA) {
      const values = serverLine(serverIndicatorName("showKAMA", periods));
      const options = lineOptions("kama");
      if (!options) return;
      if (!ind.kama) ind.kama = addLineSeries(options);
      ind.kama.applyOptions(options);
      if (values) ind.kama.setData(buildLineData(times, values));
    } else if (ind.kama) { removeSeries(ind.kama); ind.kama = null; }

    if (indicators.showALMA) {
      const values = serverLine(serverIndicatorName("showALMA", periods));
      const options = lineOptions("alma");
      if (!options) return;
      if (!ind.alma) ind.alma = addLineSeries(options);
      ind.alma.applyOptions(options);
      if (values) ind.alma.setData(buildLineData(times, values));
    } else if (ind.alma) { removeSeries(ind.alma); ind.alma = null; }

    if (indicators.showDonchian) {
      const dc = serverDict(serverIndicatorName("showDonchian", periods));
      const upperOptions = lineOptions("donUpper");
      const middleOptions = lineOptions("donMiddle");
      const lowerOptions = lineOptions("donLower");
      if (!upperOptions || !middleOptions || !lowerOptions) return;
      if (!ind.donUpper) ind.donUpper = addLineSeries(upperOptions);
      if (!ind.donMiddle) ind.donMiddle = addLineSeries(middleOptions);
      if (!ind.donLower) ind.donLower = addLineSeries(lowerOptions);
      if (dc) {
        ind.donUpper.setData(buildLineData(times, numeric(dc.upper)));
        ind.donMiddle.setData(buildLineData(times, numeric(dc.middle)));
        ind.donLower.setData(buildLineData(times, numeric(dc.lower)));
      }
    } else { for (const key of ["donUpper", "donMiddle", "donLower"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showChandelier) {
      const ce = serverDict(serverIndicatorName("showChandelier", periods));
      const longOptions = lineOptions("chandLong");
      const shortOptions = lineOptions("chandShort");
      if (!longOptions || !shortOptions) return;
      if (!ind.chandLong) ind.chandLong = addLineSeries(longOptions);
      if (!ind.chandShort) ind.chandShort = addLineSeries(shortOptions);
      if (ce) {
        ind.chandLong.setData(buildLineData(times, numeric(ce.long)));
        ind.chandShort.setData(buildLineData(times, numeric(ce.short)));
      }
    } else { for (const key of ["chandLong", "chandShort"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showStochRSI) {
      const sr = serverDict(serverIndicatorName("showStochRSI", periods));
      const kOptions = lineOptions("stochRsiK");
      const dOptions = lineOptions("stochRsiD");
      if (!kOptions || !dOptions) return;
      if (!ind.stochRsiK) { ind.stochRsiK = addLineSeries(kOptions); applyPaneScale("stochrsi"); }
      if (!ind.stochRsiD) ind.stochRsiD = addLineSeries(dOptions);
      if (sr) {
        ind.stochRsiK.setData(buildLineData(times, numeric(sr.k)));
        ind.stochRsiD.setData(buildLineData(times, numeric(sr.d)));
      }
    } else { for (const key of ["stochRsiK", "stochRsiD"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showMFI) {
      const values = serverLine(serverIndicatorName("showMFI", periods));
      const options = lineOptions("mfi");
      if (!options) return;
      if (!ind.mfi) { ind.mfi = addLineSeries(options); applyPaneScale("mfi"); }
      ind.mfi.applyOptions(options);
      if (values) ind.mfi.setData(buildLineData(times, values));
    } else if (ind.mfi) { removeSeries(ind.mfi); ind.mfi = null; }

    if (indicators.showSqueeze) {
      const sq = serverDict(serverIndicatorName("showSqueeze", periods));
      const options = histogramOptions("squeezeHist");
      if (!options) return;
      if (!ind.squeezeHist) { ind.squeezeHist = addHistogramSeries(options); applyPaneScale("squeeze"); }
      if (sq) ind.squeezeHist.setData(buildHistData(times, numeric(sq.momentum)));
    } else if (ind.squeezeHist) { removeSeries(ind.squeezeHist); ind.squeezeHist = null; }

    if (indicators.showAO) {
      const values = serverLine(serverIndicatorName("showAO", periods));
      const options = histogramOptions("aoHist");
      if (!options) return;
      if (!ind.aoHist) { ind.aoHist = addHistogramSeries(options); applyPaneScale("ao"); }
      if (values) ind.aoHist.setData(buildHistData(times, values));
    } else if (ind.aoHist) { removeSeries(ind.aoHist); ind.aoHist = null; }
  }, [
    indicatorColors,
    indicatorLineStyles,
    indicatorPaneSizes,
    indicatorPaneStretchFactors,
    indicators,
    periods,
    serverData,
    chartRef,
    candleRef,
    volumeRef,
    indRef,
    barsRef,
    timesRef,
  ]);

  useEffect(() => { refresh(); }, [refresh]);

  return { pivotRef, refresh };
}

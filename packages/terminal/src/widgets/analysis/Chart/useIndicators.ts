// Indicator series lifecycle hook.
// Manages adding / updating / removing indicator series on the chart
// whenever indicator toggles or periods change.

import { useEffect, useCallback, useRef } from "react";
import { LineSeries, HistogramSeries } from "lightweight-charts";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import {
  calcEMA, calcSMA, calcWMA, calcDEMA, calcHullMA,
  calcBollingerBands, calcKeltnerChannels,
  calcSupertrend, calcParabolicSAR, calcPivotPoints,
  calcVWAP, calcVWMA, calcOBV,
  calcRSI, calcMACD, calcStochastic, calcATR, calcADX,
  calcWilliamsR, calcCCI, calcIchimoku,
  buildLineData, buildHistData,
} from "./indicators";
import type { OhlcvBar } from "./indicators";
import type {
  IndicatorState,
  IndicatorPeriods,
  IndicatorSeriesRefs,
  PivotRefs,
} from "./types";

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
}: UseIndicatorsOptions) {
  const pivotRef = useRef<PivotRefs>({ lines: [], series: null });

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

    function removeSeries(s: ISeriesApi<"Line"> | ISeriesApi<"Histogram"> | null) {
      if (!s) return;
      try { safeChart.removeSeries(s); } catch { /* ignore */ }
    }

    // --- Overlays ---
    if (indicators.showEMA20) {
      if (!ind.ema20) ind.ema20 = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, priceScaleId: "right", title: `EMA${periods.ema1}`, lastValueVisible: false, priceLineVisible: false });
      ind.ema20.applyOptions({ title: `EMA${periods.ema1}` });
      ind.ema20.setData(buildLineData(times, calcEMA(closes, periods.ema1)));
    } else if (ind.ema20) { removeSeries(ind.ema20); ind.ema20 = null; }

    if (indicators.showEMA50) {
      if (!ind.ema50) ind.ema50 = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, priceScaleId: "right", title: `EMA${periods.ema2}`, lastValueVisible: false, priceLineVisible: false });
      ind.ema50.applyOptions({ title: `EMA${periods.ema2}` });
      ind.ema50.setData(buildLineData(times, calcEMA(closes, periods.ema2)));
    } else if (ind.ema50) { removeSeries(ind.ema50); ind.ema50 = null; }

    if (indicators.showSMA) {
      if (!ind.sma) ind.sma = chart.addSeries(LineSeries, { color: "#06b6d4", lineWidth: 1, priceScaleId: "right", title: `SMA${periods.sma}`, lastValueVisible: false, priceLineVisible: false });
      ind.sma.applyOptions({ title: `SMA${periods.sma}` });
      ind.sma.setData(buildLineData(times, calcSMA(closes, periods.sma)));
    } else if (ind.sma) { removeSeries(ind.sma); ind.sma = null; }

    if (indicators.showWMA) {
      if (!ind.wma) ind.wma = chart.addSeries(LineSeries, { color: "#84cc16", lineWidth: 1, priceScaleId: "right", title: `WMA${periods.wma}`, lastValueVisible: false, priceLineVisible: false });
      ind.wma.applyOptions({ title: `WMA${periods.wma}` });
      ind.wma.setData(buildLineData(times, calcWMA(closes, periods.wma)));
    } else if (ind.wma) { removeSeries(ind.wma); ind.wma = null; }

    if (indicators.showBB) {
      const bb = calcBollingerBands(closes, periods.bbPeriod, periods.bbMult);
      if (!ind.bbUpper) ind.bbUpper = chart.addSeries(LineSeries, { color: "#ef4444", lineWidth: 1, lineStyle: 2, priceScaleId: "right", title: "BB Upper", lastValueVisible: false, priceLineVisible: false });
      if (!ind.bbMiddle) ind.bbMiddle = chart.addSeries(LineSeries, { color: "#94a3b8", lineWidth: 1, lineStyle: 1, priceScaleId: "right", title: "BB Mid", lastValueVisible: false, priceLineVisible: false });
      if (!ind.bbLower) ind.bbLower = chart.addSeries(LineSeries, { color: "#22c55e", lineWidth: 1, lineStyle: 2, priceScaleId: "right", title: "BB Lower", lastValueVisible: false, priceLineVisible: false });
      ind.bbUpper.setData(buildLineData(times, bb.upper));
      ind.bbMiddle.setData(buildLineData(times, bb.middle));
      ind.bbLower.setData(buildLineData(times, bb.lower));
    } else { for (const key of ["bbUpper", "bbMiddle", "bbLower"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showSupertrend) {
      const st = calcSupertrend(highs, lows, closes, periods.stPeriod, periods.stFactor);
      if (!ind.stUp) ind.stUp = chart.addSeries(LineSeries, { color: "#22c55e", lineWidth: 2, priceScaleId: "right", title: "ST Up", lastValueVisible: false, priceLineVisible: false });
      if (!ind.stDown) ind.stDown = chart.addSeries(LineSeries, { color: "#ef4444", lineWidth: 2, priceScaleId: "right", title: "ST Down", lastValueVisible: false, priceLineVisible: false });
      ind.stUp.setData(buildLineData(times, st.up));
      ind.stDown.setData(buildLineData(times, st.down));
    } else { for (const key of ["stUp", "stDown"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showVWAP) {
      if (!ind.vwap) ind.vwap = chart.addSeries(LineSeries, { color: "#e879f9", lineWidth: 1, priceScaleId: "right", title: "VWAP", lastValueVisible: true, priceLineVisible: false });
      ind.vwap.setData(buildLineData(times, calcVWAP(bars, times)));
    } else if (ind.vwap) { removeSeries(ind.vwap); ind.vwap = null; }

    if (indicators.showIchimoku) {
      const ichi = calcIchimoku(highs, lows, closes);
      if (!ind.ichTenkan) ind.ichTenkan = chart.addSeries(LineSeries, { color: "#ef4444", lineWidth: 1, priceScaleId: "right", title: "Tenkan", lastValueVisible: false, priceLineVisible: false });
      if (!ind.ichKijun) ind.ichKijun = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, priceScaleId: "right", title: "Kijun", lastValueVisible: false, priceLineVisible: false });
      if (!ind.ichSenkouA) ind.ichSenkouA = chart.addSeries(LineSeries, { color: "rgba(34,197,94,0.5)", lineWidth: 1, priceScaleId: "right", title: "Senkou A", lastValueVisible: false, priceLineVisible: false });
      if (!ind.ichSenkouB) ind.ichSenkouB = chart.addSeries(LineSeries, { color: "rgba(239,68,68,0.5)", lineWidth: 1, priceScaleId: "right", title: "Senkou B", lastValueVisible: false, priceLineVisible: false });
      if (!ind.ichChikou) ind.ichChikou = chart.addSeries(LineSeries, { color: "#a855f7", lineWidth: 1, lineStyle: 2, priceScaleId: "right", title: "Chikou", lastValueVisible: false, priceLineVisible: false });
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
        const pivotLevels: [number, string, string][] = [
          [pivots.pp, "#94a3b8", "PP"], [pivots.r1, "#ef4444", "R1"], [pivots.r2, "#f97316", "R2"],
          [pivots.r3, "#dc2626", "R3"], [pivots.s1, "#22c55e", "S1"], [pivots.s2, "#16a34a", "S2"], [pivots.s3, "#15803d", "S3"],
        ];
        for (const [price, color, title] of pivotLevels) {
          try { const pl = candle.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }); pivotRef.current.lines.push(pl); } catch { /* ignore */ }
        }
      }
    } else {
      if (pivotRef.current.series && pivotRef.current.lines.length > 0) {
        for (const pl of pivotRef.current.lines) { try { pivotRef.current.series.removePriceLine(pl); } catch { /* ignore */ } }
        pivotRef.current.lines = []; pivotRef.current.series = null;
      }
    }

    if (volumeRef.current) volumeRef.current.applyOptions({ visible: indicators.showVolume });

    // --- Oscillators ---
    if (indicators.showRSI) {
      if (!ind.rsi) { ind.rsi = chart.addSeries(LineSeries, { color: "#a855f7", lineWidth: 1, priceScaleId: "rsi", title: `RSI(${periods.rsi})`, lastValueVisible: true, priceLineVisible: false }); chart.priceScale("rsi").applyOptions({ scaleMargins: { top: 0.75, bottom: 0.05 } }); }
      ind.rsi.applyOptions({ title: `RSI(${periods.rsi})` });
      ind.rsi.setData(buildLineData(times, calcRSI(closes, periods.rsi).values));
    } else if (ind.rsi) { removeSeries(ind.rsi); ind.rsi = null; }

    if (indicators.showMACD) {
      const macdData = calcMACD(closes);
      if (!ind.macdHist) { ind.macdHist = chart.addSeries(HistogramSeries, { priceScaleId: "macd", title: "MACD Hist", lastValueVisible: false, priceLineVisible: false }); chart.priceScale("macd").applyOptions({ scaleMargins: { top: 0.6, bottom: 0.05 } }); }
      if (!ind.macdLine) ind.macdLine = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, priceScaleId: "macd", title: "MACD", lastValueVisible: false, priceLineVisible: false });
      if (!ind.macdSignal) ind.macdSignal = chart.addSeries(LineSeries, { color: "#f97316", lineWidth: 1, priceScaleId: "macd", title: "Signal", lastValueVisible: false, priceLineVisible: false });
      ind.macdHist.setData(buildHistData(times, macdData.hist));
      ind.macdLine.setData(buildLineData(times, macdData.macd));
      ind.macdSignal.setData(buildLineData(times, macdData.signal));
    } else { for (const key of ["macdHist", "macdLine", "macdSignal"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showStoch) {
      const stoch = calcStochastic(highs, lows, closes);
      if (!ind.stochK) { ind.stochK = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, priceScaleId: "stoch", title: "%K", lastValueVisible: false, priceLineVisible: false }); chart.priceScale("stoch").applyOptions({ scaleMargins: { top: 0.65, bottom: 0.05 } }); }
      if (!ind.stochD) ind.stochD = chart.addSeries(LineSeries, { color: "#f97316", lineWidth: 1, priceScaleId: "stoch", title: "%D", lastValueVisible: false, priceLineVisible: false });
      ind.stochK.setData(buildLineData(times, stoch.k));
      ind.stochD.setData(buildLineData(times, stoch.d));
    } else { for (const key of ["stochK", "stochD"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showATR) {
      if (!ind.atr) { ind.atr = chart.addSeries(LineSeries, { color: "#fb923c", lineWidth: 1, priceScaleId: "atr", title: `ATR(${periods.atr})`, lastValueVisible: true, priceLineVisible: false }); chart.priceScale("atr").applyOptions({ scaleMargins: { top: 0.7, bottom: 0.05 } }); }
      ind.atr.applyOptions({ title: `ATR(${periods.atr})` });
      ind.atr.setData(buildLineData(times, calcATR(highs, lows, closes, periods.atr).values));
    } else if (ind.atr) { removeSeries(ind.atr); ind.atr = null; }

    if (indicators.showADX) {
      const adxData = calcADX(highs, lows, closes, periods.adx);
      if (!ind.adx) { ind.adx = chart.addSeries(LineSeries, { color: "#fbbf24", lineWidth: 1, priceScaleId: "adx", title: "ADX", lastValueVisible: true, priceLineVisible: false }); chart.priceScale("adx").applyOptions({ scaleMargins: { top: 0.65, bottom: 0.05 } }); }
      if (!ind.adxPlus) ind.adxPlus = chart.addSeries(LineSeries, { color: "#22c55e", lineWidth: 1, priceScaleId: "adx", title: "+DI", lastValueVisible: false, priceLineVisible: false });
      if (!ind.adxMinus) ind.adxMinus = chart.addSeries(LineSeries, { color: "#ef4444", lineWidth: 1, priceScaleId: "adx", title: "-DI", lastValueVisible: false, priceLineVisible: false });
      ind.adx.setData(buildLineData(times, adxData.adx));
      ind.adxPlus.setData(buildLineData(times, adxData.plusDI));
      ind.adxMinus.setData(buildLineData(times, adxData.minusDI));
    } else { for (const key of ["adx", "adxPlus", "adxMinus"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showWilliamsR) {
      if (!ind.williamsR) { ind.williamsR = chart.addSeries(LineSeries, { color: "#f472b6", lineWidth: 1, priceScaleId: "wr", title: `W%R(${periods.wr})`, lastValueVisible: true, priceLineVisible: false }); chart.priceScale("wr").applyOptions({ scaleMargins: { top: 0.7, bottom: 0.05 } }); }
      ind.williamsR.applyOptions({ title: `W%R(${periods.wr})` });
      ind.williamsR.setData(buildLineData(times, calcWilliamsR(highs, lows, closes, periods.wr)));
    } else if (ind.williamsR) { removeSeries(ind.williamsR); ind.williamsR = null; }

    if (indicators.showCCI) {
      if (!ind.cci) { ind.cci = chart.addSeries(LineSeries, { color: "#38bdf8", lineWidth: 1, priceScaleId: "cci", title: `CCI(${periods.cci})`, lastValueVisible: true, priceLineVisible: false }); chart.priceScale("cci").applyOptions({ scaleMargins: { top: 0.7, bottom: 0.05 } }); }
      ind.cci.applyOptions({ title: `CCI(${periods.cci})` });
      ind.cci.setData(buildLineData(times, calcCCI(highs, lows, closes, periods.cci)));
    } else if (ind.cci) { removeSeries(ind.cci); ind.cci = null; }

    if (indicators.showDEMA) {
      if (!ind.dema) ind.dema = chart.addSeries(LineSeries, { color: "#f97316", lineWidth: 1, priceScaleId: "right", title: `DEMA${periods.dema}`, lastValueVisible: false, priceLineVisible: false });
      ind.dema.applyOptions({ title: `DEMA${periods.dema}` });
      ind.dema.setData(buildLineData(times, calcDEMA(closes, periods.dema)));
    } else if (ind.dema) { removeSeries(ind.dema); ind.dema = null; }

    if (indicators.showHullMA) {
      if (!ind.hullMA) ind.hullMA = chart.addSeries(LineSeries, { color: "#a855f7", lineWidth: 1, priceScaleId: "right", title: `HMA${periods.hull}`, lastValueVisible: false, priceLineVisible: false });
      ind.hullMA.applyOptions({ title: `HMA${periods.hull}` });
      ind.hullMA.setData(buildLineData(times, calcHullMA(closes, periods.hull)));
    } else if (ind.hullMA) { removeSeries(ind.hullMA); ind.hullMA = null; }

    if (indicators.showParabolicSAR) {
      if (!ind.parSar) ind.parSar = chart.addSeries(LineSeries, { color: "#facc15", lineWidth: 1, priceScaleId: "right", title: "SAR", lastValueVisible: false, priceLineVisible: false, pointMarkersVisible: true });
      ind.parSar.setData(buildLineData(times, calcParabolicSAR(highs, lows)));
    } else if (ind.parSar) { removeSeries(ind.parSar); ind.parSar = null; }

    if (indicators.showOBV) {
      const vols = bars.map((b) => b.volume ?? 0);
      if (!ind.obv) { ind.obv = chart.addSeries(LineSeries, { color: "#94a3b8", lineWidth: 1, priceScaleId: "obv", title: "OBV", lastValueVisible: true, priceLineVisible: false }); chart.priceScale("obv").applyOptions({ scaleMargins: { top: 0.7, bottom: 0.05 } }); }
      ind.obv.setData(buildLineData(times, calcOBV(closes, vols)));
    } else if (ind.obv) { removeSeries(ind.obv); ind.obv = null; }

    if (indicators.showKeltner) {
      const kc = calcKeltnerChannels(bars, periods.keltner, periods.keltnerMult);
      if (!ind.keltnerUpper) ind.keltnerUpper = chart.addSeries(LineSeries, { color: "rgba(249,115,22,0.4)", lineWidth: 1, lineStyle: 2, priceScaleId: "right", title: "KC Upper", lastValueVisible: false, priceLineVisible: false });
      if (!ind.keltnerMiddle) ind.keltnerMiddle = chart.addSeries(LineSeries, { color: "#f97316", lineWidth: 1, priceScaleId: "right", title: "KC Mid", lastValueVisible: false, priceLineVisible: false });
      if (!ind.keltnerLower) ind.keltnerLower = chart.addSeries(LineSeries, { color: "rgba(249,115,22,0.4)", lineWidth: 1, lineStyle: 2, priceScaleId: "right", title: "KC Lower", lastValueVisible: false, priceLineVisible: false });
      ind.keltnerUpper.setData(buildLineData(times, kc.upper));
      ind.keltnerMiddle.setData(buildLineData(times, kc.middle));
      ind.keltnerLower.setData(buildLineData(times, kc.lower));
    } else { for (const key of ["keltnerUpper", "keltnerMiddle", "keltnerLower"] as const) { if (ind[key]) { removeSeries(ind[key]!); ind[key] = null; } } }

    if (indicators.showVWMA) {
      if (!ind.vwma) ind.vwma = chart.addSeries(LineSeries, { color: "#2dd4bf", lineWidth: 1, priceScaleId: "right", title: `VWMA${periods.vwma}`, lastValueVisible: false, priceLineVisible: false });
      ind.vwma.applyOptions({ title: `VWMA${periods.vwma}` });
      ind.vwma.setData(buildLineData(times, calcVWMA(bars, periods.vwma)));
    } else if (ind.vwma) { removeSeries(ind.vwma); ind.vwma = null; }
  }, [indicators, periods, chartRef, candleRef, volumeRef, indRef, barsRef, timesRef]);

  useEffect(() => { refresh(); }, [refresh]);

  return { pivotRef };
}

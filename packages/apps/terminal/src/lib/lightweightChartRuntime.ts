import {
  createChart,
  AreaSeries,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createSeriesMarkers,
} from "lightweight-charts";
import type {
  AreaSeriesPartialOptions,
  CandlestickSeriesPartialOptions,
  ChartOptions,
  DeepPartial,
  HistogramSeriesPartialOptions,
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineSeriesPartialOptions,
  SeriesMarker,
  Time,
} from "lightweight-charts";
import type {
  FlintAreaChartRuntime,
  FlintCandlestickChartRuntime,
  FlintChartShellRuntime,
  FlintHistogramChartRuntime,
  FlintLineChartRuntime,
} from "@flinttrade/design-system";

export const lightweightChartShellRuntime: FlintChartShellRuntime<IChartApi> = {
  createChart: (container, options) =>
    createChart(container, options as DeepPartial<ChartOptions>),
};

export const lightweightCandlestickRuntime: FlintCandlestickChartRuntime<
  IChartApi,
  ISeriesApi<"Candlestick">,
  ISeriesApi<"Histogram">,
  ISeriesMarkersPluginApi<Time>
> = {
  createChart: lightweightChartShellRuntime.createChart,
  addCandlestickSeries: (chart, options, paneIndex) =>
    chart.addSeries(
      CandlestickSeries,
      options as CandlestickSeriesPartialOptions,
      paneIndex,
    ),
  addHistogramSeries: (chart, options, paneIndex) =>
    chart.addSeries(
      HistogramSeries,
      options as HistogramSeriesPartialOptions,
      paneIndex,
    ),
  createSeriesMarkers: (series, markers) =>
    createSeriesMarkers(series, markers as SeriesMarker<Time>[]),
};

export const lightweightLineRuntime: FlintLineChartRuntime<
  IChartApi,
  ISeriesApi<"Line">
> = {
  createChart: lightweightChartShellRuntime.createChart,
  addLineSeries: (chart, options, paneIndex) =>
    chart.addSeries(LineSeries, options as LineSeriesPartialOptions, paneIndex),
};

export const lightweightAreaRuntime: FlintAreaChartRuntime<
  IChartApi,
  ISeriesApi<"Area">
> = {
  createChart: lightweightChartShellRuntime.createChart,
  addAreaSeries: (chart, options, paneIndex) =>
    chart.addSeries(AreaSeries, options as AreaSeriesPartialOptions, paneIndex),
};

export const lightweightHistogramRuntime: FlintHistogramChartRuntime<
  IChartApi,
  ISeriesApi<"Histogram">
> = {
  createChart: lightweightChartShellRuntime.createChart,
  addHistogramSeries: (chart, options, paneIndex) =>
    chart.addSeries(HistogramSeries, options as HistogramSeriesPartialOptions, paneIndex),
};

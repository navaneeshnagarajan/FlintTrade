import type { FlintLightweightChartTheme } from "./theme"

export interface FlintRuntimeChartLike {
  applyOptions(options: unknown): void
  priceScale(id: string): { applyOptions(options: unknown): void }
  remove(): void
  resize?(width: number, height: number): void
}

export interface FlintRuntimeSeriesLike {
  applyOptions(options: unknown): void
}

export interface FlintChartShellRuntime<TChart extends FlintRuntimeChartLike> {
  createChart(container: HTMLElement, options: unknown): TChart
}

export interface FlintCandlestickChartRuntime<
  TChart extends FlintRuntimeChartLike,
  TCandle extends FlintRuntimeSeriesLike,
  TVolume extends FlintRuntimeSeriesLike,
  TMarkers = unknown,
> extends FlintChartShellRuntime<TChart> {
  addCandlestickSeries(chart: TChart, options: unknown, paneIndex?: number): TCandle
  addHistogramSeries(chart: TChart, options: unknown, paneIndex?: number): TVolume
  createSeriesMarkers?: (series: TCandle, markers: readonly unknown[]) => TMarkers
}

export interface FlintLineChartRuntime<
  TChart extends FlintRuntimeChartLike,
  TLine extends FlintRuntimeSeriesLike,
> extends FlintChartShellRuntime<TChart> {
  addLineSeries(chart: TChart, options: unknown, paneIndex?: number): TLine
}

export interface FlintAreaChartRuntime<
  TChart extends FlintRuntimeChartLike,
  TArea extends FlintRuntimeSeriesLike,
> extends FlintChartShellRuntime<TChart> {
  addAreaSeries(chart: TChart, options: unknown, paneIndex?: number): TArea
}

export interface FlintHistogramChartRuntime<
  TChart extends FlintRuntimeChartLike,
  THistogram extends FlintRuntimeSeriesLike,
> extends FlintChartShellRuntime<TChart> {
  addHistogramSeries(chart: TChart, options: unknown, paneIndex?: number): THistogram
}

export interface FlintChartOverrides {
  layout?: Record<string, unknown>
  grid?: Record<string, unknown>
  crosshair?: Record<string, unknown>
  rightPriceScale?: Record<string, unknown>
  timeScale?: Record<string, unknown>
  handleScale?: Record<string, unknown> | boolean
  handleScroll?: Record<string, unknown> | boolean
  kineticScroll?: Record<string, unknown>
  trackingMode?: Record<string, unknown>
}

export interface FlintChartShellOptions extends FlintChartOverrides {
  width?: number
  height?: number
  ariaLabel?: string
  resize?: "observer" | "none"
}

export interface FlintChartDisplaySettings {
  version: 1
  gridVisible: boolean
  crosshairVisible: boolean
  wheelZoom: boolean
  dragScroll: boolean
  updatedAt: number
}

export interface FlintChartDisplaySettingsInput {
  gridVisible: boolean
  crosshairVisible: boolean
  wheelZoom: boolean
  dragScroll: boolean
}

export interface FlintCandlestickChartOptions extends FlintChartShellOptions {
  candleOptions?: Record<string, unknown>
  volumeOptions?: Record<string, unknown>
  volumeScaleOptions?: Record<string, unknown>
  markers?: readonly unknown[]
}

export interface FlintLineSeriesConfig {
  id: string
  options?: Record<string, unknown>
}

export interface FlintLineChartOptions extends FlintChartShellOptions {
  defaultSeriesOptions?: Record<string, unknown>
  series?: readonly FlintLineSeriesConfig[]
}

export interface FlintAreaSeriesConfig {
  id: string
  options?: Record<string, unknown>
}

export interface FlintAreaChartOptions extends FlintChartShellOptions {
  defaultSeriesOptions?: Record<string, unknown>
  series?: readonly FlintAreaSeriesConfig[]
}

export interface FlintHistogramSeriesConfig {
  id: string
  options?: Record<string, unknown>
}

export interface FlintHistogramChartOptions extends FlintChartShellOptions {
  defaultSeriesOptions?: Record<string, unknown>
  series?: readonly FlintHistogramSeriesConfig[]
}

export interface FlintChartShell<TChart extends FlintRuntimeChartLike> {
  chart: TChart
  applyTheme(theme: FlintLightweightChartTheme, options?: FlintChartShellOptions): void
  resize(width: number, height: number): void
  remove(): void
}

export interface FlintCandlestickChart<
  TChart extends FlintRuntimeChartLike,
  TCandle extends FlintRuntimeSeriesLike,
  TVolume extends FlintRuntimeSeriesLike,
  TMarkers = unknown,
> extends FlintChartShell<TChart> {
  candleSeries: TCandle
  volumeSeries: TVolume
  markersPlugin: TMarkers | null
  applyTheme(theme: FlintLightweightChartTheme, options?: FlintCandlestickChartOptions): void
}

export interface FlintLineChart<
  TChart extends FlintRuntimeChartLike,
  TLine extends FlintRuntimeSeriesLike,
> extends FlintChartShell<TChart> {
  series: readonly TLine[]
  seriesById: Readonly<Record<string, TLine>>
  applyTheme(theme: FlintLightweightChartTheme, options?: FlintLineChartOptions): void
}

export interface FlintAreaChart<
  TChart extends FlintRuntimeChartLike,
  TArea extends FlintRuntimeSeriesLike,
> extends FlintChartShell<TChart> {
  series: readonly TArea[]
  seriesById: Readonly<Record<string, TArea>>
  applyTheme(theme: FlintLightweightChartTheme, options?: FlintAreaChartOptions): void
}

export interface FlintHistogramChart<
  TChart extends FlintRuntimeChartLike,
  THistogram extends FlintRuntimeSeriesLike,
> extends FlintChartShell<TChart> {
  series: readonly THistogram[]
  seriesById: Readonly<Record<string, THistogram>>
  applyTheme(theme: FlintLightweightChartTheme, options?: FlintHistogramChartOptions): void
}

export const FLINT_VOLUME_SCALE_OPTIONS = {
  scaleMargins: { top: 0.85, bottom: 0 },
}

export const FLINT_DEFAULT_VOLUME_OPTIONS = {
  priceFormat: { type: "volume" },
  priceScaleId: "vol",
  color: "rgba(107, 107, 120, 0.28)",
} as const

export const FLINT_TRANSPARENT_CHART_LAYOUT = {
  background: { type: "solid", color: "transparent" },
} as const

export const FLINT_CHART_DISPLAY_SETTINGS_VERSION = 1
export const FLINT_CHART_DISPLAY_SETTINGS_STORAGE_KEY = "flinttrade:chart:display-settings:v1"

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function parseJson(value: string | null): unknown {
  if (!value) return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function normaliseBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback
}

function normaliseUpdatedAt(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function recordProp(value: unknown, key: string): Record<string, unknown> {
  if (!isRecord(value)) return {}
  const next = value[key]
  return isRecord(next) ? next : {}
}

function mergeHandleScale(
  theme: FlintLightweightChartTheme,
  handleScale: FlintChartShellOptions["handleScale"],
): FlintChartShellOptions["handleScale"] {
  if (typeof handleScale === "boolean") return handleScale
  if (!isRecord(handleScale)) return theme.handleScale
  return {
    ...theme.handleScale,
    ...handleScale,
    axisPressedMouseMove: {
      ...theme.handleScale.axisPressedMouseMove,
      ...recordProp(handleScale, "axisPressedMouseMove"),
    },
    axisDoubleClickReset: {
      ...theme.handleScale.axisDoubleClickReset,
      ...recordProp(handleScale, "axisDoubleClickReset"),
    },
  }
}

export function createFlintChartDefaultDisplaySettings(): FlintChartDisplaySettings {
  return {
    version: FLINT_CHART_DISPLAY_SETTINGS_VERSION,
    gridVisible: true,
    crosshairVisible: true,
    wheelZoom: true,
    dragScroll: true,
    updatedAt: 0,
  }
}

export function parseFlintChartDisplaySettings(
  value: string | null | unknown,
): FlintChartDisplaySettings {
  const parsed = typeof value === "string" || value === null ? parseJson(value) : value
  const defaults = createFlintChartDefaultDisplaySettings()
  if (!isRecord(parsed)) return defaults

  return {
    version: FLINT_CHART_DISPLAY_SETTINGS_VERSION,
    gridVisible: normaliseBoolean(parsed.gridVisible, defaults.gridVisible),
    crosshairVisible: normaliseBoolean(parsed.crosshairVisible, defaults.crosshairVisible),
    wheelZoom: normaliseBoolean(parsed.wheelZoom, defaults.wheelZoom),
    dragScroll: normaliseBoolean(parsed.dragScroll, defaults.dragScroll),
    updatedAt: normaliseUpdatedAt(parsed.updatedAt),
  }
}

export function encodeFlintChartDisplaySettings(
  settings: FlintChartDisplaySettingsInput,
): string {
  const defaults = createFlintChartDefaultDisplaySettings()
  return JSON.stringify({
    version: FLINT_CHART_DISPLAY_SETTINGS_VERSION,
    gridVisible: normaliseBoolean(settings.gridVisible, defaults.gridVisible),
    crosshairVisible: normaliseBoolean(settings.crosshairVisible, defaults.crosshairVisible),
    wheelZoom: normaliseBoolean(settings.wheelZoom, defaults.wheelZoom),
    dragScroll: normaliseBoolean(settings.dragScroll, defaults.dragScroll),
    updatedAt: Date.now(),
  } satisfies FlintChartDisplaySettings)
}

export function createFlintChartDisplaySettingsOptions(
  settings: FlintChartDisplaySettings | FlintChartDisplaySettingsInput,
): FlintChartShellOptions {
  const normalised = parseFlintChartDisplaySettings(settings)
  return {
    grid: {
      vertLines: { visible: normalised.gridVisible },
      horzLines: { visible: normalised.gridVisible },
    },
    crosshair: {
      vertLine: {
        visible: normalised.crosshairVisible,
        labelVisible: normalised.crosshairVisible,
      },
      horzLine: {
        visible: normalised.crosshairVisible,
        labelVisible: normalised.crosshairVisible,
      },
    },
    handleScale: {
      mouseWheel: normalised.wheelZoom,
    },
    handleScroll: {
      mouseWheel: normalised.dragScroll,
      pressedMouseMove: normalised.dragScroll,
    },
  }
}

export function createFlintChartOptions(
  theme: FlintLightweightChartTheme,
  options: FlintChartShellOptions = {},
): Record<string, unknown> {
  const {
    candle: _candle,
    volume: _volume,
    layout,
    grid,
    crosshair,
    rightPriceScale,
    timeScale,
    handleScale,
    handleScroll,
    kineticScroll,
    trackingMode,
    width,
    height,
    ariaLabel: _ariaLabel,
    resize: _resize,
  } = options as FlintChartShellOptions & {
    candle?: unknown
    volume?: unknown
  }

  return {
    layout: { ...theme.layout, ...layout },
    grid: {
      ...theme.grid,
      ...grid,
      vertLines: { ...theme.grid.vertLines, ...recordProp(grid, "vertLines") },
      horzLines: { ...theme.grid.horzLines, ...recordProp(grid, "horzLines") },
    },
    crosshair: {
      ...theme.crosshair,
      ...crosshair,
      vertLine: { ...theme.crosshair.vertLine, ...recordProp(crosshair, "vertLine") },
      horzLine: { ...theme.crosshair.horzLine, ...recordProp(crosshair, "horzLine") },
    },
    rightPriceScale: { ...theme.rightPriceScale, ...rightPriceScale },
    timeScale: { ...theme.timeScale, ...timeScale },
    handleScale: mergeHandleScale(theme, handleScale),
    handleScroll: isRecord(handleScroll) ? { ...theme.handleScroll, ...handleScroll } : handleScroll ?? theme.handleScroll,
    kineticScroll: { ...theme.kineticScroll, ...kineticScroll },
    trackingMode: { ...theme.trackingMode, ...trackingMode },
    ...(typeof width === "number" ? { width } : {}),
    ...(typeof height === "number" ? { height } : {}),
  }
}

export function splitFlintChartTheme(theme: FlintLightweightChartTheme): {
  chartOptions: Record<string, unknown>
  candle: FlintLightweightChartTheme["candle"]
  volume: FlintLightweightChartTheme["volume"]
} {
  const { candle, volume } = theme
  return {
    chartOptions: createFlintChartOptions(theme),
    candle,
    volume: volume ?? FLINT_DEFAULT_VOLUME_OPTIONS,
  }
}

export function applyFlintChartTheme<TChart extends FlintRuntimeChartLike>(
  chart: TChart,
  theme: FlintLightweightChartTheme,
  options: FlintChartShellOptions = {},
): void {
  chart.applyOptions(createFlintChartOptions(theme, options))
}

export function applyFlintCandlestickTheme<
  TChart extends FlintRuntimeChartLike,
  TCandle extends FlintRuntimeSeriesLike,
>(
  chart: TChart,
  candleSeries: TCandle,
  theme: FlintLightweightChartTheme,
  options: FlintCandlestickChartOptions = {},
): void {
  applyFlintChartTheme(chart, theme, options)
  candleSeries.applyOptions({ ...theme.candle, ...options.candleOptions })
}

export function setFlintChartCanvasLabel(
  container: HTMLElement,
  ariaLabel = "Price chart",
): void {
  const canvas = container.querySelector("canvas")
  if (!canvas) return
  canvas.setAttribute("role", "img")
  canvas.setAttribute("aria-label", ariaLabel)
}

function observeFlintChartSize<TChart extends FlintRuntimeChartLike>(
  container: HTMLElement,
  chart: TChart,
  resize: FlintChartShellOptions["resize"] = "observer",
): () => void {
  if (resize === "none" || typeof ResizeObserver === "undefined") {
    return () => {}
  }

  const observer = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const { width, height } = entry.contentRect
      chart.applyOptions({ width, height })
    }
  })
  observer.observe(container)
  return () => observer.disconnect()
}

export function createFlintChartShell<TChart extends FlintRuntimeChartLike>(
  runtime: FlintChartShellRuntime<TChart>,
  container: HTMLElement,
  theme: FlintLightweightChartTheme,
  options: FlintChartShellOptions = {},
): FlintChartShell<TChart> {
  const chart = runtime.createChart(
    container,
    createFlintChartOptions(theme, {
      ...options,
      width: options.width ?? container.clientWidth,
      height: options.height ?? container.clientHeight,
    }),
  )
  const disconnectResize = observeFlintChartSize(container, chart, options.resize)
  setFlintChartCanvasLabel(container, options.ariaLabel)

  return {
    chart,
    applyTheme(nextTheme, nextOptions = {}) {
      applyFlintChartTheme(chart, nextTheme, nextOptions)
    },
    resize(width, height) {
      if (typeof chart.resize === "function") {
        chart.resize(width, height)
        return
      }
      chart.applyOptions({ width, height })
    },
    remove() {
      disconnectResize()
      chart.remove()
    },
  }
}

export function createFlintCandlestickChart<
  TChart extends FlintRuntimeChartLike,
  TCandle extends FlintRuntimeSeriesLike,
  TVolume extends FlintRuntimeSeriesLike,
  TMarkers = unknown,
>(
  runtime: FlintCandlestickChartRuntime<TChart, TCandle, TVolume, TMarkers>,
  container: HTMLElement,
  theme: FlintLightweightChartTheme,
  options: FlintCandlestickChartOptions = {},
): FlintCandlestickChart<TChart, TCandle, TVolume, TMarkers> {
  const shell = createFlintChartShell(runtime, container, theme, options)
  const candleSeries = runtime.addCandlestickSeries(shell.chart, {
    ...theme.candle,
    ...options.candleOptions,
  })
  const volumeTheme = theme.volume ?? FLINT_DEFAULT_VOLUME_OPTIONS
  const volumeSeries = runtime.addHistogramSeries(shell.chart, {
    ...volumeTheme,
    ...options.volumeOptions,
  })
  shell.chart
    .priceScale(volumeTheme.priceScaleId)
    .applyOptions(options.volumeScaleOptions ?? FLINT_VOLUME_SCALE_OPTIONS)

  const markersPlugin =
    runtime.createSeriesMarkers?.(candleSeries, options.markers ?? []) ?? null

  return {
    ...shell,
    candleSeries,
    volumeSeries,
    markersPlugin,
    applyTheme(nextTheme, nextOptions = {}) {
      applyFlintCandlestickTheme(shell.chart, candleSeries, nextTheme, nextOptions)
    },
  }
}

export function createFlintLineChart<
  TChart extends FlintRuntimeChartLike,
  TLine extends FlintRuntimeSeriesLike,
>(
  runtime: FlintLineChartRuntime<TChart, TLine>,
  container: HTMLElement,
  theme: FlintLightweightChartTheme,
  options: FlintLineChartOptions = {},
): FlintLineChart<TChart, TLine> {
  const shell = createFlintChartShell(runtime, container, theme, options)
  const series: TLine[] = []
  const seriesById: Record<string, TLine> = {}

  for (const seriesConfig of options.series ?? []) {
    if (seriesById[seriesConfig.id]) {
      throw new Error(`Duplicate Flint line series id: ${seriesConfig.id}`)
    }

    const lineSeries = runtime.addLineSeries(shell.chart, {
      ...options.defaultSeriesOptions,
      ...seriesConfig.options,
    })
    series.push(lineSeries)
    seriesById[seriesConfig.id] = lineSeries
  }

  return {
    ...shell,
    series,
    seriesById,
    applyTheme(nextTheme, nextOptions = {}) {
      applyFlintChartTheme(shell.chart, nextTheme, nextOptions)

      for (const seriesConfig of nextOptions.series ?? []) {
        const lineSeries = seriesById[seriesConfig.id]
        if (!lineSeries) continue
        lineSeries.applyOptions({
          ...nextOptions.defaultSeriesOptions,
          ...seriesConfig.options,
        })
      }
    },
  }
}

export function createFlintAreaChart<
  TChart extends FlintRuntimeChartLike,
  TArea extends FlintRuntimeSeriesLike,
>(
  runtime: FlintAreaChartRuntime<TChart, TArea>,
  container: HTMLElement,
  theme: FlintLightweightChartTheme,
  options: FlintAreaChartOptions = {},
): FlintAreaChart<TChart, TArea> {
  const shell = createFlintChartShell(runtime, container, theme, options)
  const series: TArea[] = []
  const seriesById: Record<string, TArea> = {}

  for (const seriesConfig of options.series ?? []) {
    if (seriesById[seriesConfig.id]) {
      throw new Error(`Duplicate Flint area series id: ${seriesConfig.id}`)
    }

    const areaSeries = runtime.addAreaSeries(shell.chart, {
      ...options.defaultSeriesOptions,
      ...seriesConfig.options,
    })
    series.push(areaSeries)
    seriesById[seriesConfig.id] = areaSeries
  }

  return {
    ...shell,
    series,
    seriesById,
    applyTheme(nextTheme, nextOptions = {}) {
      applyFlintChartTheme(shell.chart, nextTheme, nextOptions)

      for (const seriesConfig of nextOptions.series ?? []) {
        const areaSeries = seriesById[seriesConfig.id]
        if (!areaSeries) continue
        areaSeries.applyOptions({
          ...nextOptions.defaultSeriesOptions,
          ...seriesConfig.options,
        })
      }
    },
  }
}

export function createFlintHistogramChart<
  TChart extends FlintRuntimeChartLike,
  THistogram extends FlintRuntimeSeriesLike,
>(
  runtime: FlintHistogramChartRuntime<TChart, THistogram>,
  container: HTMLElement,
  theme: FlintLightweightChartTheme,
  options: FlintHistogramChartOptions = {},
): FlintHistogramChart<TChart, THistogram> {
  const shell = createFlintChartShell(runtime, container, theme, options)
  const series: THistogram[] = []
  const seriesById: Record<string, THistogram> = {}

  for (const seriesConfig of options.series ?? []) {
    if (seriesById[seriesConfig.id]) {
      throw new Error(`Duplicate Flint histogram series id: ${seriesConfig.id}`)
    }

    const histogramSeries = runtime.addHistogramSeries(shell.chart, {
      ...options.defaultSeriesOptions,
      ...seriesConfig.options,
    })
    series.push(histogramSeries)
    seriesById[seriesConfig.id] = histogramSeries
  }

  return {
    ...shell,
    series,
    seriesById,
    applyTheme(nextTheme, nextOptions = {}) {
      applyFlintChartTheme(shell.chart, nextTheme, nextOptions)

      for (const seriesConfig of nextOptions.series ?? []) {
        const histogramSeries = seriesById[seriesConfig.id]
        if (!histogramSeries) continue
        histogramSeries.applyOptions({
          ...nextOptions.defaultSeriesOptions,
          ...seriesConfig.options,
        })
      }
    },
  }
}

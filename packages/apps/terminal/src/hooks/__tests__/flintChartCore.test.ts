import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import {
  FLINT_CHART_DISPLAY_SETTINGS_STORAGE_KEY,
  FLINT_CHART_VIEW_STATE_STORAGE_KEY,
  FLINT_CHART_FIB_EXTENSION_LEVELS,
  FLINT_CHART_FIB_LEVELS,
  FLINT_VOLUME_SCALE_OPTIONS,
  createFlintChartBrushDrawing,
  createFlintChartBrushDrawingData,
  createFlintChartDisplaySettingsOptions,
  createFlintChartDefaultDisplaySettings,
  createFlintChartFibExtensionPriceLines,
  createFlintChartFibPriceLines,
  createFlintChartOptions,
  createFlintChartDrawingsStorageKey,
  createFlintChartElliottWaveDrawingData,
  createFlintChartElliottWaveMarkers,
  createFlintChartHLinePriceLine,
  createFlintChartLineDrawingData,
  createFlintChartLineDrawingSeriesOptions,
  createFlintChartMeasureMarker,
  createFlintChartParallelChannelDrawingData,
  createFlintChartPositionRiskPriceLines,
  createFlintChartPriceLabelMarker,
  createFlintChartCalloutMarker,
  createFlintChartCircleDrawingData,
  getFlintChartDrawingStyle,
  createFlintChartDrawingSummaries,
  createFlintChartRectPriceLines,
  createFlintChartTextMarker,
  createFlintChartVLineMarker,
  createFlintChartDrawingHandleMarkers,
  createFlintChartDrawingRenderPlan,
  createFlintChartDrawingRenderPlanDiff,
  findFlintChartDrawingHit,
  findFlintChartDrawingHandleHit,
  moveFlintChartDrawingHandleByDelta,
  moveFlintChartDrawingByDelta,
  moveFlintChartDrawingByPriceDelta,
  updateFlintChartDrawingStyle,
  updateFlintChartDrawingStateById,
  updateFlintChartDrawingsHidden,
  updateFlintChartDrawingsLocked,
  getFlintChartVisibleDrawings,
  FLINT_CHART_DEFAULT_INDICATORS,
  FLINT_CHART_DEFAULT_PERIODS,
  FLINT_CHART_INDICATOR_DEFAULT_COLORS,
  FLINT_CHART_INDICATOR_DEFAULT_LINE_STYLES,
  FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES,
  FLINT_CHART_INDICATOR_PANE_SIZE_LABELS,
  FLINT_CHART_INDICATOR_PANE_SIZE_OPTIONS,
  FLINT_CHART_INDICATOR_PANE_SIZE_SHORT_LABELS,
  FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MAX,
  FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MIN,
  FLINT_CHART_INDICATOR_PANE_STRETCH_FACTORS,
  FLINT_CHART_INDICATOR_SETTINGS_STORAGE_KEY,
  FLINT_CHART_INDICATOR_CATEGORIES,
  FLINT_CHART_INDICATOR_DEFINITIONS,
  createFlintChartDefaultIndicatorSettings,
  advanceFlintChartDrawingDraft,
  encodeFlintChartIndicatorSettings,
  createFlintChartIndicatorLifecyclePlan,
  createFlintChartIndicatorPaneControls,
  createFlintChartIndicatorPaneLayoutPlan,
  createFlintChartIndicatorSeriesRenderPlan,
  createFlintChartIndicatorSeriesRenderPlanDiff,
  resizeFlintChartIndicatorPaneStretchFactors,
  getFlintChartActiveIndicatorCount,
  getFlintChartActiveIndicatorCountByCategory,
  getFlintChartIndicatorPaneSpec,
  createFlintChartIndicatorPaneOptions,
  createFlintChartIndicatorHistogramSeriesOptions,
  createFlintChartIndicatorLineSeriesOptions,
  createFlintChartOIOverlaySeriesOptions,
  createFlintChartOIProfileBarData,
  getFlintChartLineStyleCode,
  createFlintChartPivotPriceLineSpecs,
  calcEMA,
  calcMACD,
  calcRSI,
  calcVWAP,
  buildHistData,
  buildLineData,
  createFlintPlotlyTheme,
  parseFlintChartIndicatorSettings,
  createFlintCandlestickChart,
  createFlintLightweightChartTheme,
  encodeFlintChartDisplaySettings,
  mergeFlintPlotlyLayout,
  FLINT_PLOTLY_DEFAULT_CONFIG,
  encodeFlintChartDrawings,
  encodeFlintChartViewState,
  parseFlintChartDisplaySettings,
  parseFlintChartDrawings,
  parseFlintChartViewState,
  getFlintChartSelectedDrawing,
  removeFlintChartDrawingById,
  type FlintCandlestickChartRuntime,
  type FlintChartOhlcvBar,
  type FlintRuntimeChartLike,
  type FlintRuntimeSeriesLike,
} from "@flinttrade/design-system";

const terminalSrcRoot = path.resolve(process.cwd(), "src");
const lightweightRuntimeAdapterPath = path.join(
  terminalSrcRoot,
  "lib/lightweightChartRuntime.ts",
);

function collectProductionSourceFiles(dir: string): string[] {
  const entries = readdirSync(dir, { withFileTypes: true });
  return entries.flatMap((entry) => {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "__tests__") return [];
      return collectProductionSourceFiles(fullPath);
    }
    if (!/\.(ts|tsx)$/.test(entry.name)) return [];
    if (/\.test\.(ts|tsx)$/.test(entry.name)) return [];
    return [fullPath];
  });
}

function valueImportsFromLightweightCharts(source: string): string[] {
  const offenders: string[] = [];
  const importBlockRe = /import\s*\{([^;]*?)\}\s*from\s*["']lightweight-charts["'];?/g;
  for (const match of source.matchAll(importBlockRe)) {
    const specifiers = match[1]
      .split(",")
      .map((specifier) => specifier.trim())
      .filter(Boolean);
    offenders.push(
      ...specifiers.filter((specifier) => !specifier.startsWith("type ")),
    );
  }
  return offenders;
}

const palette = {
  background: "#0a0a0f",
  grid: "#1e1e2e",
  text: "#a0a0b0",
  border: "#2a2a3a",
  up: "#22c55e",
  down: "#ef4444",
  accent: "#38bdf8",
  muted: "#6b6b78",
};

describe("core Flint Lightweight Charts factory", () => {
  const observe = vi.fn();
  const disconnect = vi.fn();

  beforeEach(() => {
    observe.mockClear();
    disconnect.mockClear();
    vi.stubGlobal(
      "ResizeObserver",
      class ResizeObserver {
        observe = observe;
        disconnect = disconnect;
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates chart, candle, volume, markers, accessibility label, and volume scale from core", () => {
    const container = document.createElement("div");
    const canvas = document.createElement("canvas");
    container.appendChild(canvas);

    const priceScaleApplyOptions = vi.fn();
    const chart = {
      applyOptions: vi.fn(),
      priceScale: vi.fn(() => ({ applyOptions: priceScaleApplyOptions })),
      remove: vi.fn(),
    } satisfies FlintRuntimeChartLike;
    const candleSeries = { applyOptions: vi.fn() } satisfies FlintRuntimeSeriesLike;
    const volumeSeries = { applyOptions: vi.fn() } satisfies FlintRuntimeSeriesLike;
    const markersPlugin = { setMarkers: vi.fn() };
    const runtime: FlintCandlestickChartRuntime<
      typeof chart,
      typeof candleSeries,
      typeof volumeSeries,
      typeof markersPlugin
    > = {
      createChart: vi.fn(() => chart),
      addCandlestickSeries: vi.fn(() => candleSeries),
      addHistogramSeries: vi.fn(() => volumeSeries),
      createSeriesMarkers: vi.fn(() => markersPlugin),
    };

    const theme = createFlintLightweightChartTheme(palette);
    const flintChart = createFlintCandlestickChart(runtime, container, theme, {
      ariaLabel: "NIFTY price chart",
    });

    expect(runtime.createChart).toHaveBeenCalledWith(
      container,
      expect.objectContaining({
        layout: expect.objectContaining({ textColor: "#a0a0b0" }),
        handleScale: expect.objectContaining({ mouseWheel: true }),
        handleScroll: expect.objectContaining({ horzTouchDrag: true }),
      }),
    );
    expect(runtime.addCandlestickSeries).toHaveBeenCalledWith(
      chart,
      expect.objectContaining({ upColor: "#22c55e", downColor: "#ef4444" }),
    );
    expect(runtime.addHistogramSeries).toHaveBeenCalledWith(
      chart,
      expect.objectContaining({ priceScaleId: "vol" }),
    );
    expect(priceScaleApplyOptions).toHaveBeenCalledWith(FLINT_VOLUME_SCALE_OPTIONS);
    expect(runtime.createSeriesMarkers).toHaveBeenCalledWith(candleSeries, []);
    expect(canvas.getAttribute("role")).toBe("img");
    expect(canvas.getAttribute("aria-label")).toBe("NIFTY price chart");

    flintChart.applyTheme(theme);
    expect(chart.applyOptions).toHaveBeenCalled();
    expect(candleSeries.applyOptions).toHaveBeenCalledWith(
      expect.objectContaining({ upColor: "#22c55e" }),
    );

    flintChart.remove();
    expect(disconnect).toHaveBeenCalled();
    expect(chart.remove).toHaveBeenCalled();
  });

  it("keeps Lightweight Charts value imports isolated to the Flint runtime adapter", () => {
    const offenders = collectProductionSourceFiles(terminalSrcRoot)
      .filter((filePath) => filePath !== lightweightRuntimeAdapterPath)
      .flatMap((filePath) => {
        const valueImports = valueImportsFromLightweightCharts(readFileSync(filePath, "utf8"));
        return valueImports.map((specifier) => (
          `${path.relative(process.cwd(), filePath)} imports ${specifier}`
        ));
      });

    expect(offenders).toEqual([]);
  });

  it("owns Plotly theme, default config, and layout merging in core", async () => {
    const designSystem = await import("@flinttrade/design-system");
    expect(designSystem).toHaveProperty("createFlintPlotlyTheme");
    expect(designSystem).toHaveProperty("mergeFlintPlotlyLayout");
    expect(designSystem).toHaveProperty("FLINT_PLOTLY_DEFAULT_CONFIG");

    const baseTheme = createFlintPlotlyTheme({
      grid: "#1e1e2e",
      text: "#a0a0b0",
      accent: "#6366f1",
      profit: "#22c55e",
      loss: "#ef4444",
      warning: "#f59e0b",
      border: "#2a2a3a",
    });

    expect(baseTheme.paper_bgcolor).toBe("transparent");
    expect(baseTheme.plot_bgcolor).toBe("transparent");
    expect(baseTheme.colorway).toEqual([
      "#6366f1",
      "#22c55e",
      "#ef4444",
      "#f59e0b",
      "#818cf8",
      "#06b6d4",
    ]);
    expect(FLINT_PLOTLY_DEFAULT_CONFIG).toMatchObject({
      displayModeBar: true,
      displaylogo: false,
      responsive: true,
    });

    const merged = mergeFlintPlotlyLayout(baseTheme, {
      title: { text: "GEX" },
      xaxis: { title: { text: "Strike" } },
      yaxis: { zerolinecolor: "#ffffff" },
    });

    expect(merged.margin).toEqual({ t: 30, r: 20, b: 40, l: 50 });
    expect(merged.title).toEqual({ text: "GEX" });
    expect(merged.xaxis).toMatchObject({
      gridcolor: "#1e1e2e",
      title: { text: "Strike" },
    });
    expect(merged.yaxis).toMatchObject({
      gridcolor: "#1e1e2e",
      zerolinecolor: "#ffffff",
    });
  });

  it("creates named line-series charts through the core runtime contract", async () => {
    const designSystem = await import("@flinttrade/design-system");
    expect(designSystem).toHaveProperty("createFlintLineChart");

    const container = document.createElement("div");
    const canvas = document.createElement("canvas");
    container.appendChild(canvas);

    const chart = {
      applyOptions: vi.fn(),
      priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
      remove: vi.fn(),
    };
    const mainSeries = { applyOptions: vi.fn() };
    const overlaySeries = { applyOptions: vi.fn() };
    const runtime = {
      createChart: vi.fn(() => chart),
      addLineSeries: vi.fn()
        .mockReturnValueOnce(mainSeries)
        .mockReturnValueOnce(overlaySeries),
    };

    const theme = createFlintLightweightChartTheme(palette);
    const flintChart = designSystem.createFlintLineChart(runtime, container, theme, {
      ariaLabel: "Straddle line chart",
      defaultSeriesOptions: {
        priceLineVisible: false,
        lastValueVisible: true,
      },
      series: [
        { id: "straddle", options: { color: "#3b82f6", lineWidth: 2 } },
        { id: "spot", options: { color: "#eab308", lineWidth: 1, visible: false } },
      ],
    });

    expect(runtime.addLineSeries).toHaveBeenCalledWith(chart, {
      priceLineVisible: false,
      lastValueVisible: true,
      color: "#3b82f6",
      lineWidth: 2,
    });
    expect(runtime.addLineSeries).toHaveBeenCalledWith(chart, {
      priceLineVisible: false,
      lastValueVisible: true,
      color: "#eab308",
      lineWidth: 1,
      visible: false,
    });
    expect(flintChart.seriesById.straddle).toBe(mainSeries);
    expect(flintChart.seriesById.spot).toBe(overlaySeries);
    expect(canvas.getAttribute("aria-label")).toBe("Straddle line chart");

    flintChart.applyTheme(theme, {
      series: [
        { id: "straddle", options: { color: "#22c55e" } },
        { id: "spot", options: { visible: true } },
      ],
    });

    expect(chart.applyOptions).toHaveBeenCalled();
    expect(mainSeries.applyOptions).toHaveBeenCalledWith({
      color: "#22c55e",
    });
    expect(overlaySeries.applyOptions).toHaveBeenCalledWith({
      visible: true,
    });
  });

  it("creates named area-series charts through the core runtime contract", async () => {
    const designSystem = await import("@flinttrade/design-system");
    expect(designSystem).toHaveProperty("createFlintAreaChart");

    const container = document.createElement("div");
    const canvas = document.createElement("canvas");
    container.appendChild(canvas);

    const chart = {
      applyOptions: vi.fn(),
      priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
      remove: vi.fn(),
    };
    const pnlSeries = { applyOptions: vi.fn() };
    const drawdownSeries = { applyOptions: vi.fn() };
    const runtime = {
      createChart: vi.fn(() => chart),
      addAreaSeries: vi.fn()
        .mockReturnValueOnce(pnlSeries)
        .mockReturnValueOnce(drawdownSeries),
    };

    const theme = createFlintLightweightChartTheme(palette);
    const flintChart = designSystem.createFlintAreaChart(runtime, container, theme, {
      ariaLabel: "Mark-to-market PnL chart",
      defaultSeriesOptions: {
        priceScaleId: "right",
        lineWidth: 1,
      },
      series: [
        { id: "pnl", options: { lineColor: "#7C3AED", lineWidth: 2 } },
        { id: "drawdown", options: { lineColor: "#EF4444" } },
      ],
    });

    expect(runtime.addAreaSeries).toHaveBeenCalledWith(chart, {
      priceScaleId: "right",
      lineWidth: 2,
      lineColor: "#7C3AED",
    });
    expect(runtime.addAreaSeries).toHaveBeenCalledWith(chart, {
      priceScaleId: "right",
      lineWidth: 1,
      lineColor: "#EF4444",
    });
    expect(flintChart.seriesById.pnl).toBe(pnlSeries);
    expect(flintChart.seriesById.drawdown).toBe(drawdownSeries);
    expect(canvas.getAttribute("aria-label")).toBe("Mark-to-market PnL chart");
  });

  it("creates named histogram-series charts through the core runtime contract", async () => {
    const designSystem = await import("@flinttrade/design-system");
    expect(designSystem).toHaveProperty("createFlintHistogramChart");

    const container = document.createElement("div");
    const canvas = document.createElement("canvas");
    container.appendChild(canvas);

    const chart = {
      applyOptions: vi.fn(),
      priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
      remove: vi.fn(),
    };
    const pnlSeries = { applyOptions: vi.fn() };
    const runtime = {
      createChart: vi.fn(() => chart),
      addHistogramSeries: vi.fn(() => pnlSeries),
    };

    const theme = createFlintLightweightChartTheme(palette);
    const flintChart = designSystem.createFlintHistogramChart(runtime, container, theme, {
      ariaLabel: "Monthly P&L chart",
      defaultSeriesOptions: {
        priceScaleId: "right",
        priceFormat: { type: "price", precision: 0, minMove: 1 },
      },
      series: [
        { id: "monthly-pnl", options: { color: "#34d399" } },
      ],
    });

    expect(runtime.addHistogramSeries).toHaveBeenCalledWith(chart, {
      priceScaleId: "right",
      priceFormat: { type: "price", precision: 0, minMove: 1 },
      color: "#34d399",
    });
    expect(flintChart.seriesById["monthly-pnl"]).toBe(pnlSeries);
    expect(canvas.getAttribute("aria-label")).toBe("Monthly P&L chart");
  });

  it("centralises display settings persistence and safe chart option overrides in core", () => {
    expect(FLINT_CHART_DISPLAY_SETTINGS_STORAGE_KEY).toBe("flinttrade:chart:display-settings:v1");
    expect(createFlintChartDefaultDisplaySettings()).toEqual({
      version: 1,
      gridVisible: true,
      crosshairVisible: true,
      wheelZoom: true,
      dragScroll: true,
      updatedAt: 0,
    });

    expect(parseFlintChartDisplaySettings({
      gridVisible: false,
      crosshairVisible: false,
      wheelZoom: false,
      dragScroll: false,
      updatedAt: 42,
      unknown: "ignored",
    })).toEqual({
      version: 1,
      gridVisible: false,
      crosshairVisible: false,
      wheelZoom: false,
      dragScroll: false,
      updatedAt: 42,
    });
    expect(parseFlintChartDisplaySettings("{bad json")).toEqual(createFlintChartDefaultDisplaySettings());

    const beforeEncode = Date.now();
    const encoded = encodeFlintChartDisplaySettings({
      gridVisible: false,
      crosshairVisible: false,
      wheelZoom: false,
      dragScroll: false,
    });
    const afterEncode = Date.now();
    const parsed = parseFlintChartDisplaySettings(encoded);
    expect(parsed).toMatchObject({
      version: 1,
      gridVisible: false,
      crosshairVisible: false,
      wheelZoom: false,
      dragScroll: false,
    });
    expect(parsed.updatedAt).toBeGreaterThanOrEqual(beforeEncode);
    expect(parsed.updatedAt).toBeLessThanOrEqual(afterEncode);

    const theme = createFlintLightweightChartTheme(palette);
    const options = createFlintChartOptions(
      theme,
      createFlintChartDisplaySettingsOptions(parsed),
    );

    expect(options.grid).toEqual({
      vertLines: { ...theme.grid.vertLines, visible: false },
      horzLines: { ...theme.grid.horzLines, visible: false },
    });
    expect(options.crosshair).toEqual({
      ...theme.crosshair,
      vertLine: { ...theme.crosshair.vertLine, visible: false, labelVisible: false },
      horzLine: { ...theme.crosshair.horzLine, visible: false, labelVisible: false },
    });
    expect(options.handleScale).toMatchObject({
      mouseWheel: false,
      pinch: true,
      axisPressedMouseMove: { time: true, price: true },
    });
    expect(options.handleScroll).toMatchObject({
      mouseWheel: false,
      pressedMouseMove: false,
      horzTouchDrag: true,
    });
  });

  it("keeps drawing persistence in the core contract while accepting the legacy raw-array shape", () => {
    const legacyRawArray = JSON.stringify([
      { kind: "hline", id: "support", price: 22100 },
      { kind: "trendline", id: "trend", p1: { time: 1, price: 22000 }, p2: { time: 2, price: 22240 } },
      { kind: "text", id: "note", point: { time: 3, price: 22320 }, label: "Breakout" },
      { kind: "price_label", id: "price", point: { time: 4, price: 22440 } },
      { kind: "callout", id: "callout", point: { time: 5, price: 22500 }, label: "Watch" },
      { kind: "hline", id: "bad-price", price: Number.NaN },
      { kind: "unknown", id: "ignored" },
    ]);

    expect(parseFlintChartDrawings<number>(legacyRawArray)).toEqual([
      { kind: "hline", id: "support", price: 22100 },
      { kind: "trendline", id: "trend", p1: { time: 1, price: 22000 }, p2: { time: 2, price: 22240 } },
      { kind: "text", id: "note", point: { time: 3, price: 22320 }, label: "Breakout" },
      { kind: "price_label", id: "price", point: { time: 4, price: 22440 } },
      { kind: "callout", id: "callout", point: { time: 5, price: 22500 }, label: "Watch" },
    ]);

    const encoded = encodeFlintChartDrawings([
      { kind: "vline", id: "open", time: 1719824400 },
      { kind: "rect", id: "zone", p1: { time: 1719824400, price: 22150 }, p2: { time: 1719835200, price: 22300 } },
    ]);

    expect(JSON.parse(encoded)).toEqual({
      version: 1,
      drawings: [
        { kind: "vline", id: "open", time: 1719824400 },
        { kind: "rect", id: "zone", p1: { time: 1719824400, price: 22150 }, p2: { time: 1719835200, price: 22300 } },
      ],
    });
    expect(parseFlintChartDrawings<number>(encoded)).toEqual([
      { kind: "vline", id: "open", time: 1719824400 },
      { kind: "rect", id: "zone", p1: { time: 1719824400, price: 22150 }, p2: { time: 1719835200, price: 22300 } },
    ]);
  });

  it("creates stable drawing keys and versioned chart view state from core", () => {
    expect(createFlintChartDrawingsStorageKey({ symbol: " nifty ", exchange: " nse_index " }))
      .toBe("flinttrade:drawings:NIFTY:NSE_INDEX");
    expect(createFlintChartDrawingsStorageKey({ symbol: "bank nifty", exchange: "nse index", workspaceId: "alpha desk" }))
      .toBe("flinttrade:drawings:alpha%20desk:BANK%20NIFTY:NSE%20INDEX");

    const beforeEncode = Date.now();
    const encoded = encodeFlintChartViewState({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      interval: "15m",
    });
    const afterEncode = Date.now();

    expect(FLINT_CHART_VIEW_STATE_STORAGE_KEY).toBe("flinttrade:chart:view-state:v1");
    const parsed = parseFlintChartViewState(encoded);
    expect(parsed).toMatchObject({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      interval: "15m",
    });
    expect(parsed?.updatedAt).toBeGreaterThanOrEqual(beforeEncode);
    expect(parsed?.updatedAt).toBeLessThanOrEqual(afterEncode);
    expect(parseFlintChartViewState("{bad json")).toBeNull();
    expect(parseFlintChartViewState({ symbol: "", exchange: "NSE_INDEX", interval: "5m" })).toBeNull();
  });

  it("round-trips visible logical range in the core chart view state", () => {
    const encoded = encodeFlintChartViewState({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      interval: "15m",
      visibleLogicalRange: { from: 42.25, to: 118.75 },
    });

    expect(parseFlintChartViewState(encoded)).toMatchObject({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      interval: "15m",
      visibleLogicalRange: { from: 42.25, to: 118.75 },
    });
    const samePointRange = parseFlintChartViewState({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      interval: "15m",
      visibleLogicalRange: { from: 12, to: 12 },
    });
    expect(samePointRange).toMatchObject({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      interval: "15m",
    });
    expect(samePointRange?.visibleLogicalRange).toBeUndefined();

    const nonFiniteRange = parseFlintChartViewState({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      interval: "15m",
      visibleLogicalRange: { from: Number.NaN, to: 20 },
    });
    expect(nonFiniteRange).toMatchObject({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      interval: "15m",
    });
    expect(nonFiniteRange?.visibleLogicalRange).toBeUndefined();
  });

  it("centralises drawing render semantics without importing the chart runtime into core", () => {
    expect(createFlintChartHLinePriceLine(22100)).toEqual({
      price: 22100,
      color: "#eab308",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "",
    });
    expect(createFlintChartVLineMarker(1719824400)).toEqual({
      time: 1719824400,
      position: "inBar",
      color: "#64748b",
      shape: "square",
      size: 0.5,
      text: "|",
    });
    expect(createFlintChartLineDrawingSeriesOptions("ray")).toMatchObject({
      color: "#f97316",
      priceScaleId: "right",
      priceLineVisible: false,
    });
    expect(createFlintChartLineDrawingData({
      kind: "trendline",
      id: "trend",
      p1: { time: 1, price: 22000 },
      p2: { time: 2, price: 22240 },
    })).toEqual([
      { time: 1, value: 22000 },
      { time: 2, value: 22240 },
    ]);
    expect(createFlintChartLineDrawingData({
      kind: "ray",
      id: "ray",
      p1: { time: 10, price: 22000 },
      p2: { time: 20, price: 22100 },
    })).toEqual([
      { time: 10, value: 22000 },
      { time: 270, value: 24600 },
    ]);
    expect(createFlintChartLineDrawingData({
      kind: "extended_line",
      id: "extended",
      p1: { time: 10, price: 22000 },
      p2: { time: 20, price: 22100 },
    })).toEqual([
      { time: -240, value: 19500 },
      { time: 270, value: 24600 },
    ]);

    const brushDrawing = createFlintChartBrushDrawing([
      { time: 1, price: 100 },
      { time: 2, price: 105 },
      { time: 3, price: 102 },
    ], () => "brush");
    expect(brushDrawing).toEqual({
      kind: "brush",
      id: "brush",
      points: [
        { time: 1, price: 100 },
        { time: 2, price: 105 },
        { time: 3, price: 102 },
      ],
    });
    expect(createFlintChartBrushDrawingData(brushDrawing!)).toEqual([
      { time: 1, value: 100 },
      { time: 2, value: 105 },
      { time: 3, value: 102 },
    ]);

    const circleArcs = createFlintChartCircleDrawingData({
      kind: "circle",
      id: "circle",
      p1: { time: 10, price: 22000 },
      p2: { time: 20, price: 22200 },
    });
    expect(circleArcs).toHaveLength(2);
    expect(circleArcs[0]).toHaveLength(17);
    expect(circleArcs[1]).toHaveLength(17);
    expect(circleArcs[0][0]).toEqual({ time: 10, value: 22100 });
    expect(circleArcs[0][8]).toEqual({ time: 15, value: 22200 });
    expect(circleArcs[0].at(-1)).toEqual({ time: 20, value: 22100 });
    expect(circleArcs[1][0]).toEqual({ time: 10, value: 22100 });
    expect(circleArcs[1][8]).toEqual({ time: 15, value: 22000 });
    expect(circleArcs[1].at(-1)).toEqual({ time: 20, value: 22100 });

    expect(createFlintChartParallelChannelDrawingData({
      kind: "parallel_channel",
      id: "channel",
      p1: { time: 10, price: 22000 },
      p2: { time: 20, price: 22100 },
      p3: { time: 12, price: 22200 },
    })).toEqual([
      [
        { time: 10, value: 22000 },
        { time: 20, value: 22100 },
      ],
      [
        { time: 12, value: 22200 },
        { time: 22, value: 22300 },
      ],
      [
        { time: 10, value: 22000 },
        { time: 12, value: 22200 },
      ],
      [
        { time: 20, value: 22100 },
        { time: 22, value: 22300 },
      ],
    ]);

    const fibExtensionLines = createFlintChartFibExtensionPriceLines({
      kind: "fib_extension",
      id: "fib-extension",
      p1: { time: 1, price: 100 },
      p2: { time: 2, price: 200 },
      p3: { time: 3, price: 150 },
    });
    expect(fibExtensionLines).toHaveLength(FLINT_CHART_FIB_EXTENSION_LEVELS.length);
    expect(fibExtensionLines[0]).toMatchObject({ price: 150, title: "Fib Ext 0.0%" });
    expect(fibExtensionLines[2]).toMatchObject({ price: 250, title: "Fib Ext 100.0%" });
    expect(fibExtensionLines.at(-1)).toMatchObject({ price: 411.8, title: "Fib Ext 261.8%" });

    expect(createFlintChartPositionRiskPriceLines({
      kind: "long_position",
      id: "long-position",
      p1: { time: 1, price: 100 },
      p2: { time: 2, price: 130 },
      p3: { time: 3, price: 90 },
    })).toEqual([
      expect.objectContaining({ price: 100, title: "Long Entry" }),
      expect.objectContaining({ price: 130, title: "Long Target" }),
      expect.objectContaining({ price: 90, title: "Long Stop" }),
    ]);
    expect(createFlintChartPositionRiskPriceLines({
      kind: "short_position",
      id: "short-position",
      p1: { time: 1, price: 100 },
      p2: { time: 2, price: 70 },
      p3: { time: 3, price: 110 },
    })).toEqual([
      expect.objectContaining({ price: 100, title: "Short Entry" }),
      expect.objectContaining({ price: 70, title: "Short Target" }),
      expect.objectContaining({ price: 110, title: "Short Stop" }),
    ]);

    const impulseDrawing = {
      kind: "elliott_impulse" as const,
      id: "impulse",
      points: [
        { time: 1, price: 100 },
        { time: 2, price: 120 },
        { time: 3, price: 110 },
        { time: 4, price: 140 },
        { time: 5, price: 128 },
        { time: 6, price: 155 },
      ],
    };
    expect(createFlintChartElliottWaveDrawingData(impulseDrawing)).toEqual([
      { time: 1, value: 100 },
      { time: 2, value: 120 },
      { time: 3, value: 110 },
      { time: 4, value: 140 },
      { time: 5, value: 128 },
      { time: 6, value: 155 },
    ]);
    expect(createFlintChartElliottWaveMarkers(impulseDrawing).map((marker) => marker.text)).toEqual([
      "0",
      "1",
      "2",
      "3",
      "4",
      "5",
    ]);

    const correctionDrawing = {
      kind: "elliott_correction" as const,
      id: "correction",
      points: [
        { time: 1, price: 100 },
        { time: 2, price: 120 },
        { time: 3, price: 108 },
        { time: 4, price: 132 },
      ],
    };
    expect(createFlintChartElliottWaveMarkers(correctionDrawing).map((marker) => marker.text)).toEqual([
      "0",
      "A",
      "B",
      "C",
    ]);

    const fibLines = createFlintChartFibPriceLines({
      kind: "fib",
      id: "fib",
      p1: { time: 1, price: 100 },
      p2: { time: 2, price: 200 },
    });
    expect(fibLines).toHaveLength(FLINT_CHART_FIB_LEVELS.length);
    expect(fibLines[0]).toMatchObject({ price: 200, title: "Fib 0.0%" });
    expect(fibLines.at(-1)).toMatchObject({ price: 100, title: "Fib 100.0%" });

    expect(createFlintChartRectPriceLines({
      kind: "rect",
      id: "zone",
      p1: { time: 1, price: 100 },
      p2: { time: 2, price: 200 },
    })).toEqual([
      expect.objectContaining({ price: 200, title: "Rect Top" }),
      expect.objectContaining({ price: 100, title: "Rect Bot" }),
    ]);
    expect(createFlintChartTextMarker({
      kind: "text",
      id: "note",
      point: { time: 3, price: 22320 },
      label: "Breakout",
    })).toEqual({
      time: 3,
      position: "atPriceMiddle",
      color: "#facc15",
      shape: "circle",
      size: 1,
      price: 22320,
      text: "Breakout",
    });
    expect(createFlintChartPriceLabelMarker({
      kind: "price_label",
      id: "price",
      point: { time: 4, price: 22440 },
    })).toEqual({
      time: 4,
      position: "atPriceMiddle",
      color: "#38bdf8",
      shape: "square",
      size: 1,
      price: 22440,
      text: "22,440.00",
    });
    expect(createFlintChartCalloutMarker({
      kind: "callout",
      id: "callout",
      point: { time: 5, price: 22500 },
      label: "Watch",
    })).toEqual({
      time: 5,
      position: "atPriceMiddle",
      color: "#f97316",
      shape: "square",
      size: 1,
      price: 22500,
      text: "Watch",
    });
    expect(createFlintChartDrawingHandleMarkers([
      {
        kind: "trendline",
        id: "trend",
        p1: { time: 1, price: 22000 },
        p2: { time: 2, price: 22240 },
      },
      { kind: "hline", id: "support", price: 22100 },
    ], "trend")).toEqual([
      expect.objectContaining({ time: 1, price: 22000, text: "1", shape: "circle" }),
      expect.objectContaining({ time: 2, price: 22240, text: "2", shape: "circle" }),
    ]);
  });

  it("centralises drawing render-plan orchestration in core", () => {
    const renderPlan = createFlintChartDrawingRenderPlan([
      { kind: "hline", id: "support", price: 22100 },
      {
        kind: "trendline",
        id: "trend",
        p1: { time: 1, price: 22000 },
        p2: { time: 2, price: 22240 },
      },
      {
        kind: "circle",
        id: "circle",
        p1: { time: 10, price: 22000 },
        p2: { time: 20, price: 22200 },
      },
      {
        kind: "fib_extension",
        id: "fib-extension",
        p1: { time: 1, price: 100 },
        p2: { time: 2, price: 200 },
        p3: { time: 3, price: 150 },
      },
      {
        kind: "brush",
        id: "brush",
        points: [
          { time: 4, price: 100 },
          { time: 5, price: 110 },
        ],
      },
      {
        kind: "text",
        id: "note",
        point: { time: 6, price: 22400 },
        label: "Breakout",
      },
      { kind: "hline", id: "hidden", price: 22500, hidden: true },
    ], "trend");

    expect(renderPlan.lineSeries.map((series) => series.drawingId)).toEqual([
      "trend",
      "circle",
      "circle",
      "brush",
    ]);
    expect(renderPlan.lineSeries[0]).toMatchObject({
      drawingId: "trend",
      data: [
        { time: 1, value: 22000 },
        { time: 2, value: 22240 },
      ],
      options: expect.objectContaining({ priceScaleId: "right" }),
    });
    expect(renderPlan.lineSeries[3]).toMatchObject({
      drawingId: "brush",
      data: [
        { time: 4, value: 100 },
        { time: 5, value: 110 },
      ],
    });

    expect(renderPlan.priceLines).toHaveLength(1 + FLINT_CHART_FIB_EXTENSION_LEVELS.length);
    expect(renderPlan.priceLines[0]).toEqual(expect.objectContaining({
      drawingId: "support",
      priceLine: expect.objectContaining({ price: 22100 }),
    }));
    expect(renderPlan.priceLines.slice(1).map((entry) => entry.drawingId))
      .toEqual(Array.from({ length: FLINT_CHART_FIB_EXTENSION_LEVELS.length }, () => "fib-extension"));

    expect(renderPlan.markers).toEqual([
      expect.objectContaining({ text: "Breakout", time: 6, price: 22400 }),
      expect.objectContaining({ text: "1", time: 1, price: 22000 }),
      expect.objectContaining({ text: "2", time: 2, price: 22240 }),
    ]);
  });

  it("centralises drawing render-plan diffing for stable runtime reconciliation", () => {
    const previousPlan = createFlintChartDrawingRenderPlan([
      { kind: "hline", id: "support", price: 22100 },
      {
        kind: "trendline",
        id: "trend",
        p1: { time: 1, price: 22000 },
        p2: { time: 2, price: 22240 },
      },
      {
        kind: "brush",
        id: "brush",
        points: [
          { time: 4, price: 100 },
          { time: 5, price: 110 },
        ],
      },
      {
        kind: "text",
        id: "note",
        point: { time: 6, price: 22400 },
        label: "Breakout",
      },
    ]);
    const nextPlan = createFlintChartDrawingRenderPlan([
      { kind: "hline", id: "support", price: 22100 },
      { kind: "hline", id: "resistance", price: 22500 },
      {
        kind: "trendline",
        id: "trend",
        p1: { time: 1, price: 22000 },
        p2: { time: 2, price: 22300 },
      },
      {
        kind: "text",
        id: "note",
        point: { time: 6, price: 22400 },
        label: "Breakout watch",
      },
    ]);

    const diff = createFlintChartDrawingRenderPlanDiff(previousPlan, nextPlan);

    expect(diff.lineSeries.unchanged.map((entry) => entry.key)).toEqual([]);
    expect(diff.lineSeries.updated.map((entry) => entry.key)).toEqual(["trend:line:0"]);
    expect(diff.lineSeries.removed.map((entry) => entry.key)).toEqual(["brush:line:0"]);
    expect(diff.lineSeries.added.map((entry) => entry.key)).toEqual([]);

    expect(diff.priceLines.unchanged.map((entry) => entry.key)).toEqual(["support:price:0"]);
    expect(diff.priceLines.added.map((entry) => entry.key)).toEqual(["resistance:price:0"]);
    expect(diff.priceLines.removed.map((entry) => entry.key)).toEqual([]);

    expect(diff.markersChanged).toBe(true);
    expect(diff.markers).toEqual([
      expect.objectContaining({ text: "Breakout watch", time: 6, price: 22400 }),
    ]);
  });

  it("persists drawing styles and applies them to core render specs", () => {
    const encoded = JSON.stringify({
      version: 1,
      drawings: [
        {
          kind: "trendline",
          id: "trend",
          p1: { time: 1, price: 22000 },
          p2: { time: 2, price: 22240 },
          style: { color: "#14b8a6", lineWidth: 3, lineStyle: "dotted" },
        },
        {
          kind: "hline",
          id: "bad-style",
          price: 22100,
          style: { color: "not-a-colour", lineWidth: 99, lineStyle: "scribble" },
        },
      ],
    });

    expect(parseFlintChartDrawings<number>(encoded)).toEqual([
      {
        kind: "trendline",
        id: "trend",
        p1: { time: 1, price: 22000 },
        p2: { time: 2, price: 22240 },
        style: { color: "#14b8a6", lineWidth: 3, lineStyle: "dotted" },
      },
      { kind: "hline", id: "bad-style", price: 22100 },
    ]);

    expect(createFlintChartLineDrawingSeriesOptions({
      kind: "trendline",
      id: "trend",
      p1: { time: 1, price: 22000 },
      p2: { time: 2, price: 22240 },
      style: { color: "#14b8a6", lineWidth: 3, lineStyle: "dotted" },
    })).toMatchObject({
      color: "#14b8a6",
      lineWidth: 3,
      lineStyle: 1,
    });

    expect(createFlintChartHLinePriceLine({
      kind: "hline",
      id: "support",
      price: 22100,
      style: { color: "#ef4444", lineWidth: 4, lineStyle: "solid" },
    })).toMatchObject({
      color: "#ef4444",
      lineWidth: 4,
      lineStyle: 0,
    });

    expect(createFlintChartTextMarker({
      kind: "text",
      id: "note",
      point: { time: 3, price: 22320 },
      label: "Breakout",
      style: { color: "#22c55e", lineWidth: 2, lineStyle: "dashed" },
    })).toMatchObject({ color: "#22c55e" });
  });

  it("centralises drawing selection summaries and deletion semantics in core", () => {
    const drawings = [
      { kind: "hline" as const, id: "support", price: 22100 },
      {
        kind: "trendline" as const,
        id: "trend",
        p1: { time: 1, price: 22000 },
        p2: { time: 2, price: 22240 },
      },
      {
        kind: "text" as const,
        id: "note",
        point: { time: 3, price: 22320 },
        label: "Breakout",
      },
      {
        kind: "price_label" as const,
        id: "price",
        point: { time: 4, price: 22440 },
      },
      {
        kind: "callout" as const,
        id: "callout",
        point: { time: 5, price: 22500 },
        label: "Watch",
      },
    ];

    expect(createFlintChartDrawingSummaries(drawings)).toEqual([
      {
        id: "support",
        index: 0,
        kind: "hline",
        label: "Horizontal Line 22,100.00",
        detail: "Price 22,100.00",
        hidden: false,
        locked: false,
      },
      {
        id: "trend",
        index: 1,
        kind: "trendline",
        label: "Trend Line",
        detail: "22,000.00 -> 22,240.00",
        hidden: false,
        locked: false,
      },
      {
        id: "note",
        index: 2,
        kind: "text",
        label: "Text: Breakout",
        detail: "Price 22,320.00",
        hidden: false,
        locked: false,
      },
      {
        id: "price",
        index: 3,
        kind: "price_label",
        label: "Price Label 22,440.00",
        detail: "Price 22,440.00",
        hidden: false,
        locked: false,
      },
      {
        id: "callout",
        index: 4,
        kind: "callout",
        label: "Callout: Watch",
        detail: "Price 22,500.00",
        hidden: false,
        locked: false,
      },
    ]);

    expect(getFlintChartSelectedDrawing(drawings, "trend")).toEqual(drawings[1]);
    expect(getFlintChartSelectedDrawing(drawings, "missing")).toBeNull();
    expect(getFlintChartSelectedDrawing(drawings, null)).toBeNull();

    expect(removeFlintChartDrawingById(drawings, "trend")).toEqual([drawings[0], drawings[2], drawings[3], drawings[4]]);
    expect(removeFlintChartDrawingById(drawings, "missing")).toBe(drawings);
  });

  it("centralises drawing creation and draft progression in core", () => {
    const ids = [
      "support",
      "session-open",
      "trend",
      "extended",
      "circle",
      "channel",
      "fib-extension",
      "long-position",
      "short-position",
      "impulse",
      "correction",
      "measure",
      "price",
      "note",
      "callout",
    ];
    let idIndex = 0;
    const createId = () => ids[idIndex++];
    const p1 = { time: 10, price: 22000 };
    const p2 = { time: 20, price: 22120 };

    expect(advanceFlintChartDrawingDraft({
      tool: "hline",
      point: p1,
      createId,
    })).toEqual({
      status: "created",
      drawing: { kind: "hline", id: "support", price: 22000 },
      pendingPoint: null,
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "vline",
      point: p1,
      createId,
    })).toEqual({
      status: "created",
      drawing: { kind: "vline", id: "session-open", time: 10 },
      pendingPoint: null,
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "trendline",
      point: p1,
      createId,
    })).toEqual({
      status: "pending",
      drawing: null,
      pendingPoint: p1,
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "trendline",
      point: p2,
      pendingPoint: p1,
      createId,
    })).toEqual({
      status: "created",
      drawing: { kind: "trendline", id: "trend", p1, p2 },
      pendingPoint: null,
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "extended_line",
      point: p2,
      pendingPoint: p1,
      createId,
    })).toEqual({
      status: "created",
      drawing: { kind: "extended_line", id: "extended", p1, p2 },
      pendingPoint: null,
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "circle",
      point: p2,
      pendingPoint: p1,
      createId,
    })).toEqual({
      status: "created",
      drawing: { kind: "circle", id: "circle", p1, p2 },
      pendingPoint: null,
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "parallel_channel",
      point: p1,
      createId,
    })).toEqual({
      status: "pending",
      drawing: null,
      pendingPoint: p1,
      pendingPoints: [p1],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "parallel_channel",
      point: p2,
      pendingPoints: [p1],
      createId,
    })).toEqual({
      status: "pending",
      drawing: null,
      pendingPoint: p2,
      pendingPoints: [p1, p2],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "parallel_channel",
      point: { time: 12, price: 22200 },
      pendingPoints: [p1, p2],
      createId,
    })).toEqual({
      status: "created",
      drawing: {
        kind: "parallel_channel",
        id: "channel",
        p1,
        p2,
        p3: { time: 12, price: 22200 },
      },
      pendingPoint: null,
      pendingPoints: [],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "fib_extension",
      point: p1,
      createId,
    })).toEqual({
      status: "pending",
      drawing: null,
      pendingPoint: p1,
      pendingPoints: [p1],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "fib_extension",
      point: p2,
      pendingPoints: [p1],
      createId,
    })).toEqual({
      status: "pending",
      drawing: null,
      pendingPoint: p2,
      pendingPoints: [p1, p2],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "fib_extension",
      point: { time: 30, price: 22100 },
      pendingPoints: [p1, p2],
      createId,
    })).toEqual({
      status: "created",
      drawing: {
        kind: "fib_extension",
        id: "fib-extension",
        p1,
        p2,
        p3: { time: 30, price: 22100 },
      },
      pendingPoint: null,
      pendingPoints: [],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "long_position",
      point: p1,
      createId,
    })).toEqual({
      status: "pending",
      drawing: null,
      pendingPoint: p1,
      pendingPoints: [p1],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "long_position",
      point: { time: 30, price: 22400 },
      pendingPoints: [p1],
      createId,
    })).toEqual({
      status: "pending",
      drawing: null,
      pendingPoint: { time: 30, price: 22400 },
      pendingPoints: [p1, { time: 30, price: 22400 }],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "long_position",
      point: { time: 40, price: 21800 },
      pendingPoints: [p1, { time: 30, price: 22400 }],
      createId,
    })).toEqual({
      status: "created",
      drawing: {
        kind: "long_position",
        id: "long-position",
        p1,
        p2: { time: 30, price: 22400 },
        p3: { time: 40, price: 21800 },
      },
      pendingPoint: null,
      pendingPoints: [],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "short_position",
      point: p1,
      createId,
    })).toEqual({
      status: "pending",
      drawing: null,
      pendingPoint: p1,
      pendingPoints: [p1],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "short_position",
      point: { time: 30, price: 21600 },
      pendingPoints: [p1],
      createId,
    })).toEqual({
      status: "pending",
      drawing: null,
      pendingPoint: { time: 30, price: 21600 },
      pendingPoints: [p1, { time: 30, price: 21600 }],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "short_position",
      point: { time: 40, price: 22300 },
      pendingPoints: [p1, { time: 30, price: 21600 }],
      createId,
    })).toEqual({
      status: "created",
      drawing: {
        kind: "short_position",
        id: "short-position",
        p1,
        p2: { time: 30, price: 21600 },
        p3: { time: 40, price: 22300 },
      },
      pendingPoint: null,
      pendingPoints: [],
      awaitingText: null,
    });

    const impulsePoints = [
      p1,
      p2,
      { time: 30, price: 22300 },
      { time: 40, price: 22100 },
      { time: 50, price: 22500 },
      { time: 60, price: 22350 },
    ];
    expect(advanceFlintChartDrawingDraft({
      tool: "elliott_impulse",
      point: impulsePoints[0],
      createId,
    })).toEqual({
      status: "pending",
      drawing: null,
      pendingPoint: impulsePoints[0],
      pendingPoints: [impulsePoints[0]],
      awaitingText: null,
    });
    expect(advanceFlintChartDrawingDraft({
      tool: "elliott_impulse",
      point: impulsePoints[5],
      pendingPoints: impulsePoints.slice(0, 5),
      createId,
    })).toEqual({
      status: "created",
      drawing: {
        kind: "elliott_impulse",
        id: "impulse",
        points: impulsePoints,
      },
      pendingPoint: null,
      pendingPoints: [],
      awaitingText: null,
    });

    const correctionPoints = [
      p1,
      { time: 30, price: 22400 },
      { time: 40, price: 22100 },
      { time: 50, price: 22550 },
    ];
    expect(advanceFlintChartDrawingDraft({
      tool: "elliott_correction",
      point: correctionPoints[3],
      pendingPoints: correctionPoints.slice(0, 3),
      createId,
    })).toEqual({
      status: "created",
      drawing: {
        kind: "elliott_correction",
        id: "correction",
        points: correctionPoints,
      },
      pendingPoint: null,
      pendingPoints: [],
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "measure",
      point: p2,
      pendingPoint: p1,
      createId,
    })).toEqual({
      status: "created",
      drawing: { kind: "measure", id: "measure", p1, p2 },
      pendingPoint: null,
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "price_label",
      point: p2,
      createId,
    })).toEqual({
      status: "created",
      drawing: { kind: "price_label", id: "price", point: p2 },
      pendingPoint: null,
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "text",
      point: p1,
      createId,
    })).toEqual({
      status: "awaiting-text",
      drawing: null,
      pendingPoint: null,
      awaitingText: p1,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "text",
      point: p1,
      label: " Breakout ",
      createId,
    })).toEqual({
      status: "created",
      drawing: { kind: "text", id: "note", point: p1, label: "Breakout" },
      pendingPoint: null,
      awaitingText: null,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "callout",
      point: p2,
      createId,
    })).toEqual({
      status: "awaiting-text",
      drawing: null,
      pendingPoint: null,
      awaitingText: p2,
    });

    expect(advanceFlintChartDrawingDraft({
      tool: "callout",
      point: p2,
      label: " Watch ",
      createId,
    })).toEqual({
      status: "created",
      drawing: { kind: "callout", id: "callout", point: p2, label: "Watch" },
      pendingPoint: null,
      awaitingText: null,
    });

    expect(idIndex).toBe(ids.length);
  });

  it("creates measure drawing readouts in core", () => {
    const drawing = {
      kind: "measure" as const,
      id: "measure",
      p1: { time: 10, price: 22000 },
      p2: { time: 15, price: 22550 },
    };

    expect(createFlintChartLineDrawingSeriesOptions(drawing)).toMatchObject({
      color: "#22c55e",
      lineStyle: 1,
      priceLineVisible: false,
    });
    expect(createFlintChartLineDrawingData(drawing)).toEqual([
      { time: 10, value: 22000 },
      { time: 15, value: 22550 },
    ]);
    expect(createFlintChartMeasureMarker(drawing)).toMatchObject({
      time: 15,
      price: 22550,
      text: "+550.00 (+2.50%) / 5 bars",
    });
  });

  it("updates drawing styles by selected id while preserving drawing order", () => {
    const drawings = [
      { kind: "hline" as const, id: "support", price: 22100 },
      {
        kind: "trendline" as const,
        id: "trend",
        p1: { time: 1, price: 22000 },
        p2: { time: 2, price: 22240 },
      },
    ];

    const styled = updateFlintChartDrawingStyle(drawings, "trend", {
      color: "#14b8a6",
      lineWidth: 3,
      lineStyle: "dashed",
    });

    expect(styled).toEqual([
      drawings[0],
      {
        ...drawings[1],
        style: { color: "#14b8a6", lineWidth: 3, lineStyle: "dashed" },
      },
    ]);
    expect(getFlintChartDrawingStyle(styled[1])).toEqual({
      color: "#14b8a6",
      lineWidth: 3,
      lineStyle: "dashed",
    });
    expect(updateFlintChartDrawingStyle(drawings, "missing", { color: "#ef4444" })).toBe(drawings);
  });

  it("centralises drawing hidden and locked state semantics in core", () => {
    const encoded = JSON.stringify({
      version: 1,
      drawings: [
        { kind: "hline", id: "support", price: 22100, hidden: true },
        {
          kind: "trendline",
          id: "trend",
          p1: { time: 1, price: 22000 },
          p2: { time: 2, price: 22240 },
          locked: true,
        },
      ],
    });

    const drawings = parseFlintChartDrawings<number>(encoded);
    expect(drawings).toEqual([
      { kind: "hline", id: "support", price: 22100, hidden: true },
      {
        kind: "trendline",
        id: "trend",
        p1: { time: 1, price: 22000 },
        p2: { time: 2, price: 22240 },
        locked: true,
      },
    ]);
    expect(getFlintChartVisibleDrawings(drawings)).toEqual([drawings[1]]);

    const hidden = updateFlintChartDrawingsHidden(drawings, true);
    expect(hidden).toEqual([
      { ...drawings[0], hidden: true },
      { ...drawings[1], hidden: true },
    ]);
    expect(getFlintChartVisibleDrawings(hidden)).toEqual([]);

    const locked = updateFlintChartDrawingsLocked(drawings, true);
    expect(locked.every((drawing) => drawing.locked)).toBe(true);
    expect(removeFlintChartDrawingById(locked, "support")).toBe(locked);
    expect(updateFlintChartDrawingStyle(locked, "support", { color: "#14b8a6" })).toBe(locked);
  });

  it("updates selected drawing state by id while preserving order and styles", () => {
    const drawings = [
      {
        kind: "hline" as const,
        id: "support",
        price: 22100,
        style: { color: "#14b8a6" as const, lineWidth: 3 as const, lineStyle: "dashed" as const },
      },
      {
        kind: "trendline" as const,
        id: "trend",
        p1: { time: 10, price: 22000 },
        p2: { time: 20, price: 22100 },
      },
    ];

    const hiddenLocked = updateFlintChartDrawingStateById(drawings, "support", {
      hidden: true,
      locked: true,
    });

    expect(hiddenLocked).toEqual([
      {
        ...drawings[0],
        hidden: true,
        locked: true,
      },
      drawings[1],
    ]);

    expect(updateFlintChartDrawingStateById(hiddenLocked, "support", {
      hidden: false,
      locked: false,
    })).toEqual(drawings);
    expect(updateFlintChartDrawingStateById(drawings, "missing", { hidden: true })).toBe(drawings);
    expect(updateFlintChartDrawingStateById(drawings, "support", {})).toBe(drawings);
  });

  it("centralises drawing canvas hit-testing while ignoring hidden drawings", () => {
    const drawings = [
      { kind: "hline" as const, id: "support", price: 22100 },
      { kind: "hline" as const, id: "hidden-resistance", price: 22200, hidden: true },
      {
        kind: "trendline" as const,
        id: "trend",
        p1: { time: 10, price: 22000 },
        p2: { time: 20, price: 22100 },
      },
      {
        kind: "rect" as const,
        id: "demand-zone",
        p1: { time: 14, price: 22040 },
        p2: { time: 18, price: 22090 },
        locked: true,
      },
      {
        kind: "circle" as const,
        id: "cycle-zone",
        p1: { time: 40, price: 22220 },
        p2: { time: 50, price: 22420 },
      },
    ];

    expect(findFlintChartDrawingHit(drawings, { price: 22103 }, { priceTolerance: 5 })?.id)
      .toBe("support");
    expect(findFlintChartDrawingHit(drawings, { price: 22200 }, { priceTolerance: 8 }))
      .toBeNull();
    expect(findFlintChartDrawingHit(drawings, { time: 15, price: 22050 }, { priceTolerance: 3 })?.id)
      .toBe("trend");
    expect(findFlintChartDrawingHit(drawings, { time: 16, price: 22070 }, { priceTolerance: 1 })?.id)
      .toBe("demand-zone");
    expect(findFlintChartDrawingHit(drawings, { time: 45, price: 22320 }, { priceTolerance: 1 })?.id)
      .toBe("cycle-zone");
    expect(findFlintChartDrawingHit(drawings, { time: 30, price: 22300 }, { priceTolerance: 2 }))
      .toBeNull();
  });

  it("centralises selected drawing price movement while preserving locked drawings", () => {
    const drawings = [
      { kind: "hline" as const, id: "support", price: 22100 },
      {
        kind: "trendline" as const,
        id: "trend",
        p1: { time: 10, price: 22000 },
        p2: { time: 20, price: 22100 },
      },
      {
        kind: "text" as const,
        id: "note",
        point: { time: 12, price: 22040 },
        label: "Breakout",
      },
      {
        kind: "rect" as const,
        id: "locked-zone",
        p1: { time: 14, price: 22040 },
        p2: { time: 18, price: 22090 },
        locked: true,
      },
    ];

    expect(moveFlintChartDrawingByPriceDelta(drawings, "support", 125)).toEqual([
      { kind: "hline", id: "support", price: 22225 },
      drawings[1],
      drawings[2],
      drawings[3],
    ]);
    expect(moveFlintChartDrawingByPriceDelta(drawings, "trend", -50)).toEqual([
      drawings[0],
      {
        kind: "trendline",
        id: "trend",
        p1: { time: 10, price: 21950 },
        p2: { time: 20, price: 22050 },
      },
      drawings[2],
      drawings[3],
    ]);
    expect(moveFlintChartDrawingByPriceDelta(drawings, "note", 10)).toEqual([
      drawings[0],
      drawings[1],
      {
        kind: "text",
        id: "note",
        point: { time: 12, price: 22050 },
        label: "Breakout",
      },
      drawings[3],
    ]);
    expect(moveFlintChartDrawingByPriceDelta(drawings, "locked-zone", 20)).toBe(drawings);
    expect(moveFlintChartDrawingByPriceDelta(drawings, "missing", 20)).toBe(drawings);
    expect(moveFlintChartDrawingByPriceDelta(drawings, "support", Number.NaN)).toBe(drawings);
  });

  it("centralises selected drawing time and price movement in core", () => {
    const drawings = [
      { kind: "vline" as const, id: "event", time: 10 },
      {
        kind: "trendline" as const,
        id: "trend",
        p1: { time: 10, price: 22000 },
        p2: { time: 20, price: 22100 },
      },
      {
        kind: "text" as const,
        id: "note",
        point: { time: 12, price: 22040 },
        label: "Breakout",
      },
      { kind: "hline" as const, id: "support", price: 22100 },
    ];

    expect(moveFlintChartDrawingByDelta(drawings, "event", { timeDelta: 3 })).toEqual([
      { kind: "vline", id: "event", time: 13 },
      drawings[1],
      drawings[2],
      drawings[3],
    ]);
    expect(moveFlintChartDrawingByDelta(drawings, "trend", { timeDelta: 2, priceDelta: -50 })).toEqual([
      drawings[0],
      {
        kind: "trendline",
        id: "trend",
        p1: { time: 12, price: 21950 },
        p2: { time: 22, price: 22050 },
      },
      drawings[2],
      drawings[3],
    ]);
    expect(moveFlintChartDrawingByDelta(drawings, "note", { timeDelta: -1, priceDelta: 10 })).toEqual([
      drawings[0],
      drawings[1],
      {
        kind: "text",
        id: "note",
        point: { time: 11, price: 22050 },
        label: "Breakout",
      },
      drawings[3],
    ]);
    expect(moveFlintChartDrawingByDelta(drawings, "support", { timeDelta: 3 })).toBe(drawings);
    expect(moveFlintChartDrawingByDelta(drawings, "trend", { priceDelta: 0, timeDelta: 0 })).toBe(drawings);
  });

  it("centralises editable endpoint handles for two-point drawings", () => {
    const drawings = [
      {
        kind: "trendline" as const,
        id: "trend",
        p1: { time: 10, price: 22000 },
        p2: { time: 20, price: 22100 },
      },
      {
        kind: "rect" as const,
        id: "locked-zone",
        p1: { time: 14, price: 22040 },
        p2: { time: 18, price: 22090 },
        locked: true,
      },
      { kind: "hline" as const, id: "support", price: 22100 },
    ];

    expect(findFlintChartDrawingHandleHit(
      drawings,
      "trend",
      { time: 20.4, price: 22103 },
      { timeTolerance: 1, priceTolerance: 5 },
    )).toMatchObject({
      drawingId: "trend",
      handle: "p2",
      time: 20,
      price: 22100,
    });
    expect(findFlintChartDrawingHandleHit(
      drawings,
      "trend",
      { time: 15, price: 22050 },
      { timeTolerance: 1, priceTolerance: 5 },
    )).toBeNull();
    expect(findFlintChartDrawingHandleHit(
      drawings,
      "locked-zone",
      { time: 14, price: 22040 },
      { timeTolerance: 1, priceTolerance: 5 },
    )).toBeNull();

    expect(moveFlintChartDrawingHandleByDelta(drawings, "trend", "p2", { timeDelta: 2, priceDelta: 125 }))
      .toEqual([
        {
          kind: "trendline",
          id: "trend",
          p1: { time: 10, price: 22000 },
          p2: { time: 22, price: 22225 },
        },
        drawings[1],
        drawings[2],
      ]);
    expect(moveFlintChartDrawingHandleByDelta(drawings, "trend", "p1", { priceDelta: -50 }))
      .toEqual([
        {
          kind: "trendline",
          id: "trend",
          p1: { time: 10, price: 21950 },
          p2: { time: 20, price: 22100 },
        },
        drawings[1],
        drawings[2],
      ]);
    expect(moveFlintChartDrawingHandleByDelta(drawings, "locked-zone", "p1", { priceDelta: 50 })).toBe(drawings);
    expect(moveFlintChartDrawingHandleByDelta(drawings, "support", "p1", { priceDelta: 50 })).toBe(drawings);
  });

  it("centralises indicator catalogue, defaults, and pane layout in the core chart contract", () => {
    expect(FLINT_CHART_INDICATOR_CATEGORIES).toEqual(["Overlays", "Volume", "Oscillators"]);
    expect(FLINT_CHART_DEFAULT_INDICATORS.showVolume).toBe(true);
    expect(FLINT_CHART_DEFAULT_INDICATORS.showRSI).toBe(false);
    expect(FLINT_CHART_DEFAULT_PERIODS).toMatchObject({
      ema1: 20,
      ema2: 50,
      rsi: 14,
      atr: 14,
    });

    const definitionKeys = FLINT_CHART_INDICATOR_DEFINITIONS.map((definition) => definition.key);
    expect(definitionKeys).toContain("showEMA20");
    expect(definitionKeys).toContain("showRSI");
    expect(definitionKeys).toContain("showOI");
    expect(FLINT_CHART_INDICATOR_DEFINITIONS.find((definition) => definition.key === "showBB")?.periods).toEqual([
      { field: "bbPeriod", label: "Period", min: 2, max: 200, step: 1 },
      { field: "bbMult", label: "Mult", min: 0.5, max: 5, step: 0.1 },
    ]);

    const active = {
      ...FLINT_CHART_DEFAULT_INDICATORS,
      showEMA20: true,
      showRSI: true,
      showMACD: true,
      showOBV: true,
    };

    expect(getFlintChartActiveIndicatorCount(active)).toBe(4);
    expect(getFlintChartActiveIndicatorCount(active, { includeDefaultVolume: true })).toBe(5);
    expect(getFlintChartActiveIndicatorCountByCategory(active)).toEqual({
      Overlays: 1,
      Volume: 2,
      Oscillators: 2,
    });

    expect(getFlintChartIndicatorPaneSpec("rsi")).toEqual({
      scaleId: "rsi",
      scaleMargins: { top: 0.75, bottom: 0.05 },
    });
    expect(getFlintChartIndicatorPaneSpec("macd")).toEqual({
      scaleId: "macd",
      scaleMargins: { top: 0.6, bottom: 0.05 },
    });
    expect(getFlintChartIndicatorPaneSpec("oi")).toEqual({
      scaleId: "oi",
      scaleMargins: { top: 0.75, bottom: 0 },
      borderVisible: false,
    });
    expect(getFlintChartIndicatorPaneSpec("right")).toBeNull();
    expect(FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES).toMatchObject({
      rsi: "balanced",
      macd: "balanced",
      oi: "balanced",
    });
    expect(FLINT_CHART_INDICATOR_PANE_SIZE_OPTIONS).toEqual(["compact", "balanced", "expanded"]);
    expect(FLINT_CHART_INDICATOR_PANE_SIZE_LABELS.expanded).toBe("Expanded");
    expect(FLINT_CHART_INDICATOR_PANE_SIZE_SHORT_LABELS.compact).toBe("S");
    expect(FLINT_CHART_INDICATOR_PANE_STRETCH_FACTORS).toEqual({
      compact: 0.75,
      balanced: 1,
      expanded: 1.5,
    });
    expect(FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MIN).toBe(0.5);
    expect(FLINT_CHART_INDICATOR_PANE_STRETCH_FACTOR_MAX).toBe(2.5);

    const lifecyclePlan = createFlintChartIndicatorLifecyclePlan({
      ...FLINT_CHART_DEFAULT_INDICATORS,
      showVolume: false,
      showEMA20: true,
      showRSI: true,
      showMACD: true,
      showOI: true,
    });
    expect(lifecyclePlan.volumeVisible).toBe(false);
    expect(lifecyclePlan.activeKeys).toEqual(["showEMA20", "showOI", "showRSI", "showMACD"]);
    expect(lifecyclePlan.activePriceScaleIds).toEqual(["right", "oi", "rsi", "macd"]);
    expect(lifecyclePlan.paneSpecs).toEqual([
      { scaleId: "oi", scaleMargins: { top: 0.75, bottom: 0 }, borderVisible: false },
      { scaleId: "rsi", scaleMargins: { top: 0.75, bottom: 0.05 } },
      { scaleId: "macd", scaleMargins: { top: 0.6, bottom: 0.05 } },
    ]);
    expect(createFlintChartIndicatorPaneOptions(lifecyclePlan.paneSpecs[0])).toEqual({
      scaleMargins: { top: 0.75, bottom: 0 },
      borderVisible: false,
    });
    expect(createFlintChartIndicatorPaneOptions(lifecyclePlan.paneSpecs[1])).toEqual({
      scaleMargins: { top: 0.75, bottom: 0.05 },
    });

    expect(createFlintChartIndicatorPaneLayoutPlan({
      ...FLINT_CHART_DEFAULT_INDICATORS,
      showRSI: true,
      showMACD: true,
    }, {
      ...FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES,
      macd: "expanded",
    }, {
      macd: 1.8,
    })).toEqual({
      mainPaneIndex: 0,
      mainPaneStretchFactor: 4,
      panes: [
        {
          scaleId: "rsi",
          scaleMargins: { top: 0.75, bottom: 0.05 },
          paneIndex: 1,
          stretchFactor: 1,
        },
        {
          scaleId: "macd",
          scaleMargins: { top: 0.6, bottom: 0.05 },
          paneIndex: 2,
          stretchFactor: 1.8,
        },
      ],
      paneIndexByScaleId: { rsi: 1, macd: 2 },
    });
    expect(createFlintChartIndicatorPaneControls({
      ...FLINT_CHART_DEFAULT_INDICATORS,
      showRSI: true,
      showMACD: true,
    }, {
      ...FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES,
      rsi: "compact",
      macd: "expanded",
    }, {
      macd: 1.8,
    })).toEqual([
      { scaleId: "rsi", label: "RSI", size: "compact", stretchFactor: 0.75, isCustomSize: false },
      { scaleId: "macd", label: "MACD", size: "expanded", stretchFactor: 1.8, isCustomSize: true },
    ]);

    expect(resizeFlintChartIndicatorPaneStretchFactors({
      paneStretchFactors: { macd: 1 },
      scaleId: "macd",
      startStretchFactor: 1,
      deltaPixels: -120,
    })).toMatchObject({ macd: 1.6 });
    expect(resizeFlintChartIndicatorPaneStretchFactors({
      paneStretchFactors: { macd: 1 },
      scaleId: "macd",
      startStretchFactor: 1,
      deltaPixels: 999,
    })).toMatchObject({ macd: 0.5 });
    expect(resizeFlintChartIndicatorPaneStretchFactors({
      paneStretchFactors: { macd: 1 },
      scaleId: "macd",
      startStretchFactor: 1,
      deltaPixels: -999,
    })).toMatchObject({ macd: 2.5 });
  });

  it("persists indicator choices, periods, colours, line styles, and pane sizes through the core settings contract", () => {
    expect(FLINT_CHART_INDICATOR_SETTINGS_STORAGE_KEY).toBe("flinttrade:chart:indicator-settings:v1");
    const defaults = createFlintChartDefaultIndicatorSettings();
    expect(defaults).toMatchObject({
      version: 1,
      indicators: FLINT_CHART_DEFAULT_INDICATORS,
      periods: FLINT_CHART_DEFAULT_PERIODS,
      colors: expect.objectContaining({ showRSI: "#a855f7" }),
      lineStyles: expect.objectContaining({ showRSI: "solid" }),
      paneSizes: expect.objectContaining({ rsi: "balanced", macd: "balanced" }),
      paneStretchFactors: expect.objectContaining({ rsi: 1, macd: 1 }),
    });

    const beforeEncode = Date.now();
    const encoded = encodeFlintChartIndicatorSettings({
      indicators: { ...defaults.indicators, showRSI: true, showEMA20: true },
      periods: { ...defaults.periods, rsi: 21, ema1: 34 },
      colors: { ...defaults.colors, showRSI: "#ef4444", showEMA20: "#14b8a6" },
      lineStyles: { ...defaults.lineStyles, showRSI: "dashed", showEMA20: "dotted" },
      paneSizes: { ...defaults.paneSizes, rsi: "expanded", macd: "compact" },
      paneStretchFactors: { ...defaults.paneStretchFactors, rsi: 1.8, macd: 0.8 },
    });
    const afterEncode = Date.now();
    const parsed = parseFlintChartIndicatorSettings(encoded);

    expect(parsed.indicators).toMatchObject({ showRSI: true, showEMA20: true, showVolume: true });
    expect(parsed.periods).toMatchObject({ rsi: 21, ema1: 34 });
    expect(parsed.colors).toMatchObject({ showRSI: "#ef4444", showEMA20: "#14b8a6" });
    expect(parsed.lineStyles).toMatchObject({ showRSI: "dashed", showEMA20: "dotted" });
    expect(parsed.paneSizes).toMatchObject({ rsi: "expanded", macd: "compact" });
    expect(parsed.paneStretchFactors).toMatchObject({ rsi: 1.8, macd: 0.8 });
    expect(parsed.updatedAt).toBeGreaterThanOrEqual(beforeEncode);
    expect(parsed.updatedAt).toBeLessThanOrEqual(afterEncode);

    expect(parseFlintChartIndicatorSettings("{bad json")).toEqual(defaults);
    expect(parseFlintChartIndicatorSettings({
      indicators: { showMACD: true, badKey: true },
      periods: { ema1: 55, rsi: Number.NaN },
      colors: { showEMA20: "#38bdf8", showRSI: "not-a-colour" },
      lineStyles: { showEMA20: "dashed", showRSI: "scribble" },
      paneSizes: { macd: "expanded", rsi: "giant", right: "compact" },
      paneStretchFactors: { macd: 2.25, rsi: 99, right: 1.4 },
    })).toMatchObject({
      indicators: { ...FLINT_CHART_DEFAULT_INDICATORS, showMACD: true },
      periods: { ...FLINT_CHART_DEFAULT_PERIODS, ema1: 55 },
      colors: { ...defaults.colors, showEMA20: "#38bdf8" },
      lineStyles: { ...defaults.lineStyles, showEMA20: "dashed" },
      paneSizes: { ...defaults.paneSizes, macd: "expanded" },
      paneStretchFactors: { ...defaults.paneStretchFactors, macd: 2.25 },
    });

    expect(getFlintChartLineStyleCode("solid")).toBe(0);
    expect(getFlintChartLineStyleCode("dotted")).toBe(1);
    expect(getFlintChartLineStyleCode("dashed")).toBe(2);
  });

  it("centralises chart indicator calculations and render-data builders in core", () => {
    expect(calcEMA([10, 20, 30, 40, 50, 60], 3)).toEqual([null, null, 20, 30, 40, 50]);

    expect(calcRSI([10, 11, 12, 13, 14, 15], 3).values)
      .toEqual([null, null, null, 99.00990099009901, 99.00990099009901, 99.00990099009901]);

    const macdValues = calcMACD(Array.from({ length: 40 }, (_, index) => 100 + index));
    expect(macdValues.macd.some((value) => value !== null)).toBe(true);
    expect(macdValues.signal.some((value) => value !== null)).toBe(true);
    expect(macdValues.hist.some((value) => value !== null)).toBe(true);

    const bars: FlintChartOhlcvBar[] = [
      { timestamp: 1, open: 10, high: 12, low: 8, close: 11, volume: 100 },
      { timestamp: 2, open: 11, high: 14, low: 10, close: 13, volume: 200 },
    ];
    const vwap = calcVWAP(bars, [1, 2]);
    expect(vwap[0]).toBeCloseTo(10.333333333333336, 12);
    expect(vwap[1]).toBeCloseTo(11.666666666666668, 12);

    expect(buildLineData([1, 2, 3], [null, 101, 102])).toEqual([
      { time: 2, value: 101 },
      { time: 3, value: 102 },
    ]);
    expect(buildHistData([1, 2], [15, -5])).toEqual([
      { time: 1, value: 15, color: "rgba(34,197,94,0.6)" },
      { time: 2, value: -5, color: "rgba(239,68,68,0.6)" },
    ]);
  });

  it("centralises indicator series option contracts in core", () => {
    expect(createFlintChartIndicatorLineSeriesOptions({
      key: "showEMA20",
      title: "EMA34",
      color: "#14b8a6",
      lineStyle: "dashed",
      priceScaleId: "right",
    })).toEqual({
      color: "#14b8a6",
      lineStyle: 2,
      lineWidth: 1,
      priceScaleId: "right",
      title: "EMA34",
      lastValueVisible: false,
      priceLineVisible: false,
    });

    expect(createFlintChartIndicatorLineSeriesOptions({
      color: "#facc15",
      lineStyle: 1,
      lineWidth: 2,
      pointMarkersVisible: true,
      priceScaleId: "right",
      title: "SAR",
    })).toEqual({
      color: "#facc15",
      lineStyle: 1,
      lineWidth: 2,
      pointMarkersVisible: true,
      priceScaleId: "right",
      title: "SAR",
      lastValueVisible: false,
      priceLineVisible: false,
    });

    expect(createFlintChartIndicatorHistogramSeriesOptions({
      priceScaleId: "macd",
      title: "MACD Hist",
    })).toEqual({
      priceScaleId: "macd",
      title: "MACD Hist",
      lastValueVisible: false,
      priceLineVisible: false,
    });

    expect(createFlintChartOIOverlaySeriesOptions()).toEqual({
      color: "rgba(99,102,241,0.5)",
      priceFormat: { type: "volume" },
      priceScaleId: "oi",
    });
  });

  it("centralises indicator series render-plan specs in core", () => {
    const renderPlan = createFlintChartIndicatorSeriesRenderPlan({
      colors: {
        ...FLINT_CHART_INDICATOR_DEFAULT_COLORS,
        showEMA20: "#14b8a6",
      },
      indicators: {
        ...FLINT_CHART_DEFAULT_INDICATORS,
        showBB: true,
        showEMA20: true,
        showMACD: true,
      },
      lineStyles: {
        ...FLINT_CHART_INDICATOR_DEFAULT_LINE_STYLES,
        showEMA20: "dashed",
      },
      paneSizes: {
        ...FLINT_CHART_INDICATOR_DEFAULT_PANE_SIZES,
        macd: "expanded",
      },
      periods: {
        ...FLINT_CHART_DEFAULT_PERIODS,
        ema1: 34,
      },
    });

    expect(renderPlan.lineSeries.map((series) => series.refKey)).toEqual([
      "ema20",
      "bbUpper",
      "bbMiddle",
      "bbLower",
      "macdLine",
      "macdSignal",
    ]);
    expect(renderPlan.histogramSeries.map((series) => series.refKey)).toEqual(["macdHist"]);
    expect(renderPlan.lineSeries[0]).toEqual({
      key: "showEMA20:line:ema20",
      indicatorKey: "showEMA20",
      paneIndex: undefined,
      paneScaleId: "right",
      refKey: "ema20",
      options: {
        color: "#14b8a6",
        lineStyle: 2,
        lineWidth: 1,
        priceScaleId: "right",
        title: "EMA34",
        lastValueVisible: false,
        priceLineVisible: false,
      },
    });
    expect(renderPlan.lineSeries.find((series) => series.refKey === "bbUpper")?.options)
      .toMatchObject({ color: "#ef4444", lineStyle: 2, title: "BB Upper" });
    expect(renderPlan.histogramSeries[0]).toEqual({
      key: "showMACD:histogram:macdHist",
      indicatorKey: "showMACD",
      paneIndex: 1,
      paneScaleId: "macd",
      refKey: "macdHist",
      options: {
        priceScaleId: "macd",
        title: "MACD Hist",
        lastValueVisible: false,
        priceLineVisible: false,
      },
    });
    expect(renderPlan.lineSeries.find((series) => series.refKey === "macdSignal")?.paneIndex)
      .toBe(1);
    expect(renderPlan.paneLayoutPlan.panes).toEqual([
      expect.objectContaining({ paneIndex: 1, scaleId: "macd", stretchFactor: 1.5 }),
    ]);
  });

  it("centralises indicator series render-plan diffing in core", () => {
    const previousPlan = createFlintChartIndicatorSeriesRenderPlan({
      colors: FLINT_CHART_INDICATOR_DEFAULT_COLORS,
      indicators: {
        ...FLINT_CHART_DEFAULT_INDICATORS,
        showEMA20: true,
        showEMA50: true,
        showMACD: true,
      },
      lineStyles: FLINT_CHART_INDICATOR_DEFAULT_LINE_STYLES,
      periods: FLINT_CHART_DEFAULT_PERIODS,
    });
    const nextPlan = createFlintChartIndicatorSeriesRenderPlan({
      colors: {
        ...FLINT_CHART_INDICATOR_DEFAULT_COLORS,
        showEMA20: "#14b8a6",
      },
      indicators: {
        ...FLINT_CHART_DEFAULT_INDICATORS,
        showBB: true,
        showEMA20: true,
        showMACD: true,
      },
      lineStyles: {
        ...FLINT_CHART_INDICATOR_DEFAULT_LINE_STYLES,
        showEMA20: "dashed",
      },
      periods: {
        ...FLINT_CHART_DEFAULT_PERIODS,
        ema1: 34,
      },
    });

    const diff = createFlintChartIndicatorSeriesRenderPlanDiff(previousPlan, nextPlan);

    expect(diff.lineSeries.added.map((series) => series.refKey)).toEqual([
      "bbUpper",
      "bbMiddle",
      "bbLower",
    ]);
    expect(diff.lineSeries.updated.map((series) => series.refKey)).toEqual(["ema20"]);
    expect(diff.lineSeries.unchanged.map((series) => series.refKey)).toEqual([
      "macdLine",
      "macdSignal",
    ]);
    expect(diff.lineSeries.removed.map((series) => series.refKey)).toEqual(["ema50"]);
    expect(diff.histogramSeries).toEqual({
      added: [],
      updated: [],
      unchanged: [expect.objectContaining({ refKey: "macdHist" })],
      removed: [],
    });
  });

  it("centralises OI profile overlay bar semantics in core", () => {
    expect(createFlintChartOIProfileBarData({
      latestTime: "2026-06-01",
      totalCeOi: 300,
      totalPeOi: 100,
    })).toEqual({
      color: "rgba(239,68,68,0.55)",
      time: "2026-06-01",
      value: expect.closeTo(66.67, 2),
    });

    expect(createFlintChartOIProfileBarData({
      latestTime: "2026-06-01",
      totalCeOi: 100,
      totalPeOi: 400,
    })).toEqual({
      color: "rgba(34,197,94,0.55)",
      time: "2026-06-01",
      value: 75,
    });

    expect(createFlintChartOIProfileBarData({
      latestTime: "2026-06-01",
      totalCeOi: 0,
      totalPeOi: 0,
    })).toBeNull();
  });

  it("centralises Pivot price-line render specs in core", () => {
    expect(createFlintChartPivotPriceLineSpecs({
      pp: 100,
      r1: 110,
      r2: 120,
      r3: 130,
      s1: 90,
      s2: 80,
      s3: 70,
    })).toEqual([
      { price: 100, color: "#94a3b8", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "PP" },
      { price: 110, color: "#ef4444", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "R1" },
      { price: 120, color: "#f97316", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "R2" },
      { price: 130, color: "#dc2626", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "R3" },
      { price: 90, color: "#22c55e", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "S1" },
      { price: 80, color: "#16a34a", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "S2" },
      { price: 70, color: "#15803d", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "S3" },
    ]);
    expect(createFlintChartPivotPriceLineSpecs(null)).toEqual([]);
  });
});

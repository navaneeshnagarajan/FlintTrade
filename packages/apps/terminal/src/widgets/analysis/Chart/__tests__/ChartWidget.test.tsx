/**
 * ChartWidget.test.tsx
 *
 * Smoke tests for the ChartWidget wrapper component.
 * lightweight-charts is a canvas library that cannot render in jsdom,
 * so we mock it and verify the React wrapper elements.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import type { Dispatch, SetStateAction } from "react";
import type { IDockviewPanelProps } from "dockview-react";
import { ohlcvCacheKey } from "@/lib/chartCache";

// ---------------------------------------------------------------------------
// Mocks — must be declared before the component import
// ---------------------------------------------------------------------------

// lightweight-charts — canvas library, returns stubs
vi.mock("lightweight-charts", () => ({
  createChart: () => ({
    addCandlestickSeries: () => ({
      setData: vi.fn(),
      applyOptions: vi.fn(),
    }),
    addHistogramSeries: () => ({
      setData: vi.fn(),
      applyOptions: vi.fn(),
    }),
    timeScale: () => ({
      fitContent: vi.fn(),
      subscribeVisibleTimeRangeChange: vi.fn(),
    }),
    subscribeCrosshairMove: vi.fn(),
    applyOptions: vi.fn(),
    resize: vi.fn(),
    remove: vi.fn(),
  }),
  CrosshairMode: { Normal: 0 },
  LineStyle: { Solid: 0, Dashed: 1, Dotted: 2 },
  ColorType: { Solid: "solid" },
}));

const drawingToolMocks = vi.hoisted(() => ({
  toggleDrawMode: vi.fn(),
  clearAllDrawings: vi.fn(),
  undoLastDrawing: vi.fn(),
  lastOptions: null as null | {
    setDrawings: Dispatch<SetStateAction<unknown[]>>;
    onDrawingCreated?: (drawingId: string) => void;
    onDrawingHit?: (drawingId: string | null) => void;
    onDrawingMove?: (drawingId: string, delta: { priceDelta?: number; timeDelta?: number }) => void;
    onDrawingHandleMove?: (
      drawingId: string,
      handle: "p1" | "p2",
      delta: { priceDelta?: number; timeDelta?: number },
    ) => void;
  },
}));

const indicatorHookMocks = vi.hoisted(() => ({
  refresh: vi.fn(),
}));

const chartInitMocks = vi.hoisted(() => {
  let ready = false;
  const timeScale = {
    fitContent: vi.fn(),
    setVisibleLogicalRange: vi.fn(),
    subscribeVisibleLogicalRangeChange: vi.fn(),
    unsubscribeVisibleLogicalRangeChange: vi.fn(),
    setVisibleRange: vi.fn(),
    subscribeVisibleTimeRangeChange: vi.fn(),
    unsubscribeVisibleTimeRangeChange: vi.fn(),
  };
  const chart = {
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => timeScale),
  };
  const candleSeries = {
    applyOptions: vi.fn(),
    setData: vi.fn(),
  };
  const volumeSeries = {
    applyOptions: vi.fn(),
    setData: vi.fn(),
  };
  const containerRef = { current: document.createElement("div") };
  const chartRef = { current: null as typeof chart | null };
  const candleRef = { current: null as typeof candleSeries | null };
  const volumeRef = { current: null as typeof volumeSeries | null };
  const markersPluginRef = { current: null };
  const indRef = { current: {} };
  const refs = { containerRef, chartRef, candleRef, volumeRef, markersPluginRef, indRef };

  return {
    candleSeries,
    chart,
    reset: () => {
      ready = false;
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      vi.clearAllMocks();
    },
    setReady: (next: boolean) => {
      ready = next;
      chartRef.current = ready ? chart : null;
      candleRef.current = ready ? candleSeries : null;
      volumeRef.current = ready ? volumeSeries : null;
    },
    timeScale,
    volumeSeries,
    refs: () => refs,
  };
});

// Mock local chart hooks that touch the canvas
vi.mock("../useChartInit", () => ({
  useChartInit: () => chartInitMocks.refs(),
}));

vi.mock("../useDrawingTools", () => ({
  useDrawingTools: (options: typeof drawingToolMocks.lastOptions) => {
    drawingToolMocks.lastOptions = options;
    return drawingToolMocks;
  },
}));

vi.mock("../useIndicators", () => ({
  useIndicators: vi.fn(() => ({ refresh: indicatorHookMocks.refresh })),
}));

const replayMocks = vi.hoisted(() => ({
  exitReplay: vi.fn(),
  enterReplay: vi.fn(),
  pause: vi.fn(),
  play: vi.fn(),
  reset: vi.fn(),
  seek: vi.fn(),
  setSpeed: vi.fn(),
}));

vi.mock("../useChartReplay", () => ({
  useChartReplay: () => ({
    isReplaying: false,
    isPlaying: false,
    replayIndex: 0,
    replaySpeed: 1,
    totalBars: 0,
    ...replayMocks,
  }),
}));

const apiMocks = vi.hoisted(() => ({
  getHistory: vi.fn<(...args: unknown[]) => Promise<unknown[]>>(() => Promise.resolve([])),
  getQuotes: vi.fn(() => Promise.resolve({})),
}));

// Services — prevent real API calls
vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn(() => Promise.resolve([])),
  getHistory: apiMocks.getHistory,
  getQuotes: apiMocks.getQuotes,
  getIntervals: vi.fn(() => Promise.resolve([])),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

const dataScopeState = vi.hoisted(() => ({ value: "explore:mock" }));
vi.mock("@/hooks/useDataScope", () => ({
  useDataScope: () => dataScopeState.value,
}));

// Chart sync bus — the widget must not touch it at all without a syncGroup
// param, so the mock doubles as a tripwire for that guarantee.
const chartSyncMocks = vi.hoisted(() => ({
  subscribeChartSync: vi.fn<(
    group: string,
    id: string,
    cb: (range: { from: number; to: number }) => void,
  ) => () => void>(),
  publishChartSync: vi.fn(),
}));

vi.mock("@/lib/chartSyncBus", () => ({
  subscribeChartSync: chartSyncMocks.subscribeChartSync,
  publishChartSync: chartSyncMocks.publishChartSync,
}));

// Option-leg resolution — mocked at the helper boundary; the helper itself is
// unit-tested in src/lib/__tests__/optionLegSymbols.test.ts.
const optionLegMocks = vi.hoisted(() => ({
  resolveOptionLeg: vi.fn<(request: { underlying: string; leg: "CE" | "PE" }) => Promise<{
    symbol: string;
    exchange: string;
    strike: string;
    expiry: string;
  }>>(),
}));

vi.mock("@/lib/optionLegSymbols", () => ({
  resolveOptionLeg: optionLegMocks.resolveOptionLeg,
}));

vi.mock("@/hooks/useChartTheme", () => ({
  useLightweightChartTheme: () => ({
    candle: {
      borderDownColor: "#ef4444",
      borderUpColor: "#22c55e",
      downColor: "#ef4444",
      upColor: "#22c55e",
      wickDownColor: "#ef4444",
      wickUpColor: "#22c55e",
    },
    crosshair: {
      doNotSnapToHiddenSeriesIndices: true,
      horzLine: {
        color: "#38bdf8",
        labelBackgroundColor: "#38bdf8",
        labelVisible: true,
        style: 2,
        visible: true,
        width: 1,
      },
      mode: 0,
      vertLine: {
        color: "#38bdf8",
        labelBackgroundColor: "#38bdf8",
        labelVisible: true,
        style: 2,
        visible: true,
        width: 1,
      },
    },
    grid: {
      horzLines: { color: "#1f2937", style: 1, visible: true },
      vertLines: { color: "#1f2937", style: 1, visible: true },
    },
    handleScale: {
      axisDoubleClickReset: { price: true, time: true },
      axisPressedMouseMove: { price: true, time: true },
      mouseWheel: true,
      pinch: true,
    },
    handleScroll: {
      horzTouchDrag: true,
      mouseWheel: true,
      pressedMouseMove: true,
      vertTouchDrag: false,
    },
    kineticScroll: { mouse: true, touch: true },
    layout: {
      background: { color: "#000" },
      fontFamily: "system-ui",
      fontSize: 11,
      panes: {
        enableResize: true,
        separatorColor: "#1f2937",
        separatorHoverColor: "#38bdf8",
      },
      textColor: "#fff",
    },
    rightPriceScale: {
      autoScale: true,
      borderColor: "#1f2937",
      borderVisible: true,
      ensureEdgeTickMarksVisible: true,
      entireTextOnly: true,
      minimumWidth: 72,
      scaleMargins: { bottom: 0.14, top: 0.08 },
      textColor: "#fff",
      tickMarkDensity: 2.5,
      ticksVisible: true,
    },
    timeScale: {
      allowShiftVisibleRangeOnWhitespaceReplacement: true,
      barSpacing: 7,
      borderColor: "#1f2937",
      borderVisible: true,
      fixLeftEdge: false,
      fixRightEdge: false,
      lockVisibleTimeRangeOnResize: true,
      maxBarSpacing: 28,
      minBarSpacing: 2,
      rightBarStaysOnScroll: true,
      rightOffset: 8,
      secondsVisible: false,
      shiftVisibleRangeOnNewBar: true,
      tickMarkMaxCharacterLength: 10,
      ticksVisible: true,
      timeVisible: true,
      visible: true,
    },
    trackingMode: { exitMode: 1 },
    volume: {
      color: "#64748b",
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    },
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { createStore, Provider } from "jotai";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import ChartWidget from "../ChartWidget";
import { useIndicators } from "../useIndicators";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ChartWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    chartInitMocks.reset();
    indicatorHookMocks.refresh.mockClear();
    drawingToolMocks.toggleDrawMode.mockClear();
    drawingToolMocks.clearAllDrawings.mockClear();
    drawingToolMocks.undoLastDrawing.mockClear();
    drawingToolMocks.lastOptions = null;
    dataScopeState.value = "explore:mock";
    apiMocks.getHistory.mockReset();
    apiMocks.getHistory.mockResolvedValue([]);
    apiMocks.getQuotes.mockReset();
    apiMocks.getQuotes.mockResolvedValue({});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders without crashing", () => {
    const { container } = render(<ChartWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the chart container div", () => {
    render(<ChartWidget />);
    const chartArea = document.querySelector('[data-tour-target="chart"]');
    expect(chartArea).toBeInTheDocument();
  });

  it("labels Explore OHLCV as sample history", () => {
    render(<ChartWidget />);
    expect(screen.getByText("Sample history")).toBeInTheDocument();
  });

  it("refreshes the quote when the account data scope changes", async () => {
    const view = render(<ChartWidget />);
    await waitFor(() => expect(apiMocks.getQuotes).toHaveBeenCalledTimes(1));

    dataScopeState.value = "live:openalgo:default";
    view.rerender(<ChartWidget params={{}} />);

    await waitFor(() => expect(apiMocks.getQuotes).toHaveBeenCalledTimes(2));
  });

  it("clears stale candles and quotes before loading a new data scope", async () => {
    chartInitMocks.setReady(true);
    apiMocks.getHistory
      .mockResolvedValueOnce([{
        timestamp: "2026-07-11",
        open: 100,
        high: 103,
        low: 99,
        close: 102,
        volume: 10,
      }])
      .mockResolvedValueOnce([]);
    apiMocks.getQuotes
      .mockResolvedValueOnce({ ltp: 101.25, close: 100 })
      .mockReturnValueOnce(new Promise(() => {}));

    const view = render(<ChartWidget />);

    await waitFor(() => {
      expect(chartInitMocks.candleSeries.setData).toHaveBeenLastCalledWith([
        expect.objectContaining({ close: 102 }),
      ]);
    });
    expect(await screen.findByText("101.25")).toBeInTheDocument();

    dataScopeState.value = "live:openalgo:new-connection";
    view.rerender(<ChartWidget params={{ dataScope: dataScopeState.value }} />);

    await waitFor(() => expect(apiMocks.getHistory).toHaveBeenCalledTimes(2));
    expect(chartInitMocks.candleSeries.setData).toHaveBeenLastCalledWith([]);
    expect(chartInitMocks.volumeSeries.setData).toHaveBeenLastCalledWith([]);
    await waitFor(() => expect(screen.queryByText("101.25")).not.toBeInTheDocument());
  });

  it("switches drawing tools to a horizontal rail when the chart workspace narrows", async () => {
    let resizeCallback: ResizeObserverCallback | null = null;
    vi.stubGlobal(
      "ResizeObserver",
      class ResizeObserver {
        constructor(callback: ResizeObserverCallback) {
          resizeCallback = callback;
        }
        observe = vi.fn();
        disconnect = vi.fn();
        unobserve = vi.fn();
      },
    );

    render(<ChartWidget />);

    const workspace = screen.getByLabelText("Interactive chart workspace");
    expect(screen.getByRole("toolbar", { name: "Drawing tools" }))
      .toHaveAttribute("aria-orientation", "vertical");

    act(() => {
      resizeCallback?.([
        { contentRect: { width: 420, height: 700 } } as ResizeObserverEntry,
      ], {} as ResizeObserver);
    });

    await waitFor(() => {
      expect(workspace).toHaveAttribute("data-chart-layout", "compact");
      expect(screen.getByRole("toolbar", { name: "Drawing tools" }))
        .toHaveAttribute("aria-orientation", "horizontal");
    });
  });

  it("has a symbol search input", () => {
    render(<ChartWidget />);
    const searchInput = screen.getByPlaceholderText("Search symbol...");
    expect(searchInput).toBeInTheDocument();
  });

  it("uses shared chart keyboard shortcuts without stealing typing-field keys", () => {
    render(<ChartWidget />);

    const chartWorkspace = screen.getByLabelText("Interactive chart workspace");
    fireEvent.keyDown(chartWorkspace, { key: "2" });
    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("trendline");

    fireEvent.keyDown(chartWorkspace, { key: "Backspace" });
    expect(drawingToolMocks.undoLastDrawing).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(screen.getByPlaceholderText("Search symbol..."), { key: "2" });
    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledTimes(1);
  });

  it("enables the Measure drawing tool from the prediction group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Expand prediction tools" }));
    const menu = screen.getByRole("menu");
    const measureButton = within(menu).getByRole("button", { name: "Measure" });

    expect(measureButton).toBeEnabled();
    await user.click(measureButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("measure");
  });

  it("enables the Long and Short Position drawing tools from the prediction group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Expand prediction tools" }));
    const menu = screen.getByRole("menu");
    const longButton = within(menu).getByRole("button", { name: "Long Position" });
    const shortButton = within(menu).getByRole("button", { name: "Short Position" });

    expect(longButton).toBeEnabled();
    expect(shortButton).toBeEnabled();
    await user.click(longButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("long_position");
  });

  it("uses the first implemented prediction tool as the visible group face", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    const longButton = screen.getByRole("button", { name: "Long Position" });

    await user.click(longButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("long_position");
  });

  it("enables Elliott pattern drawing tools from the patterns group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    const elliottFace = screen.getByRole("button", { name: "Elliott Impulse" });
    expect(elliottFace).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Expand patterns tools" }));
    const menu = screen.getByRole("menu");
    const impulseButton = within(menu).getByRole("button", { name: "Elliott Impulse" });
    const correctionButton = within(menu).getByRole("button", { name: "Elliott Correction" });

    expect(impulseButton).toBeEnabled();
    expect(correctionButton).toBeEnabled();
    await user.click(impulseButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("elliott_impulse");
  });

  it("enables the Extended Line drawing tool from the lines group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Expand lines tools" }));
    const extendedLineButton = screen.getByRole("button", { name: "Extended Line" });

    expect(extendedLineButton).toBeEnabled();
    await user.click(extendedLineButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("extended_line");
  });

  it("enables the Parallel Channel drawing tool from the lines group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Expand lines tools" }));
    const parallelChannelButton = screen.getByRole("button", { name: "Parallel Channel" });

    expect(parallelChannelButton).toBeEnabled();
    await user.click(parallelChannelButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("parallel_channel");
  });

  it("enables the Fib Extension drawing tool from the fib group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Expand fib tools" }));
    const fibExtensionButton = screen.getByRole("button", { name: "Fib Extension" });

    expect(fibExtensionButton).toBeEnabled();
    await user.click(fibExtensionButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("fib_extension");
  });

  it("enables the Eraser drawing tool from the cursor group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Expand cursor tools" }));
    const eraserButton = screen.getByRole("button", { name: "Eraser" });

    expect(eraserButton).toBeEnabled();
    await user.click(eraserButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("eraser");
  });

  it("enables the Price Label drawing tool from the text group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Expand text tools" }));
    const priceLabelButton = screen.getByRole("button", { name: "Price Label" });

    expect(priceLabelButton).toBeEnabled();
    await user.click(priceLabelButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("price_label");
  });

  it("enables the Callout drawing tool from the text group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Expand text tools" }));
    const calloutButton = screen.getByRole("button", { name: "Callout" });

    expect(calloutButton).toBeEnabled();
    await user.click(calloutButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("callout");
  });

  it("enables the Circle drawing tool from the shapes group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Expand shapes tools" }));
    const circleButton = screen.getByRole("button", { name: "Circle" });

    expect(circleButton).toBeEnabled();
    await user.click(circleButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("circle");
  });

  it("enables the Brush drawing tool from the shapes group", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Expand shapes tools" }));
    const brushButton = screen.getByRole("button", { name: "Brush" });

    expect(brushButton).toBeEnabled();
    await user.click(brushButton);

    expect(drawingToolMocks.toggleDrawMode).toHaveBeenCalledWith("brush");
  });

  it("hydrates persisted core indicator settings into the chart lifecycle", () => {
    localStorage.setItem(
      "flinttrade:chart:indicator-settings:v1",
      JSON.stringify({
        version: 1,
        indicators: { showRSI: true },
        periods: { rsi: 21 },
        colors: { showRSI: "#ef4444" },
        lineStyles: { showRSI: "dashed" },
        paneSizes: { rsi: "expanded" },
      }),
    );

    render(<ChartWidget />);

    const indicatorsButton = screen.getByRole("button", { name: /Indicators/i });
    expect(indicatorsButton).toHaveTextContent("1");
    expect(vi.mocked(useIndicators)).toHaveBeenCalledWith(
      expect.objectContaining({
        indicators: expect.objectContaining({ showRSI: true }),
        periods: expect.objectContaining({ rsi: 21 }),
        indicatorColors: expect.objectContaining({ showRSI: "#ef4444" }),
        indicatorLineStyles: expect.objectContaining({ showRSI: "dashed" }),
        indicatorPaneSizes: expect.objectContaining({ rsi: "expanded" }),
      }),
    );
  });

  it("persists active oscillator pane sizing from the indicators menu", async () => {
    const user = userEvent.setup();
    localStorage.setItem(
      "flinttrade:chart:indicator-settings:v1",
      JSON.stringify({
        version: 1,
        indicators: { showMACD: true },
        paneSizes: { macd: "balanced" },
      }),
    );

    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: /Indicators/i }));
    expect(screen.getByRole("menu")).toHaveClass("overflow-y-auto");
    await user.click(screen.getByRole("button", { name: "Set MACD pane to Expanded" }));

    await waitFor(() => {
      const encoded = localStorage.getItem("flinttrade:chart:indicator-settings:v1");
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string)).toMatchObject({
        version: 1,
        indicators: expect.objectContaining({ showMACD: true }),
        paneSizes: expect.objectContaining({ macd: "expanded" }),
        paneStretchFactors: expect.objectContaining({ macd: 1.5 }),
      });
    });
  });

  it("persists manual indicator pane drag resizing from the chart surface", async () => {
    localStorage.setItem(
      "flinttrade:chart:indicator-settings:v1",
      JSON.stringify({
        version: 1,
        indicators: { showMACD: true },
        paneSizes: { macd: "balanced" },
        paneStretchFactors: { macd: 1 },
      }),
    );

    render(<ChartWidget />);

    const resizeHandle = screen.getByRole("separator", { name: "Resize MACD pane" });
    fireEvent.pointerDown(resizeHandle, { clientY: 500 });
    fireEvent.pointerMove(window, { clientY: 380 });
    fireEvent.pointerUp(window);

    await waitFor(() => {
      const encoded = localStorage.getItem("flinttrade:chart:indicator-settings:v1");
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string)).toMatchObject({
        version: 1,
        indicators: expect.objectContaining({ showMACD: true }),
        paneStretchFactors: expect.objectContaining({ macd: 1.6 }),
      });
    });
  });

  it("refreshes indicator panes after cached OHLCV bars are applied", async () => {
    chartInitMocks.setReady(true);
    localStorage.setItem(
      ohlcvCacheKey("explore:mock", "NIFTY", "NSE_INDEX", "5m"),
      JSON.stringify({
        timestamp: Date.now(),
        scope: "explore:mock",
        data: [
          { timestamp: 1, open: 100, high: 110, low: 95, close: 108, volume: 1000 },
          { timestamp: 2, open: 108, high: 112, low: 104, close: 106, volume: 1200 },
        ],
      }),
    );

    render(<ChartWidget />);

    await waitFor(() => {
      expect(chartInitMocks.candleSeries.setData).toHaveBeenCalledWith([
        { time: 1, open: 100, high: 110, low: 95, close: 108 },
        { time: 2, open: 108, high: 112, low: 104, close: 106 },
      ]);
      expect(chartInitMocks.volumeSeries.setData).toHaveBeenCalled();
      expect(indicatorHookMocks.refresh).toHaveBeenCalled();
    });
  });

  it("persists core chart display settings from the chart settings menu", async () => {
    const user = userEvent.setup();
    render(<ChartWidget />);

    await user.click(screen.getByRole("button", { name: "Open chart display settings" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Grid" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Crosshair" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Wheel zoom" }));

    await waitFor(() => {
      const encoded = localStorage.getItem("flinttrade:chart:display-settings:v1");
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string)).toMatchObject({
        version: 1,
        gridVisible: false,
        crosshairVisible: false,
        wheelZoom: false,
        dragScroll: true,
      });
    });
  });

  it("deletes the selected persisted drawing before falling back to undo-last", () => {
    localStorage.setItem(
      "flinttrade:drawings:NIFTY:NSE_INDEX",
      JSON.stringify({
        version: 1,
        drawings: [
          { kind: "hline", id: "support", price: 22100 },
          {
            kind: "text",
            id: "note",
            point: { time: 3, price: 22320 },
            label: "Breakout",
          },
        ],
      }),
    );

    render(<ChartWidget />);

    fireEvent.click(screen.getByRole("button", { name: "Select Horizontal Line 22,100.00" }));
    fireEvent.keyDown(screen.getByLabelText("Interactive chart workspace"), { key: "Backspace" });

    expect(screen.queryByRole("button", { name: "Select Horizontal Line 22,100.00" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select Text: Breakout" })).toBeInTheDocument();
    expect(drawingToolMocks.undoLastDrawing).not.toHaveBeenCalled();

    fireEvent.keyDown(screen.getByLabelText("Interactive chart workspace"), { key: "Backspace" });
    expect(drawingToolMocks.undoLastDrawing).toHaveBeenCalledTimes(1);
  });

  it("persists selected drawing style edits through the core drawing contract", async () => {
    localStorage.setItem(
      "flinttrade:drawings:NIFTY:NSE_INDEX",
      JSON.stringify({
        version: 1,
        drawings: [
          { kind: "hline", id: "support", price: 22100 },
        ],
      }),
    );

    render(<ChartWidget />);

    fireEvent.click(screen.getByRole("button", { name: "Select Horizontal Line 22,100.00" }));
    fireEvent.click(screen.getByRole("button", { name: "Set drawing colour teal" }));
    fireEvent.click(screen.getByRole("button", { name: "Set drawing line style dashed" }));
    fireEvent.click(screen.getByRole("button", { name: "Set drawing line width 3" }));

    await waitFor(() => {
      const encoded = localStorage.getItem("flinttrade:drawings:NIFTY:NSE_INDEX");
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string).drawings[0]).toMatchObject({
        id: "support",
        style: { color: "#14b8a6", lineStyle: "dashed", lineWidth: 3 },
      });
    });
  });

  it("selects a newly created drawing so style controls are immediately available", () => {
    render(<ChartWidget />);

    act(() => {
      drawingToolMocks.lastOptions?.setDrawings([
        { kind: "hline", id: "fresh-support", price: 22100 },
      ]);
      drawingToolMocks.lastOptions?.onDrawingCreated?.("fresh-support");
    });

    expect(screen.getByRole("button", { name: "Select Horizontal Line 22,100.00" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Selected drawing style")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set drawing colour amber" }))
      .toHaveAttribute("aria-pressed", "true");
  });

  it("selects and clears drawings reported by the canvas hit-test path", () => {
    localStorage.setItem(
      "flinttrade:drawings:NIFTY:NSE_INDEX",
      JSON.stringify({
        version: 1,
        drawings: [
          { kind: "hline", id: "support", price: 22100 },
        ],
      }),
    );

    render(<ChartWidget />);

    act(() => {
      drawingToolMocks.lastOptions?.onDrawingHit?.("support");
    });

    expect(screen.getByRole("button", { name: "Select Horizontal Line 22,100.00" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Selected drawing style")).toBeInTheDocument();

    act(() => {
      drawingToolMocks.lastOptions?.onDrawingHit?.(null);
    });

    expect(screen.getByRole("button", { name: "Select Horizontal Line 22,100.00" }))
      .toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByLabelText("Selected drawing style")).not.toBeInTheDocument();
  });

  it("moves selected drawings reported by the canvas drag path through core persistence", async () => {
    localStorage.setItem(
      "flinttrade:drawings:NIFTY:NSE_INDEX",
      JSON.stringify({
        version: 1,
        drawings: [
          { kind: "hline", id: "support", price: 22100 },
        ],
      }),
    );

    render(<ChartWidget />);

    act(() => {
      drawingToolMocks.lastOptions?.onDrawingHit?.("support");
      drawingToolMocks.lastOptions?.onDrawingMove?.("support", { priceDelta: 125 });
    });

    expect(screen.getByRole("button", { name: "Select Horizontal Line 22,225.00" }))
      .toHaveAttribute("aria-pressed", "true");

    await waitFor(() => {
      const encoded = localStorage.getItem("flinttrade:drawings:NIFTY:NSE_INDEX");
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string).drawings[0]).toMatchObject({
        id: "support",
        price: 22225,
      });
    });
  });

  it("moves selected two-point drawings in price and time through core persistence", async () => {
    localStorage.setItem(
      "flinttrade:drawings:NIFTY:NSE_INDEX",
      JSON.stringify({
        version: 1,
        drawings: [
          {
            kind: "trendline",
            id: "trend",
            p1: { time: 10, price: 22000 },
            p2: { time: 20, price: 22100 },
          },
        ],
      }),
    );

    render(<ChartWidget />);

    act(() => {
      drawingToolMocks.lastOptions?.onDrawingHit?.("trend");
      drawingToolMocks.lastOptions?.onDrawingMove?.("trend", { priceDelta: 100, timeDelta: 2 });
    });

    expect(screen.getByRole("button", { name: "Select Trend Line" }))
      .toHaveAttribute("aria-pressed", "true");

    await waitFor(() => {
      const encoded = localStorage.getItem("flinttrade:drawings:NIFTY:NSE_INDEX");
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string).drawings[0]).toMatchObject({
        id: "trend",
        p1: { time: 12, price: 22100 },
        p2: { time: 22, price: 22200 },
      });
    });
  });

  it("moves selected two-point drawing endpoints through core persistence", async () => {
    localStorage.setItem(
      "flinttrade:drawings:NIFTY:NSE_INDEX",
      JSON.stringify({
        version: 1,
        drawings: [
          {
            kind: "trendline",
            id: "trend",
            p1: { time: 10, price: 22000 },
            p2: { time: 20, price: 22100 },
          },
        ],
      }),
    );

    render(<ChartWidget />);

    act(() => {
      drawingToolMocks.lastOptions?.onDrawingHit?.("trend");
      drawingToolMocks.lastOptions?.onDrawingHandleMove?.("trend", "p2", { priceDelta: 125, timeDelta: 2 });
    });

    expect(screen.getByRole("button", { name: "Select Trend Line" }))
      .toHaveAttribute("aria-pressed", "true");

    await waitFor(() => {
      const encoded = localStorage.getItem("flinttrade:drawings:NIFTY:NSE_INDEX");
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string).drawings[0]).toMatchObject({
        id: "trend",
        p1: { time: 10, price: 22000 },
        p2: { time: 22, price: 22225 },
      });
    });
  });

  it("wires toolbar lock and hide actions into the persisted core drawing contract", async () => {
    localStorage.setItem(
      "flinttrade:drawings:NIFTY:NSE_INDEX",
      JSON.stringify({
        version: 1,
        drawings: [
          { kind: "hline", id: "support", price: 22100 },
        ],
      }),
    );

    render(<ChartWidget />);

    fireEvent.click(screen.getByRole("button", { name: "Select Horizontal Line 22,100.00" }));
    fireEvent.click(screen.getByRole("button", { name: "Lock drawings" }));

    expect(screen.getAllByText("Locked").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Delete Horizontal Line 22,100.00" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Set drawing colour teal" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Hide drawings" }));
    expect(screen.getAllByText("Hidden").length).toBeGreaterThan(0);

    await waitFor(() => {
      const encoded = localStorage.getItem("flinttrade:drawings:NIFTY:NSE_INDEX");
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string).drawings[0]).toMatchObject({
        id: "support",
        locked: true,
        hidden: true,
      });
    });
  });

  it("wires selected drawing inspector actions into persisted core state", async () => {
    localStorage.setItem(
      "flinttrade:drawings:NIFTY:NSE_INDEX",
      JSON.stringify({
        version: 1,
        drawings: [
          { kind: "hline", id: "support", price: 22100 },
        ],
      }),
    );

    render(<ChartWidget />);

    fireEvent.click(screen.getByRole("button", { name: "Select Horizontal Line 22,100.00" }));
    fireEvent.click(screen.getByRole("button", { name: "Hide Horizontal Line 22,100.00" }));
    fireEvent.click(screen.getByRole("button", { name: "Lock Horizontal Line 22,100.00" }));

    expect(screen.getByText("Selected drawing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unlock Horizontal Line 22,100.00" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show Horizontal Line 22,100.00" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete selected Horizontal Line 22,100.00" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Unlock Horizontal Line 22,100.00" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected Horizontal Line 22,100.00" }));

    await waitFor(() => {
      const encoded = localStorage.getItem("flinttrade:drawings:NIFTY:NSE_INDEX");
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string).drawings).toEqual([]);
    });
  });
});

describe("ChartWidget selection-follow (selectedSymbolAtom)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    chartInitMocks.reset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("follows a watchlist selection written to selectedSymbolAtom", async () => {
    const store = createStore();
    render(
      <Provider store={store}>
        <ChartWidget />
      </Provider>,
    );
    expect(screen.getByText("NIFTY")).toBeInTheDocument();

    act(() => {
      store.set(selectedSymbolAtom, { symbol: "TCS", exchange: "NSE" });
    });

    await waitFor(() => {
      expect(screen.getByText("TCS")).toBeInTheDocument();
    });
    expect(screen.queryByText("NIFTY")).not.toBeInTheDocument();
  });

  it("keeps a pinned chart's instrument when the selection changes", async () => {
    const store = createStore();
    render(
      <Provider store={store}>
        <ChartWidget params={{ symbol: "INFY", exchange: "NSE" }} />
      </Provider>,
    );
    expect(screen.getByText("INFY")).toBeInTheDocument();

    act(() => {
      store.set(selectedSymbolAtom, { symbol: "TCS", exchange: "NSE" });
    });

    // A pinned chart (explicit panel-params symbol) ignores the selection so
    // multi-chart preset layouts are never clobbered by a watchlist click.
    await waitFor(() => {
      expect(store.get(selectedSymbolAtom)).toEqual({ symbol: "TCS", exchange: "NSE" });
    });
    expect(screen.getByText("INFY")).toBeInTheDocument();
    expect(screen.queryByText("TCS")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Per-panel settings scoping
//
// A workspace can hold several chart panels (the Multi Chart preset lays out
// four). Indicator and display settings are therefore keyed by Dockview panel
// id, so one chart's configuration can never overwrite another's.
// ---------------------------------------------------------------------------

describe("ChartWidget per-panel settings scoping", () => {
  const INDICATOR_KEY = "flinttrade:chart:indicator-settings:v1";
  const DISPLAY_KEY = "flinttrade:chart:display-settings:v1";

  function panelProps(id: string): Partial<IDockviewPanelProps> {
    return { api: { id } as unknown as IDockviewPanelProps["api"] };
  }

  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    chartInitMocks.reset();
    indicatorHookMocks.refresh.mockClear();
    dataScopeState.value = "explore:mock";
    apiMocks.getHistory.mockReset();
    apiMocks.getHistory.mockResolvedValue([]);
    apiMocks.getQuotes.mockReset();
    apiMocks.getQuotes.mockResolvedValue({});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("hydrates a panel's own indicator settings in preference to the workspace-wide key", () => {
    localStorage.setItem(
      INDICATOR_KEY,
      JSON.stringify({ version: 1, indicators: { showRSI: true }, periods: { rsi: 21 } }),
    );
    localStorage.setItem(
      `${INDICATOR_KEY}:panel:chart-b`,
      JSON.stringify({ version: 1, indicators: { showMACD: true }, periods: { rsi: 9 } }),
    );

    render(<ChartWidget {...panelProps("chart-b")} />);

    expect(vi.mocked(useIndicators)).toHaveBeenCalledWith(
      expect.objectContaining({
        indicators: expect.objectContaining({ showMACD: true, showRSI: false }),
        periods: expect.objectContaining({ rsi: 9 }),
      }),
    );
  });

  it("inherits the workspace-wide settings the first time a panel is opened", () => {
    localStorage.setItem(
      INDICATOR_KEY,
      JSON.stringify({ version: 1, indicators: { showRSI: true }, periods: { rsi: 21 } }),
    );

    render(<ChartWidget {...panelProps("chart-new")} />);

    expect(vi.mocked(useIndicators)).toHaveBeenCalledWith(
      expect.objectContaining({
        indicators: expect.objectContaining({ showRSI: true }),
        periods: expect.objectContaining({ rsi: 21 }),
      }),
    );
    // The inherited settings become the panel's own from that point on.
    expect(localStorage.getItem(`${INDICATOR_KEY}:panel:chart-new`)).not.toBeNull();
  });

  it("writes indicator settings to the panel key, leaving the sibling panel and workspace default alone", async () => {
    const user = userEvent.setup();
    localStorage.setItem(
      INDICATOR_KEY,
      JSON.stringify({ version: 1, indicators: { showMACD: true }, paneSizes: { macd: "balanced" } }),
    );
    const siblingKey = `${INDICATOR_KEY}:panel:chart-b`;
    const siblingPayload = JSON.stringify({
      version: 1,
      indicators: { showRSI: true },
      paneSizes: { rsi: "compact" },
    });
    localStorage.setItem(siblingKey, siblingPayload);

    render(<ChartWidget {...panelProps("chart-a")} />);

    await user.click(screen.getByRole("button", { name: /Indicators/i }));
    await user.click(screen.getByRole("button", { name: "Set MACD pane to Expanded" }));

    await waitFor(() => {
      const encoded = localStorage.getItem(`${INDICATOR_KEY}:panel:chart-a`);
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string)).toMatchObject({
        version: 1,
        indicators: expect.objectContaining({ showMACD: true }),
        paneSizes: expect.objectContaining({ macd: "expanded" }),
      });
    });

    expect(JSON.parse(localStorage.getItem(INDICATOR_KEY) as string)).toMatchObject({
      paneSizes: expect.objectContaining({ macd: "balanced" }),
    });
    expect(localStorage.getItem(siblingKey)).toBe(siblingPayload);
  });

  it("writes display settings to the panel key and never to the workspace-wide key", async () => {
    const user = userEvent.setup();
    render(<ChartWidget {...panelProps("chart-a")} />);

    await user.click(screen.getByRole("button", { name: "Open chart display settings" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Grid" }));

    await waitFor(() => {
      const encoded = localStorage.getItem(`${DISPLAY_KEY}:panel:chart-a`);
      expect(encoded).not.toBeNull();
      expect(JSON.parse(encoded as string)).toMatchObject({ version: 1, gridVisible: false });
    });
    expect(localStorage.getItem(DISPLAY_KEY)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Same-window time-scale sync (params.syncGroup)
//
// The Three Panel preset lays out three chart panels that scroll and zoom
// together. Without a syncGroup param the chart must never touch the bus —
// pinned below so the sync path can never leak into standalone charts.
// ---------------------------------------------------------------------------

describe("ChartWidget time-scale sync (params.syncGroup)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    chartInitMocks.reset();
    dataScopeState.value = "explore:mock";
    apiMocks.getHistory.mockReset();
    apiMocks.getHistory.mockResolvedValue([]);
    apiMocks.getQuotes.mockReset();
    apiMocks.getQuotes.mockResolvedValue({});
    chartSyncMocks.subscribeChartSync.mockReset();
    chartSyncMocks.subscribeChartSync.mockReturnValue(() => {});
    chartSyncMocks.publishChartSync.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the chart off the sync bus when syncGroup is absent", () => {
    chartInitMocks.setReady(true);
    render(<ChartWidget params={{ symbol: "NIFTY", exchange: "NSE_INDEX" }} />);

    expect(chartSyncMocks.subscribeChartSync).not.toHaveBeenCalled();
    expect(chartSyncMocks.publishChartSync).not.toHaveBeenCalled();
    // Only the pre-existing persistence handler subscribes to range changes —
    // exactly-previous behaviour with no syncGroup, and no time-range
    // subscription at all.
    expect(chartInitMocks.timeScale.subscribeVisibleLogicalRangeChange).toHaveBeenCalledTimes(1);
    expect(chartInitMocks.timeScale.subscribeVisibleTimeRangeChange).not.toHaveBeenCalled();
  });

  it("publishes visible-time-range changes to its sync group", () => {
    chartInitMocks.setReady(true);
    render(<ChartWidget params={{ symbol: "NIFTY", exchange: "NSE_INDEX", syncGroup: "three-panel" }} />);

    expect(chartSyncMocks.subscribeChartSync).toHaveBeenCalledTimes(1);
    const [group, memberId] = chartSyncMocks.subscribeChartSync.mock.calls[0];
    expect(group).toBe("three-panel");

    // The persistence handler stays on the logical-range subscription; the
    // sync publisher rides the time-range subscription so option panels with
    // missing bars stay aligned to the same market interval.
    expect(chartInitMocks.timeScale.subscribeVisibleLogicalRangeChange).toHaveBeenCalledTimes(1);
    const rangeSubscriptions = chartInitMocks.timeScale.subscribeVisibleTimeRangeChange.mock.calls;
    expect(rangeSubscriptions).toHaveLength(1);
    const publishHandler = rangeSubscriptions[0][0] as (range: { from: number; to: number } | null) => void;

    act(() => { publishHandler({ from: 3, to: 40 }); });

    expect(chartSyncMocks.publishChartSync).toHaveBeenCalledExactlyOnceWith(
      "three-panel",
      memberId,
      { from: 3, to: 40 },
    );

    // Null and degenerate ranges are never published.
    act(() => {
      publishHandler(null);
      publishHandler({ from: 10, to: 10 });
    });
    expect(chartSyncMocks.publishChartSync).toHaveBeenCalledTimes(1);
  });

  it("applies a range received from the group without re-publishing it", () => {
    chartInitMocks.setReady(true);
    // Simulate the real chart: setting the visible time range synchronously
    // fires every time-range subscription with the applied range. Without
    // the apply guard this would boomerang straight back onto the bus.
    chartInitMocks.timeScale.setVisibleRange.mockImplementation(
      (range: { from: number; to: number }) => {
        chartInitMocks.timeScale.subscribeVisibleTimeRangeChange.mock.calls.forEach((call) => {
          (call[0] as (r: { from: number; to: number }) => void)(range);
        });
      },
    );

    render(<ChartWidget params={{ symbol: "NIFTY", exchange: "NSE_INDEX", syncGroup: "three-panel" }} />);

    const busListener = chartSyncMocks.subscribeChartSync.mock.calls[0][2];

    act(() => { busListener({ from: 5, to: 55 }); });

    expect(chartInitMocks.timeScale.setVisibleRange).toHaveBeenCalledWith({ from: 5, to: 55 });
    expect(chartSyncMocks.publishChartSync).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Option-leg panels (params.optionLeg)
//
// A preset can pin a chart to "the nearest-expiry ATM CE/PE of an underlying"
// rather than a fixed symbol. Resolution runs at mount via resolveOptionLeg;
// data loading is deferred until it lands, and failure is surfaced honestly.
// ---------------------------------------------------------------------------

describe("ChartWidget option-leg panels (params.optionLeg)", () => {
  const CE_LEG = {
    symbol: "NIFTY30DEC9924800CE",
    exchange: "NFO",
    strike: "24800",
    expiry: "30-DEC-99",
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    chartInitMocks.reset();
    dataScopeState.value = "explore:mock";
    apiMocks.getHistory.mockReset();
    apiMocks.getHistory.mockResolvedValue([]);
    apiMocks.getQuotes.mockReset();
    apiMocks.getQuotes.mockResolvedValue({});
    chartSyncMocks.subscribeChartSync.mockReset();
    chartSyncMocks.subscribeChartSync.mockReturnValue(() => {});
    chartSyncMocks.publishChartSync.mockReset();
    optionLegMocks.resolveOptionLeg.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves the leg at mount and loads only the resolved contract", async () => {
    chartInitMocks.setReady(true);
    optionLegMocks.resolveOptionLeg.mockResolvedValue(CE_LEG);

    render(<ChartWidget params={{ optionLeg: { underlying: "NIFTY", leg: "CE" } }} />);

    expect(optionLegMocks.resolveOptionLeg).toHaveBeenCalledExactlyOnceWith({
      underlying: "NIFTY",
      leg: "CE",
    });
    expect(await screen.findByText("NIFTY30DEC9924800CE")).toBeInTheDocument();

    await waitFor(() => expect(apiMocks.getHistory).toHaveBeenCalled());
    // Every fetch is for the resolved contract — never the placeholder seed.
    for (const call of apiMocks.getHistory.mock.calls) {
      expect(call[0]).toBe("NIFTY30DEC9924800CE");
      expect(call[1]).toBe("NFO");
    }
  });

  it("shows a resolving badge and defers all data fetches while the leg resolves", () => {
    chartInitMocks.setReady(true);
    optionLegMocks.resolveOptionLeg.mockReturnValue(new Promise(() => {}));

    render(<ChartWidget params={{ optionLeg: { underlying: "BANKNIFTY", leg: "PE" } }} />);

    expect(screen.getByText(/Resolving PE leg/)).toBeInTheDocument();
    // The placeholder header shows the underlying, not the workspace default.
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
    expect(apiMocks.getHistory).not.toHaveBeenCalled();
    expect(apiMocks.getQuotes).not.toHaveBeenCalled();
  });

  it("surfaces an honest error and fetches nothing when resolution fails", async () => {
    chartInitMocks.setReady(true);
    optionLegMocks.resolveOptionLeg.mockRejectedValue(
      new Error("No option expiries available for NIFTY"),
    );

    render(<ChartWidget params={{ optionLeg: { underlying: "NIFTY", leg: "CE" } }} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No option expiries available for NIFTY",
    );
    expect(apiMocks.getHistory).not.toHaveBeenCalled();
    expect(apiMocks.getQuotes).not.toHaveBeenCalled();
  });

  it("keeps an option-leg chart pinned against watchlist selection", async () => {
    optionLegMocks.resolveOptionLeg.mockResolvedValue(CE_LEG);
    const store = createStore();
    render(
      <Provider store={store}>
        <ChartWidget params={{ optionLeg: { underlying: "NIFTY", leg: "CE" } }} />
      </Provider>,
    );
    expect(await screen.findByText("NIFTY30DEC9924800CE")).toBeInTheDocument();

    act(() => {
      store.set(selectedSymbolAtom, { symbol: "TCS", exchange: "NSE" });
    });

    await waitFor(() => {
      expect(store.get(selectedSymbolAtom)).toEqual({ symbol: "TCS", exchange: "NSE" });
    });
    expect(screen.getByText("NIFTY30DEC9924800CE")).toBeInTheDocument();
    expect(screen.queryByText("TCS")).not.toBeInTheDocument();
  });
});

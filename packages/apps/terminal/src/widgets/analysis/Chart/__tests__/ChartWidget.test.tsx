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

  return {
    candleSeries,
    chart,
    reset: () => {
      ready = false;
      vi.clearAllMocks();
    },
    setReady: (next: boolean) => {
      ready = next;
    },
    timeScale,
    volumeSeries,
    refs: () => ({
      containerRef: { current: document.createElement("div") },
      chartRef: { current: ready ? chart : null },
      candleRef: { current: ready ? candleSeries : null },
      volumeRef: { current: ready ? volumeSeries : null },
      markersPluginRef: { current: null },
      indRef: { current: {} },
    }),
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

vi.mock("../useChartReplay", () => ({
  useChartReplay: () => ({
    isReplaying: false,
    isPlaying: false,
    replayIndex: 0,
    replaySpeed: 1,
    totalBars: 0,
    play: vi.fn(),
    pause: vi.fn(),
    reset: vi.fn(),
    seek: vi.fn(),
    exitReplay: vi.fn(),
    enterReplay: vi.fn(),
    setSpeed: vi.fn(),
  }),
}));

// Services — prevent real API calls
vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn(() => Promise.resolve([])),
  getHistory: vi.fn(() => Promise.resolve([])),
  getQuotes: vi.fn(() => Promise.resolve({})),
  getIntervals: vi.fn(() => Promise.resolve([])),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
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
      "ft-chart-NIFTY-NSE_INDEX-5m",
      JSON.stringify({
        timestamp: Date.now(),
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

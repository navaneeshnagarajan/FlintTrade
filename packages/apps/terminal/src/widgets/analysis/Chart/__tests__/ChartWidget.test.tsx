/**
 * ChartWidget.test.tsx
 *
 * Smoke tests for the ChartWidget wrapper component.
 * lightweight-charts is a canvas library that cannot render in jsdom,
 * so we mock it and verify the React wrapper elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

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

// Mock local chart hooks that touch the canvas
vi.mock("../useChartInit", () => ({
  useChartInit: () => ({
    containerRef: { current: document.createElement("div") },
    chartRef: { current: null },
    candleRef: { current: null },
    volumeRef: { current: null },
    markersPluginRef: { current: null },
    indRef: { current: {} },
  }),
}));

vi.mock("../useDrawingTools", () => ({
  useDrawingTools: () => ({
    toggleDrawMode: vi.fn(),
    clearAllDrawings: vi.fn(),
    undoLastDrawing: vi.fn(),
  }),
}));

vi.mock("../useIndicators", () => ({
  useIndicators: vi.fn(),
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
    candle: {},
    layout: { background: { type: "solid", color: "#000" }, textColor: "#fff" },
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import ChartWidget from "../ChartWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ChartWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
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

  it("has a symbol search input", () => {
    render(<ChartWidget />);
    const searchInput = screen.getByPlaceholderText("Search symbol...");
    expect(searchInput).toBeInTheDocument();
  });
});

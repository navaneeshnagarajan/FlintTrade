/**
 * ChartGrid.test.tsx
 *
 * Tests for the Multi-Chart Grid widget.
 * lightweight-charts and chart hooks are mocked because they require a real canvas.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("lightweight-charts", () => ({
  createChart: () => ({
    addCandlestickSeries: () => ({
      setData: vi.fn(),
      applyOptions: vi.fn(),
      update: vi.fn(),
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

const chartGridMocks = vi.hoisted(() => ({
  legendCallbacks: [] as Array<(state: unknown) => void>,
}));

vi.mock("../useChartInit", () => ({
  useChartInit: (setLegend: (state: unknown) => void) => {
    chartGridMocks.legendCallbacks.push(setLegend);
    return {
      containerRef: { current: document.createElement("div") },
      chartRef: { current: null },
      candleRef: { current: null },
      volumeRef: { current: null },
      markersPluginRef: { current: null },
      indRef: { current: {} },
    };
  },
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

vi.mock("@/hooks/useChartTheme", () => ({
  useLightweightChartTheme: () => ({
    candle: {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    },
    layout: { background: { type: "solid", color: "#0b0b0f" }, textColor: "#a0a0b0" },
    grid: { vertLines: { color: "#1e1e2e" }, horzLines: { color: "#1e1e2e" } },
    crosshair: {},
    timeScale: {},
  }),
}));

vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn().mockResolvedValue([]),
  getHistory: vi.fn().mockResolvedValue([]),
  getIntervals: vi.fn().mockResolvedValue({ intervals: ["1m", "5m", "15m", "1h", "1D"] }),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: vi.fn().mockReturnValue(false),
}));

import ChartGrid from "../ChartGrid";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ChartGrid", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    chartGridMocks.legendCallbacks = [];
    localStorage.clear();
  });

  it("renders without crashing", () => {
    const { container } = render(<ChartGrid />);
    expect(container).toBeTruthy();
  });

  it("shows the Multi Chart toolbar label", () => {
    render(<ChartGrid />);
    expect(screen.getByText("Multi Chart")).toBeInTheDocument();
  });

  it("has layout selector buttons", () => {
    render(<ChartGrid />);
    expect(screen.getByTitle("Single chart")).toBeInTheDocument();
    expect(screen.getByTitle("Two charts side by side")).toBeInTheDocument();
    expect(screen.getByTitle("Two charts stacked")).toBeInTheDocument();
    expect(screen.getByTitle("Four charts")).toBeInTheDocument();
  });

  it("defaults to 2H layout (two charts)", () => {
    render(<ChartGrid />);
    const twoHBtn = screen.getByTitle("Two charts side by side");
    expect(twoHBtn).toHaveAttribute("aria-pressed", "true");
    // Two cells => two Replay buttons shown in cell footers
    const replayBtns = screen.getAllByTitle("Replay mode");
    expect(replayBtns).toHaveLength(2);
  });

  it("switches to single chart layout on clicking '1'", () => {
    render(<ChartGrid />);
    const singleBtn = screen.getByTitle("Single chart");
    fireEvent.click(singleBtn);
    expect(singleBtn).toHaveAttribute("aria-pressed", "true");
    // Only one Replay button should be present
    const replayBtns = screen.getAllByTitle("Replay mode");
    expect(replayBtns).toHaveLength(1);
  });

  it("switches to four-chart layout on clicking '4'", () => {
    render(<ChartGrid />);
    const fourBtn = screen.getByTitle("Four charts");
    fireEvent.click(fourBtn);
    expect(fourBtn).toHaveAttribute("aria-pressed", "true");
    const replayBtns = screen.getAllByTitle("Replay mode");
    expect(replayBtns).toHaveLength(4);
  });

  it("switches to 2V (stacked) layout", () => {
    render(<ChartGrid />);
    const twoVBtn = screen.getByTitle("Two charts stacked");
    fireEvent.click(twoVBtn);
    expect(twoVBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("shows chart count label in toolbar", () => {
    render(<ChartGrid />);
    // Default 2H = 2 charts
    expect(screen.getByText("2 charts")).toBeInTheDocument();
  });

  it("updates chart count label when layout changes", () => {
    render(<ChartGrid />);
    fireEvent.click(screen.getByTitle("Four charts"));
    expect(screen.getByText("4 charts")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Single chart"));
    expect(screen.getByText("1 chart")).toBeInTheDocument();
  });

  it("has toolbar role with accessible label", () => {
    render(<ChartGrid />);
    expect(
      screen.getByRole("toolbar", { name: "Multi chart grid controls" }),
    ).toBeInTheDocument();
  });

  it("renders default symbol labels for cells", () => {
    render(<ChartGrid />);
    // In 2H mode, cells 0 and 1 have NIFTY and BANKNIFTY by default
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
  });

  it("shows the shared OHLCV readout for a chart cell when the crosshair updates", () => {
    render(<ChartGrid />);

    act(() => {
      chartGridMocks.legendCallbacks[0]?.({
        open: 24100,
        high: 24180,
        low: 24080,
        close: 24155,
        volume: 125000,
        bull: true,
      });
    });

    expect(screen.getByText("24,100.00")).toBeInTheDocument();
    expect(screen.getByText("24,180.00")).toBeInTheDocument();
    expect(screen.getByText("24,080.00")).toBeInTheDocument();
    expect(screen.getByText("24,155.00")).toBeInTheDocument();
    expect(screen.getByText("1.25L")).toBeInTheDocument();
  });
});

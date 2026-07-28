/**
 * DOMHeatmapWidget.test.tsx
 *
 * Tests for the merged DOM Heatmap widget.
 *
 * Covers the union of three retired surfaces:
 *   - the live REST poll + ring buffer (this widget's own behaviour),
 *   - the Explore-mode demo provider absorbed from `depthheatmap`, including
 *     the selectable gamma-vs-log1p intensity scale,
 *   - the transport kernel absorbed from `orderbookreplay` (play/pause, reset,
 *     step, speed pills, scrubber), now driving the REAL snapshot ring,
 *   - and the hover value readout, which is new to the merge.
 *
 * Polling is mocked so tests remain synchronous and side-effect-free.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// ─── Mocks ────────────────────────────────────────────────────────────────────

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

// Mock getDepth — returns a minimal MarketDepth for the happy path
const mockGetDepth = vi.fn();
vi.mock("@/services/api", () => ({
  getDepth: (...args: unknown[]) => mockGetDepth(...args),
}));

// Operating mode drives the data source: explore → deterministic demo book,
// anything else → the live REST poll.
let mockMode = "live";
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: mockMode }),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/components/ui/select", () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  SelectItem: ({
    children,
    value,
  }: {
    children: React.ReactNode;
    value: string;
  }) => <div data-value={value}>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => (
    <button>{children}</button>
  ),
  SelectValue: () => <span>NIFTY</span>,
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({
    children,
    variant: _variant,
    ...props
  }: {
    children: React.ReactNode;
    variant?: string;
    [key: string]: unknown;
  }) => <span {...props}>{children}</span>,
}));

// ─── Import after mocks ───────────────────────────────────────────────────────

import DOMHeatmapWidget, {
  computeIntensity,
  demoSnapshots,
  hitTestCell,
  resolveScale,
  resolveViewMode,
  snapshotStats,
  type DOMSnapshot,
} from "../DOMHeatmapWidget";
import { generateDepthHeatmapData } from "../depthHeatmapData";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const liveProps = makeWidgetPanelProps();

function replayProps() {
  return makeWidgetPanelProps({ params: { view: "replay" } });
}

/** Give an element a real box so pointer hit-testing has geometry in JSDOM. */
function sizeElement(el: HTMLElement, width: number, height: number): void {
  el.getBoundingClientRect = () =>
    ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: width,
      bottom: height,
      width,
      height,
      toJSON: () => ({}),
    }) as DOMRect;
}

function makeSnapshot(label: string, levels: [number, number, number][]): DOMSnapshot {
  return {
    ts: 0,
    label,
    levels: new Map(levels.map(([price, bidQty, askQty]) => [price, { bidQty, askQty }])),
  };
}

// ─── Pure kernels ─────────────────────────────────────────────────────────────

describe("resolveViewMode / resolveScale", () => {
  it("defaults to the live accumulating view", () => {
    expect(resolveViewMode(undefined)).toBe("live");
    expect(resolveViewMode("candlestick")).toBe("live");
  });

  it("accepts the replay view — this is how the retired orderbookreplay id resolves", () => {
    expect(resolveViewMode("replay")).toBe("replay");
  });

  it("defaults to the log1p scale and accepts gamma", () => {
    expect(resolveScale(undefined)).toBe("log");
    expect(resolveScale("nonsense")).toBe("log");
    expect(resolveScale("gamma")).toBe("gamma");
  });
});

describe("computeIntensity", () => {
  it("returns 0 for empty or degenerate input", () => {
    expect(computeIntensity(0, 100, "log")).toBe(0);
    expect(computeIntensity(50, 0, "gamma")).toBe(0);
  });

  it("saturates at the window maximum on both scales", () => {
    expect(computeIntensity(100, 100, "log")).toBeCloseTo(1, 10);
    expect(computeIntensity(100, 100, "gamma")).toBeCloseTo(1, 10);
  });

  it("gamma is the square root of the linear ratio", () => {
    expect(computeIntensity(25, 100, "gamma")).toBeCloseTo(0.5, 10);
  });

  it("log and gamma give genuinely different mid-range readings", () => {
    const log = computeIntensity(10, 1000, "log");
    const gamma = computeIntensity(10, 1000, "gamma");
    expect(log).not.toBeCloseTo(gamma, 2);
    // log1p keeps small resting orders legible; gamma pushes them down
    expect(log).toBeGreaterThan(gamma);
  });
});

describe("demoSnapshots", () => {
  it("adapts the deterministic grid onto one snapshot per time column", () => {
    const data = generateDepthHeatmapData(20, 6, 7);
    const snaps = demoSnapshots(data, 1_000_000);
    expect(snaps).toHaveLength(6);
    expect(snaps[0].label).toBe(data.timeLabels[0]);
    expect(snaps[5].ts).toBe(1_000_000);
    expect(snaps[0].ts).toBeLessThan(snaps[5].ts);
  });

  it("carries the grid volumes across unchanged", () => {
    const data = generateDepthHeatmapData(10, 3, 3);
    const snaps = demoSnapshots(data, 0);
    for (let p = 0; p < data.priceLevels.length; p++) {
      const cell = data.grid[p][1];
      if (cell.bidVolume === 0 && cell.askVolume === 0) continue;
      const got = snaps[1].levels.get(data.priceLevels[p]);
      expect(got).toEqual({ bidQty: cell.bidVolume, askQty: cell.askVolume });
    }
  });
});

describe("hitTestCell", () => {
  const snaps = [
    makeSnapshot("10:00:00", [[100, 5, 0], [101, 0, 7]]),
    makeSnapshot("10:00:01", [[100, 9, 0], [101, 0, 3]]),
  ];
  // Container 200x200 → plot spans x 4…136, y 4…180.

  it("returns null with no snapshots", () => {
    expect(hitTestCell([], 50, 50, 200, 200)).toBeNull();
  });

  it("returns null outside the plotting area", () => {
    expect(hitTestCell(snaps, 190, 50, 200, 200)).toBeNull();
    expect(hitTestCell(snaps, 50, 195, 200, 200)).toBeNull();
  });

  it("resolves the lowest price at the bottom of the plot", () => {
    const hit = hitTestCell(snaps, 10, 175, 200, 200);
    expect(hit).not.toBeNull();
    expect(hit?.price).toBe(100);
    expect(hit?.priceIndex).toBe(0);
    expect(hit?.bidQty).toBe(5);
    expect(hit?.askQty).toBe(0);
  });

  it("resolves the newest snapshot on the right of the plot", () => {
    const hit = hitTestCell(snaps, 130, 175, 200, 200);
    expect(hit?.timeIndex).toBe(1);
    expect(hit?.time).toBe("10:00:01");
    expect(hit?.bidQty).toBe(9);
  });

  it("reports zero for a price level absent from that snapshot", () => {
    const sparse = [
      makeSnapshot("10:00:00", [[100, 5, 0]]),
      makeSnapshot("10:00:01", [[101, 0, 4]]),
    ];
    const hit = hitTestCell(sparse, 10, 10, 200, 200); // top row = price 101
    expect(hit?.price).toBe(101);
    expect(hit?.bidQty).toBe(0);
    expect(hit?.askQty).toBe(0);
  });
});

describe("snapshotStats", () => {
  it("derives spread, signed imbalance and cumulative quantities", () => {
    const snap = makeSnapshot("10:00:00", [
      [99.5, 30, 0],
      [100, 30, 0],
      [100.5, 0, 20],
      [101, 0, 20],
    ]);
    const stats = snapshotStats(snap);
    expect(stats.spread).toBeCloseTo(0.5, 10);
    expect(stats.cumBidQty).toBe(60);
    expect(stats.cumAskQty).toBe(40);
    // Uses the shared bookImbalance: (60-40)/100
    expect(stats.imbalance).toBeCloseTo(0.2, 10);
  });

  it("reports a null spread when one side is empty", () => {
    const stats = snapshotStats(makeSnapshot("10:00:00", [[100, 10, 0]]));
    expect(stats.spread).toBeNull();
    expect(stats.imbalance).toBe(1);
  });
});

// ─── Widget: live view ────────────────────────────────────────────────────────

describe("DOMHeatmapWidget — live view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "live";
    // Default: getDepth never resolves during synchronous render
    mockGetDepth.mockReturnValue(new Promise(() => {}));
  });

  it("renders without crashing", () => {
    const { container } = render(<DOMHeatmapWidget {...liveProps} />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows DOM Heatmap heading", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(screen.getByText("DOM Heatmap")).toBeInTheDocument();
  });

  it("renders the heatmap canvas", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    const canvas = screen.getByTestId("domheatmap-canvas");
    expect(canvas).toBeInTheDocument();
    expect(canvas.tagName).toBe("CANVAS");
  });

  it("renders the crosshair overlay canvas", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    const xCanvas = screen.getByTestId("domheatmap-crosshair");
    expect(xCanvas).toBeInTheDocument();
  });

  it("shows 'Accumulating depth data' empty state initially", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(screen.getByText("Accumulating depth data…")).toBeInTheDocument();
  });

  it("shows legend items (Bid, Ask, Mid price)", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(screen.getByText("Bid (Buy)")).toBeInTheDocument();
    expect(screen.getByText("Ask (Sell)")).toBeInTheDocument();
    expect(screen.getByText("Mid price")).toBeInTheDocument();
  });

  it("shows symbol selector with NIFTY as default", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    const niftyEls = screen.getAllByText("NIFTY");
    expect(niftyEls.length).toBeGreaterThanOrEqual(1);
  });

  it("shows snapshot counter", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(screen.getByText(/0\/60 snaps/)).toBeInTheDocument();
  });

  it("calls getDepth on mount", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(mockGetDepth).toHaveBeenCalledWith("NIFTY", "NSE_INDEX");
  });

  it("shows error badge when getDepth rejects", async () => {
    mockGetDepth.mockRejectedValue(new Error("Connection refused"));
    await act(async () => {
      render(<DOMHeatmapWidget {...liveProps} />);
    });
    await vi.waitFor(
      () => {
        expect(screen.getByText("Error")).toBeInTheDocument();
      },
      { timeout: 2000 },
    );
  });

  it("container has correct aria-label", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    const container = screen.getByTestId("domheatmap-container");
    expect(container).toHaveAttribute("aria-label");
    expect(container.getAttribute("aria-label")).toContain("DOM heatmap");
  });

  it("does not render the replay transport in live view", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(screen.queryByRole("toolbar", { name: "Replay controls" })).toBeNull();
    expect(screen.queryByRole("slider", { name: "Replay position" })).toBeNull();
  });

  it("does not show the Demo data badge outside Explore mode", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(screen.queryByText("Demo data")).toBeNull();
  });
});

// ─── Widget: intensity scale ──────────────────────────────────────────────────

describe("DOMHeatmapWidget — intensity scale", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "live";
    mockGetDepth.mockReturnValue(new Promise(() => {}));
  });

  it("offers log and gamma as a setting, defaulting to log", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    const log = screen.getByLabelText("Logarithmic intensity scale");
    const gamma = screen.getByLabelText("Gamma power intensity scale");
    expect(log).toHaveAttribute("aria-pressed", "true");
    expect(gamma).toHaveAttribute("aria-pressed", "false");
  });

  it("switching to gamma flips the pressed state and persists to panel params", () => {
    const updateParameters = vi.fn();
    const props = makeWidgetPanelProps({
      params: {},
      api: { ...liveProps.api, updateParameters },
    });
    render(<DOMHeatmapWidget {...props} />);
    fireEvent.click(screen.getByLabelText("Gamma power intensity scale"));
    expect(screen.getByLabelText("Gamma power intensity scale")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(updateParameters).toHaveBeenCalledWith(
      expect.objectContaining({ scale: "gamma" }),
    );
  });

  it("honours params.scale — this is how the retired depthheatmap id keeps its look", () => {
    const props = makeWidgetPanelProps({ params: { scale: "gamma" } });
    render(<DOMHeatmapWidget {...props} />);
    expect(screen.getByLabelText("Gamma power intensity scale")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});

// ─── Widget: Explore-mode demo provider ───────────────────────────────────────

describe("DOMHeatmapWidget — Explore demo data", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "explore";
    mockGetDepth.mockReturnValue(new Promise(() => {}));
  });

  afterEach(() => {
    mockMode = "live";
  });

  it("never touches the broker depth endpoint in Explore mode", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(mockGetDepth).not.toHaveBeenCalled();
  });

  it("labels generated data with a permanent 'Demo data' badge", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    const badge = screen.getByText("Demo data");
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute("role")).toBe("status");
  });

  it("says 'demo data' in the chart's accessible description", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(
      screen.getByTestId("domheatmap-container").getAttribute("aria-label"),
    ).toContain("demo data");
  });

  it("fills the ring from the deterministic generator", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(screen.getByText(/60\/60 snaps/)).toBeInTheDocument();
  });
});

// ─── Widget: hover value readout (new to the merge) ───────────────────────────

describe("DOMHeatmapWidget — hover readout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "explore";
    mockGetDepth.mockReturnValue(new Promise(() => {}));
  });

  afterEach(() => {
    mockMode = "live";
  });

  it("shows nothing until the pointer is over the plot", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    expect(screen.queryByTestId("domheatmap-readout")).toBeNull();
  });

  it("reports the price and bid/ask size under the crosshair", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    const container = screen.getByTestId("domheatmap-container");
    sizeElement(container, 400, 300);
    fireEvent.mouseMove(container, { clientX: 200, clientY: 150 });
    const readout = screen.getByTestId("domheatmap-readout");
    expect(readout).toBeInTheDocument();
    expect(readout.textContent).toMatch(/Bid/);
    expect(readout.textContent).toMatch(/Ask/);
  });

  it("clears the readout on mouse leave", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    const container = screen.getByTestId("domheatmap-container");
    sizeElement(container, 400, 300);
    fireEvent.mouseMove(container, { clientX: 200, clientY: 150 });
    expect(screen.getByTestId("domheatmap-readout")).toBeInTheDocument();
    fireEvent.mouseLeave(container);
    expect(screen.queryByTestId("domheatmap-readout")).toBeNull();
  });

  it("mouse move and leave never throw", () => {
    render(<DOMHeatmapWidget {...liveProps} />);
    const container = screen.getByTestId("domheatmap-container");
    expect(() =>
      fireEvent.mouseMove(container, { clientX: 100, clientY: 80 }),
    ).not.toThrow();
    expect(() => fireEvent.mouseLeave(container)).not.toThrow();
  });
});

// ─── Widget: replay transport (ported from OrderBookReplay) ───────────────────

describe("DOMHeatmapWidget — replay transport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Explore gives the ring 60 real-shaped snapshots synchronously, so the
    // transport has something to scrub without faking timers.
    mockMode = "explore";
    mockGetDepth.mockReturnValue(new Promise(() => {}));
  });

  afterEach(() => {
    mockMode = "live";
  });

  it("renders the replay toolbar", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    expect(screen.getByRole("toolbar", { name: "Replay controls" })).toBeTruthy();
  });

  it("renders play button initially", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    expect(screen.getByLabelText("Play replay")).toBeTruthy();
  });

  it("pressing play button switches to pause button", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    fireEvent.click(screen.getByLabelText("Play replay"));
    expect(screen.getByLabelText("Pause replay")).toBeTruthy();
  });

  it("renders the scrubber slider over the real snapshot ring", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    const slider = screen.getByRole("slider", { name: "Replay position" });
    expect(slider.getAttribute("aria-valuenow")).toBe("0");
    // 60 snapshots → indices 0…59
    expect(slider.getAttribute("aria-valuemax")).toBe("59");
  });

  it("scrubber arrow keys seek one snapshot at a time", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    const slider = screen.getByRole("slider", { name: "Replay position" });
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(slider.getAttribute("aria-valuenow")).toBe("1");
    fireEvent.keyDown(slider, { key: "ArrowLeft" });
    expect(slider.getAttribute("aria-valuenow")).toBe("0");
  });

  it("step forward and step back move the playhead", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    const slider = screen.getByRole("slider", { name: "Replay position" });
    fireEvent.click(screen.getByLabelText("Step forward one snapshot"));
    fireEvent.click(screen.getByLabelText("Step forward one snapshot"));
    expect(slider.getAttribute("aria-valuenow")).toBe("2");
    fireEvent.click(screen.getByLabelText("Step back one snapshot"));
    expect(slider.getAttribute("aria-valuenow")).toBe("1");
  });

  it("reset button pauses and returns the scrubber to 0", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    fireEvent.click(screen.getByLabelText("Step forward one snapshot"));
    fireEvent.click(screen.getByLabelText("Play replay"));
    fireEvent.click(screen.getByLabelText("Reset to start"));
    const slider = screen.getByRole("slider", { name: "Replay position" });
    expect(slider.getAttribute("aria-valuenow")).toBe("0");
    expect(screen.getByLabelText("Play replay")).toBeTruthy();
  });

  it("renders speed pill buttons 1x through 8x", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    expect(screen.getByLabelText("1x speed")).toBeTruthy();
    expect(screen.getByLabelText("2x speed")).toBeTruthy();
    expect(screen.getByLabelText("4x speed")).toBeTruthy();
    expect(screen.getByLabelText("8x speed")).toBeTruthy();
  });

  it("selecting a speed marks it pressed", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    expect(screen.getByLabelText("1x speed")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByLabelText("4x speed"));
    expect(screen.getByLabelText("4x speed")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("1x speed")).toHaveAttribute("aria-pressed", "false");
  });

  it("shows the scrubbed snapshot's Spread and Imbalance", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    expect(screen.getByTestId("domheatmap-replay-stats")).toBeInTheDocument();
    expect(screen.getByText("Spread")).toBeInTheDocument();
    expect(screen.getByText("Imbalance")).toBeInTheDocument();
  });

  it("Space toggles playback and arrow keys step the playhead", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    fireEvent.keyDown(window, { key: " " });
    expect(screen.getByLabelText("Pause replay")).toBeTruthy();
    fireEvent.keyDown(window, { key: "k" });
    expect(screen.getByLabelText("Play replay")).toBeTruthy();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(
      screen.getByRole("slider", { name: "Replay position" }).getAttribute("aria-valuenow"),
    ).toBe("1");
  });

  it("switching back to live retires the transport", () => {
    render(<DOMHeatmapWidget {...replayProps()} />);
    expect(screen.getByRole("toolbar", { name: "Replay controls" })).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Live accumulating view"));
    expect(screen.queryByRole("toolbar", { name: "Replay controls" })).toBeNull();
  });

  it("persists the chosen view into panel params", () => {
    const updateParameters = vi.fn();
    const props = makeWidgetPanelProps({
      params: {},
      api: { ...liveProps.api, updateParameters },
    });
    render(<DOMHeatmapWidget {...props} />);
    fireEvent.click(screen.getByLabelText("Replay the captured snapshots"));
    expect(updateParameters).toHaveBeenCalledWith(
      expect.objectContaining({ view: "replay" }),
    );
  });
});

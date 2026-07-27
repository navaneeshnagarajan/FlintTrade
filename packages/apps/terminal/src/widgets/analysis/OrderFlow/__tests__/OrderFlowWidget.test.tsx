/**
 * OrderFlowWidget.test.tsx
 *
 * Tests for the canonical Order Flow chart widget.
 * Verifies rendering, toolbar elements, empty/loading states, and the three
 * view modes (footprint / footprint+delta / heatmap).
 *
 * The `footprint+delta` cases were ported here from the retired standalone
 * FootprintWidget suite during merge 2.4 — they pin the per-cell delta text,
 * the responsive cumulative-delta strip, and the bucket-grouping semantic.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const resizeObservations: Array<{
  callback: ResizeObserverCallback;
  target: Element;
}> = [];

// Stub ResizeObserver (not available in JSDOM) while retaining layout callbacks.
vi.stubGlobal(
  "ResizeObserver",
  class {
    constructor(private readonly callback: ResizeObserverCallback) {}

    observe(target: Element) {
      resizeObservations.push({ callback: this.callback, target });
    }

    unobserve(target: Element) {
      const index = resizeObservations.findIndex((entry) => entry.target === target);
      if (index >= 0) resizeObservations.splice(index, 1);
    }

    disconnect() {}
  },
);

const mockUseOrderFlow = vi.fn();

vi.mock("@/hooks/useOrderFlow", () => ({
  useOrderFlow: (...args: unknown[]) => mockUseOrderFlow(...args),
}));

// Mock shadcn/ui components to avoid Radix rendering issues in JSDOM
vi.mock("@/components/ui/select", () => ({
  Select: ({
    children,
    value,
    onValueChange,
  }: {
    children: React.ReactNode;
    value: string;
    onValueChange: (value: string) => void;
  }) => (
    <select
      aria-label="Symbol"
      value={value}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {children}
    </select>
  ),
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <option value={value}>{children}</option>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode; [key: string]: unknown }) => (
    <span {...props}>{children}</span>
  ),
}));

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: ({ className }: { className?: string }) => <div className={className} data-testid="skeleton" />,
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import OrderFlowWidget from "../OrderFlowWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function hookResult(overrides = {}) {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    isFetching: false,
    ...overrides,
  };
}

const defaultProps = makeWidgetPanelProps();

const deltaViewProps = makeWidgetPanelProps({
  params: { view: "footprint+delta" },
});

function resizeObservedElement(target: Element, width: number, height: number): void {
  const observation = resizeObservations.find((entry) => entry.target === target);
  expect(observation).toBeDefined();
  act(() => {
    observation?.callback(
      [{ target, contentRect: { width, height } } as ResizeObserverEntry],
      {} as ResizeObserver,
    );
  });
}

function installCanvasPaintHarness() {
  const frameCallbacks: FrameRequestCallback[] = [];
  const fillText = vi.fn();
  const measureText = vi.fn((text: string) => ({ width: text.length * 6 }) as TextMetrics);
  const moveTo = vi.fn();
  const setLineDash = vi.fn();
  const context = {
    beginPath: vi.fn(),
    closePath: vi.fn(),
    fill: vi.fn(),
    fillRect: vi.fn(),
    fillText,
    lineTo: vi.fn(),
    measureText,
    moveTo,
    restore: vi.fn(),
    save: vi.fn(),
    setLineDash,
    stroke: vi.fn(),
    strokeRect: vi.fn(),
  } as unknown as CanvasRenderingContext2D;

  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context);
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    frameCallbacks.push(callback);
    return frameCallbacks.length;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);

  return {
    fillText,
    measureText,
    moveTo,
    setLineDash,
    paintedLabels: () => fillText.mock.calls.map(([label]) => String(label)),
    runLatestFrame: () => {
      const callback = frameCallbacks.at(-1);
      expect(callback).toBeDefined();
      act(() => callback?.(0));
    },
  };
}

/** Y coordinate of the dashed Latest-POC line — the first moveTo after setLineDash. */
function getDashedLineY(
  moveTo: ReturnType<typeof vi.fn>,
  setLineDash: ReturnType<typeof vi.fn>,
): number {
  const dashOrder = setLineDash.mock.invocationCallOrder.at(-1);
  expect(dashOrder).toBeDefined();
  const moveIndex = moveTo.mock.invocationCallOrder.findIndex(
    (order) => dashOrder !== undefined && order > dashOrder,
  );
  expect(moveIndex).toBeGreaterThanOrEqual(0);
  return Number(moveTo.mock.calls[moveIndex]?.[1]);
}

const singleBucket = {
  time_label: "09:15",
  cells: { "22500": { buy_volume: 100, sell_volume: 80 } },
  poc_price: 22500,
  total_volume: 180,
  delta: 20,
};

const twoLevelBuckets = [
  {
    time_label: "09:15",
    cells: {
      "22500": { buy_volume: 1000, sell_volume: 800 },
      "22550": { buy_volume: 500, sell_volume: 1200 },
    },
    poc_price: 22500,
    total_volume: 3500,
    delta: -500,
  },
];

const twentySecondPrecisionBuckets = Array.from({ length: 20 }, (_, index) => ({
  time_label: `09:${String(15 + index).padStart(2, "0")}:00`,
  cells: {
    "22500": { buy_volume: 100 + index, sell_volume: 80 },
  },
  poc_price: 22500,
  total_volume: 180 + index,
  delta: 20 + index,
}));

function orderFlowResponse(buckets: unknown[], overrides: Record<string, unknown> = {}) {
  return {
    buckets,
    symbol: "NIFTY",
    exchange: "NSE_INDEX",
    interval: 300,
    is_live: false,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OrderFlowWidget", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    resizeObservations.length = 0;
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    mockUseOrderFlow.mockReturnValue(hookResult());
  });

  it("renders without crashing", () => {
    const { container } = render(<OrderFlowWidget {...defaultProps} />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("requests the default NIFTY capture exchange", () => {
    render(<OrderFlowWidget {...defaultProps} />);
    expect(mockUseOrderFlow).toHaveBeenCalledWith("NIFTY", "NSE_INDEX", 300, 20);
  });

  it("syncs Dockview symbol and exchange parameter changes", () => {
    const initialProps = makeWidgetPanelProps({
      params: { symbol: "NIFTY", exchange: "NSE_INDEX" },
    });
    const updatedProps = makeWidgetPanelProps({
      params: { symbol: "RELIANCE", exchange: "BSE" },
    });
    const { rerender } = render(<OrderFlowWidget {...initialProps} />);

    mockUseOrderFlow.mockClear();
    rerender(<OrderFlowWidget {...updatedProps} />);

    expect(mockUseOrderFlow).not.toHaveBeenCalledWith("NIFTY", "BSE", 300, 20);
    expect(mockUseOrderFlow).toHaveBeenLastCalledWith("RELIANCE", "BSE", 300, 20);
  });

  it("clears an explicit NSE index exchange when the user changes symbol", () => {
    const updateParameters = vi.fn();
    const props = makeWidgetPanelProps({
      params: { symbol: "NIFTY", exchange: "NSE_INDEX", view: "footprint" },
      api: { ...defaultProps.api, updateParameters },
    });
    render(<OrderFlowWidget {...props} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Symbol" }), {
      target: { value: "RELIANCE" },
    });

    expect(mockUseOrderFlow).toHaveBeenLastCalledWith("RELIANCE", "NSE", 300, 20);
    expect(updateParameters).toHaveBeenCalledWith({
      symbol: "RELIANCE",
      exchange: "NSE",
      view: "footprint",
    });
  });

  it("shows interval buttons (1m, 3m, 5m)", () => {
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("1m")).toBeInTheDocument();
    expect(screen.getByText("3m")).toBeInTheDocument();
    expect(screen.getByText("5m")).toBeInTheDocument();
  });

  it("shows labelled icon controls for all three view modes", () => {
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByRole("button", { name: "Footprint view" })).toHaveAttribute(
      "title",
      "Footprint view",
    );
    expect(
      screen.getByRole("button", { name: "Footprint with delta view" }),
    ).toHaveAttribute("title", "Footprint with delta view");
    expect(screen.getByRole("button", { name: "Heatmap view" })).toHaveAttribute(
      "title",
      "Heatmap view",
    );
  });

  // ─── View-mode parameter (retired `footprint` id resolution) ───────────────

  it("defaults to the footprint view when no view parameter is supplied", () => {
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByTestId("order-flow-chart")).toHaveAttribute("data-view", "footprint");
    expect(screen.getByRole("button", { name: "Footprint view" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryByText("Cum. Δ")).not.toBeInTheDocument();
  });

  it("opens in the delta view when the panel parameter requests it", () => {
    render(<OrderFlowWidget {...deltaViewProps} />);
    const chart = screen.getByTestId("order-flow-chart");
    expect(chart).toHaveAttribute("data-view", "footprint+delta");
    expect(chart).toHaveAttribute("data-cumulative-delta", "visible");
    expect(
      screen.getByRole("button", { name: "Footprint with delta view" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Cum. Δ")).toBeInTheDocument();
    expect(chart).toHaveAccessibleName(/Delta value shown in each cell/);
    expect(chart).toHaveAccessibleName(/Cumulative delta line shown at bottom/);
  });

  it("ignores an unrecognised view parameter", () => {
    const props = makeWidgetPanelProps({ params: { view: "candlestick" } });
    render(<OrderFlowWidget {...props} />);
    expect(screen.getByTestId("order-flow-chart")).toHaveAttribute("data-view", "footprint");
  });

  it("persists the chosen view into the panel parameters", () => {
    const updateParameters = vi.fn();
    const props = makeWidgetPanelProps({
      params: { symbol: "NIFTY", exchange: "NSE_INDEX" },
      api: { ...defaultProps.api, updateParameters },
    });
    render(<OrderFlowWidget {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "Footprint with delta view" }));

    expect(updateParameters).toHaveBeenCalledWith({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      view: "footprint+delta",
    });
    expect(screen.getByTestId("order-flow-chart")).toHaveAttribute(
      "data-view",
      "footprint+delta",
    );
  });

  // ─── Canvas sizing ────────────────────────────────────────────────────────

  it("replaces a pending paint after resizing clears the canvas backing store", () => {
    let nextAnimationFrameId = 1;
    const requestAnimationFrameMock = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((_callback: FrameRequestCallback) => nextAnimationFrameId++);
    const cancelAnimationFrameMock = vi
      .spyOn(window, "cancelAnimationFrame")
      .mockImplementation(() => undefined);
    mockUseOrderFlow.mockReturnValue(
      hookResult({ data: orderFlowResponse([singleBucket]) }),
    );
    render(<OrderFlowWidget {...defaultProps} />);
    const pendingFrameId = requestAnimationFrameMock.mock.results.at(-1)?.value as number;
    const requestCount = requestAnimationFrameMock.mock.calls.length;

    resizeObservedElement(screen.getByTestId("order-flow-chart"), 220, 64);

    expect(cancelAnimationFrameMock).toHaveBeenCalledWith(pendingFrameId);
    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(requestCount + 1);
    const canvas = screen.getByTestId("order-flow-canvas");
    expect(canvas).toHaveAttribute("width", "220");
    expect(canvas).toHaveAttribute("height", "64");
  });

  it("updates the canvas backing store when only device pixel ratio changes", () => {
    vi.useFakeTimers();
    let devicePixelRatio = 1;
    vi.spyOn(window, "devicePixelRatio", "get").mockImplementation(() => devicePixelRatio);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    mockUseOrderFlow.mockReturnValue(
      hookResult({ data: orderFlowResponse(twentySecondPrecisionBuckets) }),
    );
    render(<OrderFlowWidget {...defaultProps} />);
    const chart = screen.getByTestId("order-flow-chart");
    const canvas = screen.getByTestId("order-flow-canvas");

    resizeObservedElement(chart, 220, 64);
    expect(canvas).toHaveAttribute("width", "220");
    expect(canvas).toHaveAttribute("height", "64");

    devicePixelRatio = 2;
    act(() => vi.advanceTimersByTime(250));

    expect(canvas).toHaveAttribute("width", "440");
    expect(canvas).toHaveAttribute("height", "128");
    expect(canvas).toHaveStyle({ width: "220px", height: "64px" });
  });

  it("keeps footprint geometry stable across 139px and 140px canvas heights", () => {
    const harness = installCanvasPaintHarness();
    mockUseOrderFlow.mockReturnValue(
      hookResult({ data: orderFlowResponse(twoLevelBuckets) }),
    );
    render(<OrderFlowWidget {...deltaViewProps} />);
    const chart = screen.getByTestId("order-flow-chart");

    resizeObservedElement(chart, 520, 139);
    harness.runLatestFrame();
    const lineAt139 = getDashedLineY(harness.moveTo, harness.setLineDash);

    harness.moveTo.mockClear();
    harness.setLineDash.mockClear();
    resizeObservedElement(chart, 520, 140);
    harness.runLatestFrame();
    const lineAt140 = getDashedLineY(harness.moveTo, harness.setLineDash);

    expect(Math.abs(lineAt140 - lineAt139)).toBeLessThan(2);
    expect(screen.getByText("Cum. Δ")).toBeInTheDocument();
  });

  // ─── Delta presentation absorbed from the retired Footprint widget ─────────

  it("draws the per-cell delta number only in the delta view", () => {
    const harness = installCanvasPaintHarness();
    mockUseOrderFlow.mockReturnValue(
      hookResult({ data: orderFlowResponse([singleBucket]) }),
    );
    render(<OrderFlowWidget {...defaultProps} />);

    resizeObservedElement(screen.getByTestId("order-flow-chart"), 520, 240);
    harness.runLatestFrame();
    expect(harness.paintedLabels()).not.toContain("+20");

    harness.fillText.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Footprint with delta view" }));
    harness.runLatestFrame();

    expect(harness.paintedLabels()).toContain("+20");
    expect(harness.paintedLabels()).toContain("Cumulative Δ");
  });

  it("draws the cumulative-delta strip from the backend bucket delta, not a client sum", () => {
    const harness = installCanvasPaintHarness();
    // Cells sum to +20 while the backend reports −5000. The strip must follow
    // the backend value: the aggregator applies session/out-of-order guards
    // the client cannot reproduce.
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: orderFlowResponse([{ ...singleBucket, delta: -5000 }]),
      }),
    );
    render(<OrderFlowWidget {...deltaViewProps} />);

    resizeObservedElement(screen.getByTestId("order-flow-chart"), 520, 240);
    harness.runLatestFrame();

    const labels = harness.paintedLabels();
    expect(labels).toContain("-5,000");
    // The per-cell figure is still derived from that cell's own volumes.
    expect(labels).toContain("+20");
  });

  it("merges backend buckets that share a time label into one column", () => {
    const harness = installCanvasPaintHarness();
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: orderFlowResponse([
          singleBucket,
          {
            time_label: "09:15",
            cells: { "22500": { buy_volume: 40, sell_volume: 30 } },
            poc_price: 22500,
            total_volume: 70,
            delta: 10,
          },
        ]),
      }),
    );
    render(<OrderFlowWidget {...deltaViewProps} />);

    // A 1:1 bucket→column map would report two bars for one instant.
    expect(screen.getByText(/1 bars/)).toBeInTheDocument();

    resizeObservedElement(screen.getByTestId("order-flow-chart"), 520, 240);
    harness.runLatestFrame();

    // Volumes merge (140 buy / 110 sell) and the backend deltas add up (+30).
    expect(harness.paintedLabels()).toContain("+30");
    expect(harness.paintedLabels().filter((label) => label === "09:15")).toHaveLength(1);
  });

  // ─── Compact layout ───────────────────────────────────────────────────────

  it("uses stable compact controls and preserves chart space at 220x96", () => {
    render(
      <div style={{ width: "220px", height: "96px" }}>
        <OrderFlowWidget {...defaultProps} />
      </div>,
    );

    const panel = screen.getByTestId("order-flow-panel");
    resizeObservedElement(panel, 220, 96);
    resizeObservedElement(screen.getByTestId("order-flow-chart"), 220, 64);

    expect(panel).toHaveAttribute("data-layout", "compact");
    const toolbar = screen.getByRole("toolbar", { name: "Order flow controls" });
    expect(toolbar).toHaveClass("min-w-0", "flex-nowrap");
    expect(toolbar).not.toHaveClass("flex-wrap");
    expect(within(toolbar).getByRole("combobox", { name: "Symbol" })).toBeInTheDocument();
    const moreControls = within(toolbar).getByRole("button", { name: "More order flow controls" });
    expect(moreControls).toBeInTheDocument();
    expect(within(toolbar).queryByRole("button", { name: "1m interval" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("order-flow-legend")).not.toBeInTheDocument();
    expect(screen.getByTestId("order-flow-chart")).toHaveAttribute("data-density", "compact");
    expect(screen.getByTestId("order-flow-compact-state")).toHaveTextContent("No data");

    fireEvent.pointerDown(moreControls, { button: 0, ctrlKey: false });
    expect(screen.getByTestId("order-flow-compact-legend")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitemradio", { name: "1m interval" }));
    expect(mockUseOrderFlow).toHaveBeenLastCalledWith("NIFTY", "NSE_INDEX", 60, 20);
  });

  it("drops the cumulative-delta affordance when the canvas is too short for the strip", () => {
    render(
      <div style={{ width: "220px", height: "96px" }}>
        <OrderFlowWidget {...deltaViewProps} />
      </div>,
    );

    const panel = screen.getByTestId("order-flow-panel");
    resizeObservedElement(panel, 220, 96);
    resizeObservedElement(screen.getByTestId("order-flow-chart"), 220, 64);

    const chart = screen.getByTestId("order-flow-chart");
    expect(chart).toHaveAttribute("data-cumulative-delta", "hidden");
    expect(chart).toHaveAccessibleName(/Cumulative delta is hidden at this height/);

    fireEvent.pointerDown(
      screen.getByRole("button", { name: "More order flow controls" }),
      { button: 0, ctrlKey: false },
    );
    expect(screen.getByTestId("order-flow-compact-legend")).toBeInTheDocument();
    expect(screen.queryByText("Cum. Δ")).not.toBeInTheDocument();
  });

  it("restores full controls, legend, and canvas density at a normal panel size", () => {
    render(<OrderFlowWidget {...defaultProps} />);

    const panel = screen.getByTestId("order-flow-panel");
    resizeObservedElement(panel, 520, 360);
    expect(panel).toHaveAttribute("data-layout", "compact");

    resizeObservedElement(panel, 521, 360);
    expect(panel).toHaveAttribute("data-layout", "compact");

    resizeObservedElement(panel, 640, 360);

    expect(panel).toHaveAttribute("data-layout", "full");
    expect(screen.queryByRole("button", { name: "More order flow controls" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1m interval" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Footprint with delta view" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Heatmap view" })).toBeInTheDocument();
    expect(screen.getByTestId("order-flow-legend")).toBeInTheDocument();
    expect(screen.getByTestId("order-flow-chart")).toHaveAttribute("data-density", "full");
  });

  it("uses a bounded error status instead of overflowing a compact chart", () => {
    const errorMessage = "A backend error message that cannot fit inside a short Dockview panel";
    mockUseOrderFlow.mockReturnValue(hookResult({
      isError: true,
      error: new Error(errorMessage),
    }));
    render(<OrderFlowWidget {...defaultProps} />);

    const panel = screen.getByTestId("order-flow-panel");
    resizeObservedElement(panel, 220, 96);

    const compactError = screen.getByTestId("order-flow-compact-state");
    expect(compactError).toHaveTextContent("Unable to load");
    expect(compactError).toHaveAttribute("tabindex", "0");
    expect(compactError).toHaveAccessibleName(`Unable to load: ${errorMessage}`);
    compactError.focus();
    expect(compactError).toHaveFocus();
    expect(screen.queryByText("Retrying automatically...")).not.toBeInTheDocument();
  });

  it("keyboard-focuses compact menu status and the legend tail", async () => {
    const user = userEvent.setup();
    const errorMessage = "Full compact order flow failure details";
    mockUseOrderFlow.mockReturnValue(hookResult({
      isError: true,
      error: new Error(errorMessage),
    }));
    render(<OrderFlowWidget {...defaultProps} />);

    const panel = screen.getByTestId("order-flow-panel");
    resizeObservedElement(panel, 220, 96);
    await user.click(screen.getByRole("button", { name: "More order flow controls" }));

    const status = screen.getByTestId("order-flow-menu-status");
    const legend = screen.getByTestId("order-flow-compact-legend");
    expect(screen.getByTestId("order-flow-compact-menu")).toHaveStyle({
      maxHeight: "min(var(--radix-dropdown-menu-content-available-height), calc(100dvh - 1rem))",
      maxWidth: "calc(100vw - 1rem)",
      width: "12rem",
    });
    expect(status).toHaveAccessibleName(`Status: Error. ${errorMessage}`);

    await user.keyboard("{End}");
    expect(legend).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(status).toHaveFocus();
  });

  it("uses a bounded loading status instead of skeleton rows in a compact chart", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({ isLoading: true }));
    render(<OrderFlowWidget {...defaultProps} />);

    const panel = screen.getByTestId("order-flow-panel");
    resizeObservedElement(panel, 220, 96);

    expect(screen.getByTestId("order-flow-compact-state")).toHaveTextContent("Loading");
    expect(screen.queryByTestId("skeleton")).not.toBeInTheDocument();
  });

  // ─── Time-scale subsampling ───────────────────────────────────────────────

  it("measures and subsamples twenty HH:MM:SS labels in every view mode", () => {
    const harness = installCanvasPaintHarness();
    mockUseOrderFlow.mockReturnValue(hookResult({
      data: orderFlowResponse(twentySecondPrecisionBuckets, { interval: 60 }),
    }));
    render(<OrderFlowWidget {...defaultProps} />);
    const chart = screen.getByTestId("order-flow-chart");

    const expectSubsampledTimeLabels = () => {
      const isTimeLabel = (label: string) => /^\d{2}:\d{2}:\d{2}$/.test(label);
      const measuredTimes = harness.measureText.mock.calls
        .map(([label]) => String(label))
        .filter(isTimeLabel);
      const paintedTimes = harness.paintedLabels().filter(isTimeLabel);
      expect(measuredTimes).toHaveLength(20);
      expect(paintedTimes.length).toBeGreaterThan(1);
      expect(paintedTimes.length).toBeLessThan(20);
    };

    resizeObservedElement(chart, 520, 240);
    harness.runLatestFrame();
    expectSubsampledTimeLabels();

    harness.measureText.mockClear();
    harness.fillText.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Footprint with delta view" }));
    harness.runLatestFrame();
    expectSubsampledTimeLabels();

    harness.measureText.mockClear();
    harness.fillText.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Heatmap view" }));
    harness.runLatestFrame();
    expectSubsampledTimeLabels();
  });

  // ─── Honesty affordances ──────────────────────────────────────────────────

  it("labels the bucket-derived value and line as Latest POC, never LTP", () => {
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByText("Sell")).toBeInTheDocument();
    expect(screen.getByText("POC")).toBeInTheDocument();
    expect(screen.getByText("Latest POC")).toBeInTheDocument();
    expect(screen.queryByText("LTP")).not.toBeInTheDocument();
  });

  it("labels the delta view's legend without introducing an LTP claim", () => {
    render(<OrderFlowWidget {...deltaViewProps} />);
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByText("Sell")).toBeInTheDocument();
    expect(screen.getByText("POC")).toBeInTheDocument();
    expect(screen.getByText("Latest POC")).toBeInTheDocument();
    expect(screen.getByText("Cum. Δ")).toBeInTheDocument();
    expect(screen.queryByText("LTP")).not.toBeInTheDocument();
  });

  it("shows 'No data' when no buckets and not loading", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({ data: undefined }));
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("shows 'Live' badge when is_live is true", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({ data: orderFlowResponse([singleBucket], { exchange: "NFO", is_live: true }) }),
    );
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("renders exact trade-tick quality and provenance", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({
      data: orderFlowResponse(
        [{ ...singleBucket, quality: "exact", provenance: "trade_tick" }],
        { exchange: "NFO", is_live: true, quality: "exact", provenance: "trade_tick" },
      ),
    }));

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText("Exact trades")).toBeInTheDocument();
    expect(screen.getByLabelText(/exact order flow.*trade ticks/i)).toBeInTheDocument();
  });

  it("renders cumulative-quote order flow as estimated", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({
      data: orderFlowResponse(
        [{ ...singleBucket, quality: "estimated", provenance: "cumulative_quote_delta" }],
        {
          exchange: "NFO",
          is_live: true,
          quality: "estimated",
          provenance: "cumulative_quote_delta",
        },
      ),
    }));

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText("Estimated quote deltas")).toBeInTheDocument();
    expect(screen.getByLabelText(/estimated order flow.*cumulative quote deltas/i)).toBeInTheDocument();
  });

  it("uses the backend interval in chart and legend labels", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({ data: orderFlowResponse([singleBucket], { interval: 60, is_live: true }) }),
    );

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText(/1 bars.*NIFTY 1m/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /NIFTY, 1m interval/ })).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(mockUseOrderFlow).toHaveBeenCalledWith("NIFTY", "NSE_INDEX", 300, 20);
  });

  it("shows 'Sample data' badge when is_live is false", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({ data: orderFlowResponse([singleBucket], { exchange: "NFO" }) }),
    );
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("keeps explicit sample provenance visible even if is_live is contradictory", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({
      data: orderFlowResponse([singleBucket], {
        exchange: "NFO",
        is_live: true,
        is_sample_data: true,
      }),
    }));

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("shows 'Delayed' for retained backend data that is no longer live", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({
      data: orderFlowResponse([singleBucket], { exchange: "NFO", live_state: "delayed" }),
    }));

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText("Delayed")).toBeInTheDocument();
    expect(screen.getByLabelText(/retained order flow data is delayed/i)).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("shows 'Stale' for retained order flow from an older session", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({
      data: orderFlowResponse(
        [{ ...singleBucket, time_label: "15:25" }],
        { exchange: "NFO", live_state: "stale" },
      ),
    }));

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("shows loading skeletons when loading with no data", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({ isLoading: true }));
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("Loading order flow data...")).toBeInTheDocument();
  });
});

/**
 * FootprintWidget.test.tsx
 *
 * Tests for the Footprint chart widget.
 * Covers rendering, toolbar elements, status badges, and empty/loading/error states.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// ─── Mocks ────────────────────────────────────────────────────────────────────

const resizeObservations: Array<{
  callback: ResizeObserverCallback;
  target: Element;
}> = [];

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
  SelectItem: ({
    children,
    value,
  }: {
    children: React.ReactNode;
    value: string;
  }) => <option value={value}>{children}</option>,
  SelectTrigger: () => null,
  SelectValue: () => null,
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({
    children,
    ...props
  }: {
    children: React.ReactNode;
    [key: string]: unknown;
  }) => <span {...props}>{children}</span>,
}));

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: ({ className }: { className?: string }) => (
    <div className={className} data-testid="skeleton" />
  ),
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}));

// ─── Import after mocks ───────────────────────────────────────────────────────

import FootprintWidget from "../FootprintWidget";

// ─── Helpers ──────────────────────────────────────────────────────────────────

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

const defaultProps = makeDockviewPanelProps();

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
    runLatestFrame: () => {
      const callback = frameCallbacks.at(-1);
      expect(callback).toBeDefined();
      act(() => callback?.(0));
    },
  };
}

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

const sampleBuckets = [
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
  {
    time_label: "09:20",
    cells: {
      "22500": { buy_volume: 1200, sell_volume: 600 },
      "22600": { buy_volume: 300, sell_volume: 900 },
    },
    poc_price: 22500,
    total_volume: 3000,
    delta: 0,
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

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("FootprintWidget", () => {
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
    const { container } = render(<FootprintWidget {...defaultProps} />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows Footprint heading", () => {
    render(<FootprintWidget {...defaultProps} />);
    expect(screen.getByText("Footprint")).toBeInTheDocument();
  });

  it("renders interval toggle buttons (1m, 3m, 5m)", () => {
    render(<FootprintWidget {...defaultProps} />);
    expect(screen.getByText("1m")).toBeInTheDocument();
    expect(screen.getByText("3m")).toBeInTheDocument();
    expect(screen.getByText("5m")).toBeInTheDocument();
  });

  it("uses stable compact controls and preserves chart space at 220x96", () => {
    render(
      <div style={{ width: "220px", height: "96px" }}>
        <FootprintWidget {...defaultProps} />
      </div>,
    );

    const panel = screen.getByTestId("footprint-panel");
    resizeObservedElement(panel, 220, 96);
    resizeObservedElement(screen.getByTestId("footprint-chart"), 220, 64);

    expect(panel).toHaveAttribute("data-layout", "compact");
    const toolbar = screen.getByRole("toolbar", { name: "Footprint controls" });
    expect(toolbar).toHaveClass("min-w-0", "flex-nowrap");
    expect(toolbar).not.toHaveClass("flex-wrap");
    expect(within(toolbar).getByRole("combobox", { name: "Symbol" })).toBeInTheDocument();
    const moreControls = within(toolbar).getByRole("button", { name: "More footprint controls" });
    expect(moreControls).toBeInTheDocument();
    expect(within(toolbar).queryByRole("button", { name: "1m interval" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("footprint-legend")).not.toBeInTheDocument();
    expect(screen.getByTestId("footprint-chart")).toHaveAttribute("data-density", "compact");
    expect(screen.getByTestId("footprint-compact-state")).toHaveTextContent("No data");

    fireEvent.pointerDown(moreControls, { button: 0, ctrlKey: false });
    expect(screen.getByTestId("footprint-compact-legend")).toBeInTheDocument();
    expect(screen.queryByText("Cum. Δ")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitemradio", { name: "1m interval" }));
    expect(mockUseOrderFlow).toHaveBeenLastCalledWith("NIFTY", "NSE_INDEX", 60, 20);
  });

  it("restores full controls, legend, and canvas density at a normal panel size", () => {
    render(<FootprintWidget {...defaultProps} />);

    const panel = screen.getByTestId("footprint-panel");
    resizeObservedElement(panel, 520, 360);
    expect(panel).toHaveAttribute("data-layout", "compact");

    resizeObservedElement(panel, 521, 360);
    expect(panel).toHaveAttribute("data-layout", "compact");

    resizeObservedElement(panel, 640, 360);

    expect(panel).toHaveAttribute("data-layout", "full");
    expect(screen.queryByRole("button", { name: "More footprint controls" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1m interval" })).toBeInTheDocument();
    expect(screen.getByTestId("footprint-legend")).toBeInTheDocument();
    expect(screen.getByTestId("footprint-chart")).toHaveAttribute("data-density", "full");
  });

  it("uses a bounded error status instead of overflowing a compact chart", () => {
    const errorMessage = "A backend error message that cannot fit inside a short Dockview panel";
    mockUseOrderFlow.mockReturnValue(hookResult({
      isError: true,
      error: new Error(errorMessage),
    }));
    render(<FootprintWidget {...defaultProps} />);

    const panel = screen.getByTestId("footprint-panel");
    resizeObservedElement(panel, 220, 96);

    const compactError = screen.getByTestId("footprint-compact-state");
    expect(compactError).toHaveTextContent("Unable to load");
    expect(compactError).toHaveAttribute("tabindex", "0");
    expect(compactError).toHaveAccessibleName(`Unable to load: ${errorMessage}`);
    compactError.focus();
    expect(compactError).toHaveFocus();
    expect(screen.queryByText("Retrying automatically…")).not.toBeInTheDocument();
  });

  it("keyboard-focuses compact menu status and the legend tail", async () => {
    const user = userEvent.setup();
    const errorMessage = "Full compact footprint failure details";
    mockUseOrderFlow.mockReturnValue(hookResult({
      isError: true,
      error: new Error(errorMessage),
    }));
    render(<FootprintWidget {...defaultProps} />);

    const panel = screen.getByTestId("footprint-panel");
    resizeObservedElement(panel, 220, 96);
    await user.click(screen.getByRole("button", { name: "More footprint controls" }));

    const status = screen.getByTestId("footprint-menu-status");
    const legend = screen.getByTestId("footprint-compact-legend");
    expect(screen.getByTestId("footprint-compact-menu")).toHaveStyle({
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
    render(<FootprintWidget {...defaultProps} />);

    const panel = screen.getByTestId("footprint-panel");
    resizeObservedElement(panel, 220, 96);

    expect(screen.getByTestId("footprint-compact-state")).toHaveTextContent("Loading");
    expect(screen.queryByTestId("skeleton")).not.toBeInTheDocument();
  });

  it("labels the bucket-derived line as Latest POC, never LTP", () => {
    render(<FootprintWidget {...defaultProps} />);
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByText("Sell")).toBeInTheDocument();
    expect(screen.getByText("POC")).toBeInTheDocument();
    expect(screen.getByText("Latest POC")).toBeInTheDocument();
    expect(screen.queryByText("LTP")).not.toBeInTheDocument();
    expect(screen.getByText("Cum. Δ")).toBeInTheDocument();
  });

  it("shows 'No footprint data' when empty and not loading", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({ data: undefined }));
    render(<FootprintWidget {...defaultProps} />);
    expect(screen.getByText("No footprint data")).toBeInTheDocument();
  });

  it("shows loading skeletons and message when loading with no data", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({ isLoading: true }));
    render(<FootprintWidget {...defaultProps} />);
    expect(screen.getByText("Loading footprint data…")).toBeInTheDocument();
    const skeletons = screen.getAllByTestId("skeleton");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("shows Error badge when isError is true", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({ isError: true, error: new Error("Network failure") }),
    );
    render(<FootprintWidget {...defaultProps} />);
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(screen.getByText("Network failure")).toBeInTheDocument();
  });

  it("shows 'Live' badge when is_live is true", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: { buckets: sampleBuckets, symbol: "NIFTY", exchange: "NFO", interval: 300, is_live: true },
      }),
    );
    render(<FootprintWidget {...defaultProps} />);
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("renders exact trade-tick quality and provenance", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: {
          buckets: sampleBuckets.map((bucket) => ({
            ...bucket,
            quality: "exact",
            provenance: "trade_tick",
          })),
          symbol: "NIFTY",
          exchange: "NFO",
          interval: 300,
          is_live: true,
          quality: "exact",
          provenance: "trade_tick",
        },
      }),
    );

    render(<FootprintWidget {...defaultProps} />);

    expect(screen.getByText("Exact trades")).toBeInTheDocument();
    expect(screen.getByLabelText(/exact order flow.*trade ticks/i)).toBeInTheDocument();
  });

  it("renders cumulative-quote footprint data as estimated", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: {
          buckets: sampleBuckets.map((bucket) => ({
            ...bucket,
            quality: "estimated",
            provenance: "cumulative_quote_delta",
          })),
          symbol: "NIFTY",
          exchange: "NFO",
          interval: 300,
          is_live: true,
          quality: "estimated",
          provenance: "cumulative_quote_delta",
        },
      }),
    );

    render(<FootprintWidget {...defaultProps} />);

    expect(screen.getByText("Estimated quote deltas")).toBeInTheDocument();
    expect(screen.getByLabelText(/estimated order flow.*cumulative quote deltas/i)).toBeInTheDocument();
  });

  it("shows 'Sample data' badge when is_live is false", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: { buckets: sampleBuckets, symbol: "NIFTY", exchange: "NFO", interval: 300, is_live: false },
      }),
    );
    render(<FootprintWidget {...defaultProps} />);
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("shows 'Delayed' for retained backend data that is no longer live", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: {
          buckets: sampleBuckets,
          symbol: "NIFTY",
          exchange: "NFO",
          interval: 300,
          is_live: false,
          live_state: "delayed",
        },
      }),
    );

    render(<FootprintWidget {...defaultProps} />);

    expect(screen.getByText("Delayed")).toBeInTheDocument();
    expect(screen.getByLabelText(/retained footprint data is delayed/i)).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("shows 'Stale' for retained footprint data from an older session", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: {
          buckets: sampleBuckets,
          symbol: "NIFTY",
          exchange: "NFO",
          interval: 300,
          is_live: false,
          live_state: "stale",
        },
      }),
    );

    render(<FootprintWidget {...defaultProps} />);

    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("renders the canvas element", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: { buckets: sampleBuckets, symbol: "NIFTY", exchange: "NFO", interval: 300, is_live: false },
      }),
    );
    render(<FootprintWidget {...defaultProps} />);
    const canvas = screen.getByTestId("footprint-canvas");
    expect(canvas).toBeInTheDocument();
    expect(canvas.tagName).toBe("CANVAS");
  });

  it("replaces a pending paint after resizing clears the canvas backing store", () => {
    let nextAnimationFrameId = 1;
    const requestAnimationFrameMock = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((_callback: FrameRequestCallback) => nextAnimationFrameId++);
    const cancelAnimationFrameMock = vi
      .spyOn(window, "cancelAnimationFrame")
      .mockImplementation(() => undefined);
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: { buckets: sampleBuckets, symbol: "NIFTY", exchange: "NFO", interval: 300, is_live: false },
      }),
    );
    render(<FootprintWidget {...defaultProps} />);
    const pendingFrameId = requestAnimationFrameMock.mock.results.at(-1)?.value as number;
    const requestCount = requestAnimationFrameMock.mock.calls.length;

    resizeObservedElement(screen.getByTestId("footprint-chart"), 220, 64);

    expect(cancelAnimationFrameMock).toHaveBeenCalledWith(pendingFrameId);
    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(requestCount + 1);
    expect(screen.getByTestId("footprint-canvas")).toHaveAttribute("width", "220");
    expect(screen.getByTestId("footprint-canvas")).toHaveAttribute("height", "64");
  });

  it("updates the canvas backing store when only device pixel ratio changes", () => {
    vi.useFakeTimers();
    let devicePixelRatio = 1;
    vi.spyOn(window, "devicePixelRatio", "get").mockImplementation(() => devicePixelRatio);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: { buckets: sampleBuckets, symbol: "NIFTY", exchange: "NFO", interval: 300, is_live: false },
      }),
    );
    render(<FootprintWidget {...defaultProps} />);
    const chart = screen.getByTestId("footprint-chart");
    const canvas = screen.getByTestId("footprint-canvas");

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
      hookResult({
        data: {
          buckets: [sampleBuckets[0]],
          symbol: "NIFTY",
          exchange: "NFO",
          interval: 300,
          is_live: false,
        },
      }),
    );
    render(<FootprintWidget {...defaultProps} />);
    const chart = screen.getByTestId("footprint-chart");

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

  it("measures and subsamples twenty HH:MM:SS time labels", () => {
    const harness = installCanvasPaintHarness();
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: {
          buckets: twentySecondPrecisionBuckets,
          symbol: "NIFTY",
          exchange: "NFO",
          interval: 60,
          is_live: false,
        },
      }),
    );
    render(<FootprintWidget {...defaultProps} />);

    resizeObservedElement(screen.getByTestId("footprint-chart"), 520, 240);
    harness.runLatestFrame();

    const measuredTimes = harness.measureText.mock.calls
      .map(([label]) => String(label))
      .filter((label) => /^\d{2}:\d{2}:\d{2}$/.test(label));
    const paintedTimes = harness.fillText.mock.calls
      .map(([label]) => String(label))
      .filter((label) => /^\d{2}:\d{2}:\d{2}$/.test(label));
    expect(measuredTimes).toHaveLength(20);
    expect(paintedTimes.length).toBeGreaterThan(1);
    expect(paintedTimes.length).toBeLessThan(20);
  });

  it("requests the default NIFTY capture exchange", () => {
    render(<FootprintWidget {...defaultProps} />);
    expect(mockUseOrderFlow).toHaveBeenCalledWith("NIFTY", "NSE_INDEX", 300, 20);
  });

  it("syncs Dockview symbol and exchange parameter changes", () => {
    const initialProps = makeDockviewPanelProps({
      params: { symbol: "NIFTY", exchange: "NFO" },
    });
    const updatedProps = makeDockviewPanelProps({
      params: { symbol: "RELIANCE", exchange: "NSE" },
    });
    const { rerender } = render(<FootprintWidget {...initialProps} />);

    mockUseOrderFlow.mockClear();
    rerender(<FootprintWidget {...updatedProps} />);

    expect(mockUseOrderFlow).not.toHaveBeenCalledWith("NIFTY", "NSE", 300, 20);
    expect(mockUseOrderFlow).toHaveBeenLastCalledWith("RELIANCE", "NSE", 300, 20);
  });

  it("clears an explicit NFO exchange when the user changes symbol", () => {
    const updateParameters = vi.fn();
    const props = makeDockviewPanelProps({
      params: { symbol: "NIFTY", exchange: "NFO", displayMode: "compact" },
      api: { ...defaultProps.api, updateParameters },
    });
    render(<FootprintWidget {...props} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Symbol" }), {
      target: { value: "RELIANCE" },
    });

    expect(mockUseOrderFlow).toHaveBeenLastCalledWith("RELIANCE", "NSE", 300, 20);
    expect(updateParameters).toHaveBeenCalledWith({
      symbol: "RELIANCE",
      exchange: "NSE",
      displayMode: "compact",
    });
  });

  it("uses the backend interval in chart and legend labels", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: { buckets: sampleBuckets, symbol: "NIFTY", exchange: "NSE_INDEX", interval: 60, is_live: false },
      }),
    );

    render(<FootprintWidget {...defaultProps} />);

    expect(screen.getByText(/2 buckets.*NIFTY 1m/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /NIFTY 1m/ })).toBeInTheDocument();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(mockUseOrderFlow).toHaveBeenCalledWith("NIFTY", "NSE_INDEX", 300, 20);
  });

  it("shows bucket count in legend when data is present", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: { buckets: sampleBuckets, symbol: "NIFTY", exchange: "NFO", interval: 300, is_live: false },
      }),
    );
    render(<FootprintWidget {...defaultProps} />);
    // The legend shows "N buckets • NIFTY 5m"
    const legend = screen.getByText(/buckets/);
    expect(legend).toBeInTheDocument();
  });
});

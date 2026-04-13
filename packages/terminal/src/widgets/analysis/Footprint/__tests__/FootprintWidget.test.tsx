/**
 * FootprintWidget.test.tsx
 *
 * Tests for the Footprint chart widget.
 * Covers rendering, toolbar elements, status badges, and empty/loading/error states.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ─── Mocks ────────────────────────────────────────────────────────────────────

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const mockUseOrderFlow = vi.fn();

vi.mock("@/hooks/useOrderFlow", () => ({
  useOrderFlow: (...args: unknown[]) => mockUseOrderFlow(...args),
}));

vi.mock("@/components/ui/select", () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
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

const defaultProps = {} as Parameters<typeof FootprintWidget>[0];

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

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("FootprintWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it("shows legend items (Buy, Sell, POC, LTP, Cum. Δ)", () => {
    render(<FootprintWidget {...defaultProps} />);
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByText("Sell")).toBeInTheDocument();
    expect(screen.getByText("POC")).toBeInTheDocument();
    expect(screen.getByText("LTP")).toBeInTheDocument();
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

  it("shows 'Sample' badge when is_live is false", () => {
    mockUseOrderFlow.mockReturnValue(
      hookResult({
        data: { buckets: sampleBuckets, symbol: "NIFTY", exchange: "NFO", interval: 300, is_live: false },
      }),
    );
    render(<FootprintWidget {...defaultProps} />);
    expect(screen.getByText("Sample")).toBeInTheDocument();
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

  it("calls useOrderFlow with NFO exchange", () => {
    render(<FootprintWidget {...defaultProps} />);
    const [sym, exchange] = mockUseOrderFlow.mock.calls[0] as [string, string];
    expect(sym).toBe("NIFTY");
    expect(exchange).toBe("NFO");
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

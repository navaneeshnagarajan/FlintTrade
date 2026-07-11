/**
 * OrderFlowWidget.test.tsx
 *
 * Tests for the Order Flow footprint chart widget.
 * Verifies rendering, toolbar elements, and empty/loading states.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// Stub ResizeObserver (not available in JSDOM)
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

const defaultProps = makeDockviewPanelProps();

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OrderFlowWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    const initialProps = makeDockviewPanelProps({
      params: { symbol: "NIFTY", exchange: "NSE_INDEX" },
    });
    const updatedProps = makeDockviewPanelProps({
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
    const props = makeDockviewPanelProps({
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

  it("shows labelled icon controls for Footprint and Heatmap modes", () => {
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByRole("button", { name: "Footprint view" })).toHaveAttribute(
      "title",
      "Footprint view",
    );
    expect(screen.getByRole("button", { name: "Heatmap view" })).toHaveAttribute(
      "title",
      "Heatmap view",
    );
  });

  it("keeps every toolbar control accessible in a narrow wrapping panel", () => {
    render(
      <div style={{ width: "220px" }}>
        <OrderFlowWidget {...defaultProps} />
      </div>,
    );

    const toolbar = screen.getByRole("toolbar", { name: "Order flow controls" });
    expect(toolbar).toHaveClass("min-w-0", "flex-wrap");
    expect(within(toolbar).getByRole("combobox", { name: "Symbol" })).toBeInTheDocument();
    expect(within(toolbar).getByRole("group", { name: "View mode" })).toBeInTheDocument();
    expect(within(toolbar).getByRole("button", { name: "1m interval" })).toBeInTheDocument();
    expect(within(toolbar).getByRole("button", { name: "Heatmap view" })).toBeInTheDocument();

    const statusGroup = within(toolbar).getByTestId("order-flow-toolbar-status");
    expect(statusGroup).toHaveClass("min-w-0", "max-w-full", "flex-wrap");
  });

  it("labels the bucket-derived value and line as Latest POC, never LTP", () => {
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByText("Sell")).toBeInTheDocument();
    expect(screen.getByText("POC")).toBeInTheDocument();
    expect(screen.getByText("Latest POC")).toBeInTheDocument();
    expect(screen.queryByText("LTP")).not.toBeInTheDocument();
  });

  it("shows 'No data' when no buckets and not loading", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({ data: undefined }));
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("shows 'Live' badge when is_live is true", () => {
    const sampleData = {
      buckets: [
        {
          time_label: "09:15",
          cells: { "22500": { buy_volume: 100, sell_volume: 80 } },
          poc_price: 22500,
          total_volume: 180,
          delta: 20,
        },
      ],
      symbol: "NIFTY",
      exchange: "NFO",
      interval: 300,
      is_live: true,
    };
    mockUseOrderFlow.mockReturnValue(hookResult({ data: sampleData }));
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("renders exact trade-tick quality and provenance", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({
      data: {
        buckets: [{
          time_label: "09:15",
          cells: { "22500": { buy_volume: 100, sell_volume: 80 } },
          poc_price: 22500,
          total_volume: 180,
          delta: 20,
          quality: "exact",
          provenance: "trade_tick",
        }],
        symbol: "NIFTY",
        exchange: "NFO",
        interval: 300,
        is_live: true,
        quality: "exact",
        provenance: "trade_tick",
      },
    }));

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText("Exact trades")).toBeInTheDocument();
    expect(screen.getByLabelText(/exact order flow.*trade ticks/i)).toBeInTheDocument();
  });

  it("renders cumulative-quote order flow as estimated", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({
      data: {
        buckets: [{
          time_label: "09:15",
          cells: { "22500": { buy_volume: 100, sell_volume: 80 } },
          poc_price: 22500,
          total_volume: 180,
          delta: 20,
          quality: "estimated",
          provenance: "cumulative_quote_delta",
        }],
        symbol: "NIFTY",
        exchange: "NFO",
        interval: 300,
        is_live: true,
        quality: "estimated",
        provenance: "cumulative_quote_delta",
      },
    }));

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText("Estimated quote deltas")).toBeInTheDocument();
    expect(screen.getByLabelText(/estimated order flow.*cumulative quote deltas/i)).toBeInTheDocument();
  });

  it("uses the backend interval in chart and legend labels", () => {
    const sampleData = {
      buckets: [
        {
          time_label: "09:15",
          cells: { "22500": { buy_volume: 100, sell_volume: 80 } },
          poc_price: 22500,
          total_volume: 180,
          delta: 20,
        },
      ],
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      interval: 60,
      is_live: true,
    };
    mockUseOrderFlow.mockReturnValue(hookResult({ data: sampleData }));

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText(/1 bars.*NIFTY 1m/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /NIFTY, 1m interval/ })).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(mockUseOrderFlow).toHaveBeenCalledWith("NIFTY", "NSE_INDEX", 300, 20);
  });

  it("shows 'Sample data' badge when is_live is false", () => {
    const sampleData = {
      buckets: [
        {
          time_label: "09:15",
          cells: { "22500": { buy_volume: 100, sell_volume: 80 } },
          poc_price: 22500,
          total_volume: 180,
          delta: 20,
        },
      ],
      symbol: "NIFTY",
      exchange: "NFO",
      interval: 300,
      is_live: false,
    };
    mockUseOrderFlow.mockReturnValue(hookResult({ data: sampleData }));
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("keeps explicit sample provenance visible even if is_live is contradictory", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({
      data: {
        buckets: [
          {
            time_label: "09:15",
            cells: { "22500": { buy_volume: 100, sell_volume: 80 } },
            poc_price: 22500,
            total_volume: 180,
            delta: 20,
          },
        ],
        symbol: "NIFTY",
        exchange: "NFO",
        interval: 300,
        is_live: true,
        is_sample_data: true,
      },
    }));

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("shows 'Delayed' for retained backend data that is no longer live", () => {
    const delayedData = {
      buckets: [
        {
          time_label: "09:15",
          cells: { "22500": { buy_volume: 100, sell_volume: 80 } },
          poc_price: 22500,
          total_volume: 180,
          delta: 20,
        },
      ],
      symbol: "NIFTY",
      exchange: "NFO",
      interval: 300,
      is_live: false,
      live_state: "delayed",
    };
    mockUseOrderFlow.mockReturnValue(hookResult({ data: delayedData }));

    render(<OrderFlowWidget {...defaultProps} />);

    expect(screen.getByText("Delayed")).toBeInTheDocument();
    expect(screen.getByLabelText(/retained order flow data is delayed/i)).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("shows 'Stale' for retained order flow from an older session", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({
      data: {
        buckets: [{
          time_label: "15:25",
          cells: { "22500": { buy_volume: 100, sell_volume: 80 } },
          poc_price: 22500,
          total_volume: 180,
          delta: 20,
        }],
        symbol: "NIFTY",
        exchange: "NFO",
        interval: 300,
        is_live: false,
        live_state: "stale",
      },
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

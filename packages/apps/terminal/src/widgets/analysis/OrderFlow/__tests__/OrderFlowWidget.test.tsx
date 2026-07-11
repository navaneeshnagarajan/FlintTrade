/**
 * OrderFlowWidget.test.tsx
 *
 * Tests for the Order Flow footprint chart widget.
 * Verifies rendering, toolbar elements, and empty/loading states.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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

  it("shows view mode toggles (Footprint, Heatmap)", () => {
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("Footprint")).toBeInTheDocument();
    expect(screen.getByText("Heatmap")).toBeInTheDocument();
  });

  it("shows legend items (Buy, Sell, POC, LTP)", () => {
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByText("Sell")).toBeInTheDocument();
    expect(screen.getByText("POC")).toBeInTheDocument();
    // "LTP" appears in both the legend and the toolbar — use getAllByText
    const ltpElements = screen.getAllByText("LTP");
    expect(ltpElements.length).toBeGreaterThanOrEqual(1);
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

  it("shows 'Sample' badge when is_live is false", () => {
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
    expect(screen.getByText("Sample")).toBeInTheDocument();
  });

  it("shows loading skeletons when loading with no data", () => {
    mockUseOrderFlow.mockReturnValue(hookResult({ isLoading: true }));
    render(<OrderFlowWidget {...defaultProps} />);
    expect(screen.getByText("Loading order flow data...")).toBeInTheDocument();
  });
});

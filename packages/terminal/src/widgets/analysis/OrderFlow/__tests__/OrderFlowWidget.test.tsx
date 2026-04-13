/**
 * OrderFlowWidget.test.tsx
 *
 * Tests for the Order Flow footprint chart widget.
 * Verifies rendering, toolbar elements, and empty/loading states.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

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
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <div data-value={value}>{children}</div>
  ),
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
  SelectValue: () => <span>NIFTY</span>,
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

const defaultProps = {} as Parameters<typeof OrderFlowWidget>[0];

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

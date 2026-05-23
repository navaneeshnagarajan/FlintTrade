/**
 * DOMHeatmapWidget.test.tsx
 *
 * Tests for the DOM Heatmap widget.
 * Covers rendering, toolbar elements, canvas setup, and error states.
 * Polling is mocked so tests remain synchronous and side-effect-free.
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

// Mock getDepth — returns a minimal MarketDepth for the happy path
const mockGetDepth = vi.fn();
vi.mock("@/services/api", () => ({
  getDepth: (...args: unknown[]) => mockGetDepth(...args),
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
    ...props
  }: {
    children: React.ReactNode;
    [key: string]: unknown;
  }) => <span {...props}>{children}</span>,
}));

// ─── Import after mocks ───────────────────────────────────────────────────────

import DOMHeatmapWidget from "../DOMHeatmapWidget";

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("DOMHeatmapWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: getDepth never resolves during synchronous render
    mockGetDepth.mockReturnValue(new Promise(() => {}));
  });

  it("renders without crashing", () => {
    const { container } = render(<DOMHeatmapWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows DOM Heatmap heading", () => {
    render(<DOMHeatmapWidget />);
    expect(screen.getByText("DOM Heatmap")).toBeInTheDocument();
  });

  it("renders the heatmap canvas", () => {
    render(<DOMHeatmapWidget />);
    const canvas = screen.getByTestId("domheatmap-canvas");
    expect(canvas).toBeInTheDocument();
    expect(canvas.tagName).toBe("CANVAS");
  });

  it("renders the crosshair overlay canvas", () => {
    render(<DOMHeatmapWidget />);
    const xCanvas = screen.getByTestId("domheatmap-crosshair");
    expect(xCanvas).toBeInTheDocument();
  });

  it("shows 'Accumulating depth data' empty state initially", () => {
    render(<DOMHeatmapWidget />);
    expect(screen.getByText("Accumulating depth data…")).toBeInTheDocument();
  });

  it("shows legend items (Bid, Ask, Mid price)", () => {
    render(<DOMHeatmapWidget />);
    expect(screen.getByText("Bid (Buy)")).toBeInTheDocument();
    expect(screen.getByText("Ask (Sell)")).toBeInTheDocument();
    expect(screen.getByText("Mid price")).toBeInTheDocument();
  });

  it("shows symbol selector with NIFTY as default", () => {
    render(<DOMHeatmapWidget />);
    // SelectValue mock renders NIFTY — may appear in both trigger and item
    const niftyEls = screen.getAllByText("NIFTY");
    expect(niftyEls.length).toBeGreaterThanOrEqual(1);
  });

  it("shows snapshot counter", () => {
    render(<DOMHeatmapWidget />);
    // "0/60 snaps" format
    const counter = screen.getByText(/0\/60 snaps/);
    expect(counter).toBeInTheDocument();
  });

  it("calls getDepth on mount", () => {
    render(<DOMHeatmapWidget />);
    expect(mockGetDepth).toHaveBeenCalledWith("NIFTY", "NSE_INDEX");
  });

  it("shows error badge when getDepth rejects", async () => {
    mockGetDepth.mockRejectedValue(new Error("Connection refused"));
    const { act } = await import("react");
    await act(async () => {
      render(<DOMHeatmapWidget />);
    });
    await vi.waitFor(
      () => {
        expect(screen.getByText("Error")).toBeInTheDocument();
      },
      { timeout: 2000 },
    );
  });

  it("container has correct aria-label", () => {
    render(<DOMHeatmapWidget />);
    const container = screen.getByTestId("domheatmap-container");
    expect(container).toHaveAttribute("aria-label");
    expect(container.getAttribute("aria-label")).toContain("DOM heatmap");
  });
});

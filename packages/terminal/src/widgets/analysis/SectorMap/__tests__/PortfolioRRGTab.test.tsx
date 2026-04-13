/**
 * PortfolioRRGTab.test.tsx
 *
 * Tests for the Portfolio RRG tab within the SectorMap widget.
 * Verifies symbol management, localStorage persistence, and render states.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
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

// Stub canvas context (JSDOM does not implement Canvas 2D)
HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({
  clearRect: vi.fn(),
  fillRect: vi.fn(),
  fillText: vi.fn(),
  stroke: vi.fn(),
  beginPath: vi.fn(),
  moveTo: vi.fn(),
  lineTo: vi.fn(),
  arc: vi.fn(),
  fill: vi.fn(),
  save: vi.fn(),
  restore: vi.fn(),
  translate: vi.fn(),
  rotate: vi.fn(),
  scale: vi.fn(),
  setLineDash: vi.fn(),
  strokeStyle: "",
  fillStyle: "",
  lineWidth: 1,
  font: "",
  textAlign: "left",
});

const mockUseQuery = vi.fn();

vi.mock("@tanstack/react-query", () => ({
  useQuery: (...args: unknown[]) => mockUseQuery(...args),
}));

vi.mock("@/components/ui/input", () => ({
  Input: ({ ...props }: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({ children, onClick, disabled, ...rest }: {
    children: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    [key: string]: unknown;
  }) => (
    <button onClick={onClick} disabled={disabled} {...rest}>
      {children}
    </button>
  ),
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode; [key: string]: unknown }) => (
    <span {...props}>{children}</span>
  ),
}));

vi.mock("./RRGCanvas", () => ({
  RRG_QUADRANT_COLOURS: {
    leading:   { fill: "rgba(0, 200, 83, 0.07)",   dot: "#00C853", label: "Leading" },
    weakening: { fill: "rgba(255, 193, 7, 0.07)",  dot: "#FFC107", label: "Weakening" },
    improving: { fill: "rgba(33, 150, 243, 0.07)", dot: "#2196F3", label: "Improving" },
    lagging:   { fill: "rgba(244, 67, 54, 0.07)",  dot: "#F44336", label: "Lagging" },
    neutral:   { fill: "rgba(120, 120, 120, 0.05)", dot: "#888888", label: "Neutral" },
  },
}));

// ---------------------------------------------------------------------------
// localStorage stub
// ---------------------------------------------------------------------------

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock });

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import { PortfolioRRGTab } from "../PortfolioRRGTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PortfolioRRGTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();

    // Default: no data, not loading
    mockUseQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
  });

  it("renders the symbol input field", () => {
    render(<PortfolioRRGTab />);
    expect(screen.getByLabelText(/add symbol to portfolio rrg/i)).toBeInTheDocument();
  });

  it("shows empty state when no symbols are added", () => {
    render(<PortfolioRRGTab />);
    expect(screen.getByText(/add symbols above to plot them on the rrg/i)).toBeInTheDocument();
  });

  it("adds a symbol when Enter is pressed", () => {
    render(<PortfolioRRGTab />);
    const input = screen.getByLabelText(/add symbol to portfolio rrg/i);
    fireEvent.change(input, { target: { value: "RELIANCE" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
  });

  it("adds a symbol when + button is clicked", () => {
    render(<PortfolioRRGTab />);
    const input = screen.getByLabelText(/add symbol to portfolio rrg/i);
    fireEvent.change(input, { target: { value: "TCS" } });
    fireEvent.click(screen.getByLabelText(/add symbol$/i));
    expect(screen.getByText("TCS")).toBeInTheDocument();
  });

  it("converts input to uppercase", () => {
    render(<PortfolioRRGTab />);
    const input = screen.getByLabelText(/add symbol to portfolio rrg/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "reliance" } });
    // The onChange handler calls toUpperCase
    expect(input.value).toBe("RELIANCE");
  });

  it("does not add duplicate symbols", () => {
    render(<PortfolioRRGTab />);
    const input = screen.getByLabelText(/add symbol to portfolio rrg/i);
    fireEvent.change(input, { target: { value: "INFY" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "INFY" } });
    fireEvent.keyDown(input, { key: "Enter" });

    // INFY should appear exactly once as a chip
    const chips = screen.getAllByText("INFY");
    expect(chips.length).toBe(1);
  });

  it("removes a symbol when X button is clicked", () => {
    render(<PortfolioRRGTab />);
    const input = screen.getByLabelText(/add symbol to portfolio rrg/i);
    fireEvent.change(input, { target: { value: "WIPRO" } });
    fireEvent.keyDown(input, { key: "Enter" });

    // WIPRO chip should be visible
    expect(screen.getByText("WIPRO")).toBeInTheDocument();

    // Click the remove button
    fireEvent.click(screen.getByLabelText(/remove wipro/i));
    expect(screen.queryByText("WIPRO")).not.toBeInTheDocument();
  });

  it("persists symbols to localStorage", () => {
    render(<PortfolioRRGTab />);
    const input = screen.getByLabelText(/add symbol to portfolio rrg/i);
    fireEvent.change(input, { target: { value: "HDFC" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const stored = JSON.parse(localStorageMock.getItem("flinttrade_portfolio_rrg_symbols") ?? "[]") as string[];
    expect(stored).toContain("HDFC");
  });

  it("loads persisted symbols from localStorage on mount", () => {
    localStorageMock.setItem("flinttrade_portfolio_rrg_symbols", JSON.stringify(["PERSISTENT"]));
    render(<PortfolioRRGTab />);
    expect(screen.getByText("PERSISTENT")).toBeInTheDocument();
  });

  it("shows loading state when query is fetching", () => {
    // Add a symbol first so query runs
    localStorageMock.setItem("flinttrade_portfolio_rrg_symbols", JSON.stringify(["RELIANCE"]));

    mockUseQuery.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      refetch: vi.fn(),
    });

    render(<PortfolioRRGTab />);
    // Loading spinner — check for animate-spin class on the RefreshCw inside the canvas area
    const spinners = document.querySelectorAll(".animate-spin");
    expect(spinners.length).toBeGreaterThanOrEqual(1);
  });

  it("shows error state when fetch fails", () => {
    localStorageMock.setItem("flinttrade_portfolio_rrg_symbols", JSON.stringify(["RELIANCE"]));

    mockUseQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch: vi.fn(),
    });

    render(<PortfolioRRGTab />);
    expect(screen.getByText(/failed to load rrg data/i)).toBeInTheDocument();
  });
});

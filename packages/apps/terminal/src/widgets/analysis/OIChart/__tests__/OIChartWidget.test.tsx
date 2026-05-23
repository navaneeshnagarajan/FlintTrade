/**
 * OIChartWidget.test.tsx
 *
 * Tests for the OI Chart analysis widget.
 * Verifies rendering, loading states, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// Mock API calls used by the widget
vi.mock("@/services/api", () => ({
  getExpiry: vi.fn().mockResolvedValue([]),
  getOptionChain: vi.fn().mockResolvedValue({ calls: [], puts: [] }),
  getQuotes: vi.fn().mockResolvedValue({ ltp: 0 }),
  getMaxPain: vi.fn().mockResolvedValue({}),
}));

// Mock market hours helper
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// Mock PlotlyChart lazy import
vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import OIChartWidget from "../OIChartWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OIChartWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<OIChartWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the default symbol (NIFTY) in the selector", () => {
    render(<OIChartWidget />);
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
  });

  it("shows the exchange badge", () => {
    render(<OIChartWidget />);
    expect(screen.getByText("NFO")).toBeInTheDocument();
  });

  it("shows filter buttons (All, OI Increase, OI Decrease)", () => {
    render(<OIChartWidget />);
    expect(screen.getByText("All")).toBeInTheDocument();
    expect(screen.getByText("OI Increase")).toBeInTheDocument();
    expect(screen.getByText("OI Decrease")).toBeInTheDocument();
  });

  it("shows spot placeholder when no data loaded", () => {
    render(<OIChartWidget />);
    // Spot shows dash when no data
    expect(screen.getByText(/Spot/)).toBeInTheDocument();
  });
});

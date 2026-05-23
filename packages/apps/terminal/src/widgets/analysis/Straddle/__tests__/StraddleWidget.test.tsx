/**
 * StraddleWidget.test.tsx
 *
 * Tests for the Straddle analysis widget.
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
  getPositionbook: vi.fn().mockResolvedValue([]),
}));

// Mock market hours helper
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// Mock lightweight-charts to avoid canvas issues in JSDOM
vi.mock("lightweight-charts", () => ({
  createChart: () => ({
    addSeries: () => ({
      setData: vi.fn(),
      applyOptions: vi.fn(),
    }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }),
  LineSeries: "LineSeries",
}));

// Mock chart theme hook
vi.mock("@/hooks/useChartTheme", () => ({
  useLightweightChartTheme: () => ({
    layout: {},
    grid: {},
    rightPriceScale: {},
    timeScale: {},
  }),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import StraddleWidget from "../StraddleWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StraddleWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<StraddleWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the default symbol (NIFTY) in the selector", () => {
    render(<StraddleWidget />);
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
  });

  it("shows headline price labels (Straddle, CE, PE)", () => {
    render(<StraddleWidget />);
    // "Straddle" appears in both headline and overlay toggle — use getAllByText
    const straddleElements = screen.getAllByText("Straddle");
    expect(straddleElements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("CE")).toBeInTheDocument();
    expect(screen.getByText("PE")).toBeInTheDocument();
  });

  it("shows overlay toggle buttons", () => {
    render(<StraddleWidget />);
    expect(screen.getByText("Overlay")).toBeInTheDocument();
    expect(screen.getByText("Spot")).toBeInTheDocument();
    expect(screen.getByText("SynFut")).toBeInTheDocument();
  });
});

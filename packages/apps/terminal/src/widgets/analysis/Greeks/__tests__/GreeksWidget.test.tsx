/**
 * GreeksWidget.test.tsx
 *
 * Tests for the Portfolio Greeks analysis widget.
 * Verifies rendering, empty state, and summary cards.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const apiMocks = vi.hoisted(() => ({
  getPositionbook: vi.fn(),
  getMultiOptionGreeks: vi.fn(),
}));

// Mock API calls used by the widget
vi.mock("@/services/api", () => ({
  getPositionbook: apiMocks.getPositionbook,
  getMultiOptionGreeks: apiMocks.getMultiOptionGreeks,
}));

// Mock market hours helper
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import GreeksWidget from "../GreeksWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GreeksWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getPositionbook.mockResolvedValue([]);
    apiMocks.getMultiOptionGreeks.mockResolvedValue([]);
  });

  it("renders without crashing", () => {
    const { container } = render(<GreeksWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the Portfolio Greeks heading", () => {
    render(<GreeksWidget />);
    expect(screen.getByText("Portfolio Greeks")).toBeInTheDocument();
  });

  it("shows all four Greek summary cards", () => {
    render(<GreeksWidget />);
    expect(screen.getByText("Net Delta")).toBeInTheDocument();
    expect(screen.getByText("Net Gamma")).toBeInTheDocument();
    expect(screen.getByText("Net Theta")).toBeInTheDocument();
    expect(screen.getByText("Net Vega")).toBeInTheDocument();
  });

  it("shows empty state when no F&O positions", async () => {
    render(<GreeksWidget />);
    // The empty state text (with &amp; entity rendered)
    expect(await screen.findByText(/No F&O positions/)).toBeInTheDocument();
  });

  it("shows footer with refresh interval info", () => {
    render(<GreeksWidget />);
    expect(screen.getByText(/Greeks = per-leg/)).toBeInTheDocument();
  });

  it("requests native Greeks for Dhan CALL display aliases", async () => {
    apiMocks.getPositionbook.mockResolvedValue([{
      symbol: "DIVISLAB 28 JUL 3600 CALL",
      exchange: "NFO",
      quantity: 100,
      ltp: 42.5,
    }]);
    apiMocks.getMultiOptionGreeks.mockResolvedValue([{
      symbol: "DIVISLAB 28 JUL 3600 CALL",
      exchange: "NFO",
      instrument_id: "12345",
      delta: 0.52,
      gamma: 0.001,
      theta: -5,
      vega: 6.4,
      iv: 18.4,
    }]);

    render(<GreeksWidget />);

    await waitFor(() => expect(apiMocks.getMultiOptionGreeks).toHaveBeenCalledWith([{
      symbol: "DIVISLAB 28 JUL 3600 CALL",
      exchange: "NFO",
    }]));
    expect(await screen.findByText("DIVISLAB 28 JUL 3600 CALL")).toBeInTheDocument();
  });

  it("matches reordered native Greeks by contract identity", async () => {
    apiMocks.getPositionbook.mockResolvedValue([
      { symbol: "NIFTY24600CE", exchange: "NFO", quantity: 1 },
      { symbol: "NIFTY24700PE", exchange: "NFO", quantity: 1 },
    ]);
    apiMocks.getMultiOptionGreeks.mockResolvedValue([
      {
        symbol: "NIFTY24700PE", exchange: "NFO", instrument_id: "NSE_FO|PE",
        delta: -0.45, gamma: 0.003, theta: -7.1, vega: 5.4, iv: 14.2,
      },
      {
        symbol: "NIFTY24600CE", exchange: "NFO", instrument_id: "NSE_FO|CE",
        delta: 0.55, gamma: 0.002, theta: -8.1, vega: 6.4, iv: 13.2,
      },
    ]);

    render(<GreeksWidget />);

    const callRow = (await screen.findByText("NIFTY24600CE")).closest("tr");
    const putRow = screen.getByText("NIFTY24700PE").closest("tr");
    expect(callRow).not.toBeNull();
    expect(putRow).not.toBeNull();
    expect(within(callRow!).getByText("+0.55")).toBeInTheDocument();
    expect(within(putRow!).getByText("-0.45")).toBeInTheDocument();
  });

  it("surfaces a native option-Greeks read failure", async () => {
    apiMocks.getPositionbook.mockResolvedValue([{
      symbol: "NIFTY30JUL2625000CE",
      exchange: "NFO",
      quantity: 75,
    }]);
    apiMocks.getMultiOptionGreeks.mockRejectedValue(new Error("native Dhan Greek read failed"));

    render(<GreeksWidget />);

    expect(await screen.findByText("Option Greeks error: native Dhan Greek read failed")).toBeInTheDocument();
    for (const label of ["Net Delta", "Net Gamma", "Net Theta", "Net Vega"]) {
      expect(within(screen.getByText(label).parentElement!).getByText("—")).toBeInTheDocument();
    }
  });

  it("does not render blank Greek strings as zero exposure", async () => {
    apiMocks.getPositionbook.mockResolvedValue([{
      symbol: "NIFTY30JUL2625000CE",
      exchange: "NFO",
      quantity: 75,
    }]);
    apiMocks.getMultiOptionGreeks.mockResolvedValue([{
      symbol: "NIFTY30JUL2625000CE",
      exchange: "NFO",
      instrument_id: "NSE_FO|CE",
      delta: " ",
      gamma: "",
      theta: " ",
      vega: "",
      iv: " ",
    }]);

    render(<GreeksWidget />);

    await screen.findByText("NIFTY30JUL2625000CE");
    for (const label of ["Net Delta", "Net Gamma", "Net Theta", "Net Vega"]) {
      expect(within(screen.getByText(label).parentElement!).getByText("—")).toBeInTheDocument();
    }
  });
});

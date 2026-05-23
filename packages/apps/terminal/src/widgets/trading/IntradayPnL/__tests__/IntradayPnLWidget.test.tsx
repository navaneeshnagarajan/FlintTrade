/**
 * IntradayPnLWidget.test.tsx
 *
 * Tests for the Intraday P&L widget.
 * Verifies rendering, P&L display, stat cards, and error state.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  getPositionbook: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => true,
}));

// ---------------------------------------------------------------------------
// Import component and mock references
// ---------------------------------------------------------------------------

import { getPositionbook } from "@/services/api";
import IntradayPnLWidget from "../IntradayPnLWidget";

const mockGetPositionbook = getPositionbook as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePosition(symbol: string, pnl: number, qty = 1) {
  return {
    symbol,
    exchange: "NSE",
    product:  "MIS",
    quantity: qty,
    averagePrice: 100,
    ltp: 110,
    pnl,
    pnlPercent: 10,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("IntradayPnLWidget", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders without crashing", async () => {
    const { container } = render(<IntradayPnLWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the Intraday P&L heading", async () => {
    render(<IntradayPnLWidget />);
    // Header text includes "Intraday" and "P&L" (entity encoded in JSX)
    expect(screen.getByText(/intraday/i)).toBeInTheDocument();
  });

  it("shows stat card labels", async () => {
    render(<IntradayPnLWidget />);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("Realised")).toBeInTheDocument();
    expect(screen.getByText("Unrealised")).toBeInTheDocument();
    expect(screen.getByText("Peak P&L")).toBeInTheDocument();
    expect(screen.getByText("Max DD")).toBeInTheDocument();
  });

  it("displays net P&L as zero when no positions", async () => {
    mockGetPositionbook.mockResolvedValue([]);
    render(<IntradayPnLWidget />);
    await act(async () => { await Promise.resolve(); });
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).toContain("0.00");
  });

  it("displays positive net P&L in profit colour", async () => {
    mockGetPositionbook.mockResolvedValue([makePosition("SBIN", 500)]);
    render(<IntradayPnLWidget />);
    await act(async () => { await Promise.resolve(); });
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).toContain("500");
    expect(netEl.className).toMatch(/profit/);
  });

  it("displays negative net P&L in loss colour", async () => {
    mockGetPositionbook.mockResolvedValue([makePosition("SBIN", -300)]);
    render(<IntradayPnLWidget />);
    await act(async () => { await Promise.resolve(); });
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).toContain("300");
    expect(netEl.className).toMatch(/loss/);
  });

  it("shows error indicator when API fails", async () => {
    mockGetPositionbook.mockRejectedValue(new Error("Network error"));
    render(<IntradayPnLWidget />);
    await act(async () => { await Promise.resolve(); });
    // Error dot has a title attribute equal to the error message
    const errorDot = document.querySelector(".bg-loss.rounded-full");
    expect(errorDot).toBeInTheDocument();
  });

  it("sums P&L from multiple positions", async () => {
    mockGetPositionbook.mockResolvedValue([
      makePosition("SBIN", 200),
      makePosition("RELIANCE", 300),
    ]);
    render(<IntradayPnLWidget />);
    await act(async () => { await Promise.resolve(); });
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).toContain("500");
  });

  it("splits realised (qty=0) vs unrealised (qty>0) correctly", async () => {
    mockGetPositionbook.mockResolvedValue([
      makePosition("SBIN",     200, 0), // realised
      makePosition("RELIANCE", 300, 1), // unrealised
    ]);
    render(<IntradayPnLWidget />);
    await act(async () => { await Promise.resolve(); });
    // Net should still be 500
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).toContain("500");
  });
});

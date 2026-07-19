/**
 * IntradayPnLWidget.test.tsx
 *
 * Tests for the Intraday P&L widget.
 * Verifies rendering, P&L display, stat cards, and error state.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  getPositionbook: vi.fn().mockResolvedValue([]),
  getTradebook: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/services/ftApi.native", () => ({
  listNativeAccounts: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => true,
}));

// ---------------------------------------------------------------------------
// Import component and mock references
// ---------------------------------------------------------------------------

import { getPositionbook, getTradebook } from "@/services/api";
import IntradayPnLWidget from "../IntradayPnLWidget";

const mockGetPositionbook = getPositionbook as ReturnType<typeof vi.fn>;
const mockGetTradebook = getTradebook as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePosition(symbol: string, pnl: number, qty = 1) {
  // (ltp − averagePrice) × qty reproduces `pnl` so the locally computed MTM
  // (preferred over the broker figure) equals the requested value; closed
  // positions (qty = 0) fall back to the broker-supplied pnl.
  return {
    symbol,
    exchange: "NSE",
    product:  "MIS",
    quantity: qty,
    averagePrice: 100,
    ltp: qty === 0 ? 110 : 100 + pnl / qty,
    pnl,
    pnlPercent: 10,
  };
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={qc}>
      <IntradayPnLWidget />
    </QueryClientProvider>,
  );
  return { ...utils, qc };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("IntradayPnLWidget", () => {
  beforeEach(() => {
    // No fake timers: the widget no longer owns a poll loop — data flows
    // through the shared TanStack caches, whose fetch cycle needs real
    // microtask/macrotask scheduling to settle in tests.
    // Full reset (not clearAllMocks): pending mockResolvedValueOnce queues
    // from a prior test must not feed a later test's first shared-cache fetch.
    mockGetPositionbook.mockReset();
    mockGetTradebook.mockReset();
    mockGetPositionbook.mockResolvedValue([]);
    mockGetTradebook.mockResolvedValue([]);
  });

  it("renders without crashing", async () => {
    const { container } = renderWidget();
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the Intraday P&L heading", async () => {
    renderWidget();
    // Header text includes "Intraday" and "P&L" (entity encoded in JSX)
    expect(screen.getByText(/intraday/i)).toBeInTheDocument();
  });

  it("shows stat card labels", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("Realised")).toBeInTheDocument());
    expect(screen.getByText("Unrealised")).toBeInTheDocument();
    expect(screen.getByText("Peak P&L")).toBeInTheDocument();
    expect(screen.getByText("Max DD")).toBeInTheDocument();
  });

  it("displays net P&L as zero when no positions", async () => {
    mockGetPositionbook.mockResolvedValue([]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("0.00"),
    );
  });

  it("displays positive net P&L in profit colour", async () => {
    mockGetPositionbook.mockResolvedValue([makePosition("SBIN", 500)]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("500"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.className).toMatch(/profit/);
  });

  it("renders the equity curve through the shared Flint baseline primitive once snapshots exist", async () => {
    mockGetPositionbook
      .mockResolvedValueOnce([makePosition("SBIN", 500)])
      .mockResolvedValueOnce([makePosition("SBIN", -250)]);

    const { qc } = renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("500"),
    );
    // Second positions refresh — with the shared cache the cadence belongs to
    // usePositions, so the test drives it via the query client.
    await act(async () => {
      await qc.refetchQueries();
      await new Promise((r) => setTimeout(r, 0));
    });

    const chart = screen.getByRole("img", { name: "Intraday P&L equity curve" });
    expect(chart).toHaveAttribute("viewBox", "0 0 160 42");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelector("line")).toBeInTheDocument();
    expect(chart.querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("displays negative net P&L in loss colour", async () => {
    mockGetPositionbook.mockResolvedValue([makePosition("SBIN", -300)]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("300"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.className).toMatch(/loss/);
  });

  it("shows error indicator when API fails", async () => {
    mockGetPositionbook.mockRejectedValue(new Error("Network error"));
    renderWidget();
    // The error state lands after the query's retry cycle — wait for the
    // dot itself rather than racing it with a fixed flush.
    await waitFor(() => {
      expect(document.querySelector(".bg-loss.rounded-full")).toBeInTheDocument();
    }, { timeout: 5000 });
  });

  it("sums P&L from multiple positions", async () => {
    mockGetPositionbook.mockResolvedValue([
      makePosition("SBIN", 200),
      makePosition("RELIANCE", 300),
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("500"),
    );
  });

  it("splits realised (qty=0) vs unrealised (qty>0) correctly", async () => {
    mockGetPositionbook.mockResolvedValue([
      makePosition("SBIN",     200, 0), // realised
      makePosition("RELIANCE", 300, 1), // unrealised
    ]);
    renderWidget();
    // Net should still be 500
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("500"),
    );
  });

  it("books partial-close realised from the tradebook for a still-open position", async () => {
    // Bought 100 @ 100, sold 40 @ 110 (realised 400), 60 still open. positionbook
    // shows only the open 60 @ avg 100, ltp 105 (unrealised 300) — its booked
    // realised is invisible without the tradebook.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 60, averagePrice: 100, ltp: 105, pnl: 99999, pnlPercent: 0 },
    ]);
    mockGetTradebook.mockResolvedValue([
      { tradeId: "T1", orderId: "O1", symbol: "SBIN", exchange: "NSE", action: "BUY", quantity: 100, price: 100, timestamp: "2026-07-09T09:20:00Z" },
      { tradeId: "T2", orderId: "O2", symbol: "SBIN", exchange: "NSE", action: "SELL", quantity: 40, price: 110, timestamp: "2026-07-09T10:00:00Z" },
    ]);
    renderWidget();
    // Realised = (110 − 100) × 40 = 400 (from tradebook, not double-counted in
    // unrealised); Unrealised = (105 − 100) × 60 = 300 (open MTM); Net = 700.
    await waitFor(() =>
      expect(screen.getByText("Realised").parentElement).toHaveTextContent("+₹400.00"),
    );
    expect(screen.getByText("Unrealised").parentElement).toHaveTextContent("+₹300.00");
    expect(screen.getByTestId("net-pnl").textContent).toContain("700");
  });

  // ── Broker numeric coercion + local P&L (OpenAlgo quirk 4) ────────────────

  it("computes open-position P&L locally instead of trusting a wrong broker pnl", async () => {
    // Broker reports a wildly wrong pnl; local MTM = (110 − 100) × 10 = 100.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 10, averagePrice: 100, ltp: 110, pnl: 999999, pnlPercent: 0 },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("100.00"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).not.toContain("9,99,999");
  });

  it("coerces string-typed quantity/ltp/average_price from real adapters", async () => {
    // Wire-format row: snake_case average_price and every numeric as a string.
    // Local MTM = (150 − 134) × 75 = 1,200.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "NIFTY24APR24000CE", exchange: "NFO", product: "NRML", quantity: "75", average_price: "134", ltp: "150", pnl: "0" },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("1,200.00"),
    );
  });

  it("treats a string \"0\" quantity as a closed position (realised broker pnl)", async () => {
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: "0", pnl: "150.25" },
    ]);
    renderWidget();
    // Falls into the Realised bucket (local computation impossible for closed);
    // the same figure legitimately repeats in Net and Peak P&L, so assert the
    // buckets via their stat cards rather than a bare text query.
    await waitFor(() =>
      expect(screen.getByText("Realised").parentElement).toHaveTextContent("+₹150.25"),
    );
    expect(screen.getByText("Unrealised").parentElement).toHaveTextContent("+₹0.00");
    expect(screen.getByTestId("net-pnl").textContent).toContain("150.25");
  });

  it("falls back to the broker pnl when LTP or average price is missing", async () => {
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 5, pnl: "250.5" },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("250.50"),
    );
  });

  it("does not fabricate a loss when the broker reports ltp: 0 for an open position", async () => {
    // Illiquid/pre-market open long: broker LTP is a literal 0 but the pnl
    // field is correct. (0 − 134) × 75 = −10,050 would be a fabricated loss;
    // the widget must fall back to the broker pnl instead.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "NIFTY24APR24000CE", exchange: "NFO", product: "NRML", quantity: 75, averagePrice: 134, ltp: 0, pnl: 375, pnlPercent: 0 },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("375.00"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).not.toContain("10,050");
  });

  it("does not fabricate P&L when the broker reports averagePrice: 0", async () => {
    // averagePrice 0 would make (ltp − 0) × qty the full notional shown as P&L.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 10, averagePrice: 0, ltp: 110, pnl: 42.5, pnlPercent: 0 },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("42.50"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).not.toContain("1,100");
  });

  it("guards against non-numeric garbage instead of rendering NaN", async () => {
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: "abc", pnl: "N/A", ltp: "", average_price: null },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("0.00"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).not.toContain("NaN");
  });
});

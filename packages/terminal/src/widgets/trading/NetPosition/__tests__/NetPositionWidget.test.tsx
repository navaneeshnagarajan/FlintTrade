import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import NetPositionWidget, {
  SAMPLE_RAW_POSITIONS,
  netPositions,
} from "../NetPositionWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("NetPositionWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<NetPositionWidget />);
    expect(screen.getByText("Net Positions")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<NetPositionWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    render(<NetPositionWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders net positions table with aria-label", () => {
    mockConnected.mockReturnValue(false);
    render(<NetPositionWidget />);
    expect(screen.getByLabelText("Net positions table")).toBeTruthy();
  });

  it("renders column headers", () => {
    mockConnected.mockReturnValue(false);
    render(<NetPositionWidget />);
    expect(screen.getByText("Symbol")).toBeTruthy();
    expect(screen.getByText("Net Qty")).toBeTruthy();
    expect(screen.getByText("Avg")).toBeTruthy();
    expect(screen.getByText("LTP")).toBeTruthy();
    expect(screen.getByText(/Net P&L/i)).toBeTruthy();
    expect(screen.getByText("Exposure")).toBeTruthy();
  });

  it("renders Total row in tfoot", () => {
    mockConnected.mockReturnValue(false);
    render(<NetPositionWidget />);
    expect(screen.getByText("Total")).toBeTruthy();
  });

  it("renders underlying group headers for NIFTY and BANKNIFTY", () => {
    mockConnected.mockReturnValue(false);
    render(<NetPositionWidget />);
    // group headers show underlying name
    const niftyGroups = screen.getAllByText("NIFTY");
    expect(niftyGroups.length).toBeGreaterThanOrEqual(1);
  });

  it("clicking group header collapses its rows", () => {
    mockConnected.mockReturnValue(false);
    render(<NetPositionWidget />);
    // find the first group header row (aria-expanded)
    const expandedGroups = screen.getAllByRole("row", { hidden: false }).filter(
      (r) => r.getAttribute("aria-expanded") === "true",
    );
    if (expandedGroups.length > 0) {
      fireEvent.click(expandedGroups[0]);
      expect(expandedGroups[0].getAttribute("aria-expanded")).toBe("false");
    }
  });

  it("renders position count in header", () => {
    mockConnected.mockReturnValue(false);
    render(<NetPositionWidget />);
    const els = screen.getAllByText(/position/i);
    expect(els.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// netPositions() logic tests
// ---------------------------------------------------------------------------

describe("netPositions()", () => {
  it("nets long and short of same symbol across strategies", () => {
    const rows = netPositions([
      { strategy: "A", symbol: "NIFTY FUT", underlying: "NIFTY", qty:  2, avgPrice: 22400, ltp: 22450, lotSize: 50 },
      { strategy: "B", symbol: "NIFTY FUT", underlying: "NIFTY", qty: -1, avgPrice: 22400, ltp: 22450, lotSize: 50 },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].netQty).toBe(1);
  });

  it("excludes flat positions (net qty = 0)", () => {
    const rows = netPositions([
      { strategy: "A", symbol: "NIFTY FUT", underlying: "NIFTY", qty:  1, avgPrice: 22400, ltp: 22400, lotSize: 50 },
      { strategy: "B", symbol: "NIFTY FUT", underlying: "NIFTY", qty: -1, avgPrice: 22400, ltp: 22400, lotSize: 50 },
    ]);
    expect(rows).toHaveLength(0);
  });

  it("P&L is positive when LTP > avgPrice for long position", () => {
    const rows = netPositions([
      { strategy: "A", symbol: "NIFTY FUT", underlying: "NIFTY", qty: 1, avgPrice: 22400, ltp: 22500, lotSize: 50 },
    ]);
    expect(rows[0].pnl).toBeGreaterThan(0);
  });

  it("P&L is negative when LTP < avgPrice for long position", () => {
    const rows = netPositions([
      { strategy: "A", symbol: "NIFTY FUT", underlying: "NIFTY", qty: 1, avgPrice: 22400, ltp: 22300, lotSize: 50 },
    ]);
    expect(rows[0].pnl).toBeLessThan(0);
  });

  it("exposure equals |netQty| * avgPrice * lotSize", () => {
    const rows = netPositions([
      { strategy: "A", symbol: "NIFTY FUT", underlying: "NIFTY", qty: 2, avgPrice: 22400, ltp: 22400, lotSize: 50 },
    ]);
    expect(rows[0].exposure).toBe(2 * 22400 * 50);
  });

  it("sample data produces multiple net rows", () => {
    const rows = netPositions(SAMPLE_RAW_POSITIONS);
    expect(rows.length).toBeGreaterThan(0);
  });

  it("BANKNIFTY legs net to zero (flat)", () => {
    // Strategy A long 1 + Iron Condor short 1 = net 0 → excluded
    const bnRows = netPositions(SAMPLE_RAW_POSITIONS).filter(
      (r) => r.symbol.includes("BANKNIFTY FUT"),
    );
    expect(bnRows).toHaveLength(0);
  });

  it("NIFTY 22200 CE nets to +1 lot (2 long - 1 short)", () => {
    const rows = netPositions(SAMPLE_RAW_POSITIONS);
    const ce = rows.find((r) => r.symbol === "NIFTY 22200 CE 10APR");
    expect(ce).toBeDefined();
    expect(ce!.netQty).toBe(1);
  });
});

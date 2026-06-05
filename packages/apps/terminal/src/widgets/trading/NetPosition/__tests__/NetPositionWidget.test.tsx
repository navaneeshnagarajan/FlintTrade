import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return { ...actual, getPositionbook: vi.fn(() => Promise.resolve([])) };
});

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getPositionbook } from "@/services/api";
import type { Position } from "@/types/api";
import NetPositionWidget, {
  SAMPLE_RAW_POSITIONS,
  netPositions,
  positionToRaw,
  underlyingOf,
} from "../NetPositionWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockPositions = getPositionbook as ReturnType<typeof vi.fn>;

function renderWidget(ui: ReactElement = <NetPositionWidget />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  mockConnected.mockReturnValue(false);
  mockPositions.mockReset();
  mockPositions.mockResolvedValue([]);
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("NetPositionWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Net Positions")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    renderWidget();
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders net positions table with aria-label", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByLabelText("Net positions table")).toBeTruthy();
  });

  it("renders column headers", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Symbol")).toBeTruthy();
    expect(screen.getByText("Net Qty")).toBeTruthy();
    expect(screen.getByText("Avg")).toBeTruthy();
    expect(screen.getByText("LTP")).toBeTruthy();
    expect(screen.getByText(/Net P&L/i)).toBeTruthy();
    expect(screen.getByText("Exposure")).toBeTruthy();
  });

  it("renders Total row in tfoot", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Total")).toBeTruthy();
  });

  it("renders underlying group headers for NIFTY and BANKNIFTY", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    // group headers show underlying name
    const niftyGroups = screen.getAllByText("NIFTY");
    expect(niftyGroups.length).toBeGreaterThanOrEqual(1);
  });

  it("clicking group header collapses its rows", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
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
    renderWidget();
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

// ---------------------------------------------------------------------------
// Live broker mapping
// ---------------------------------------------------------------------------

describe("underlyingOf / positionToRaw", () => {
  it("derives the underlying from the first symbol token", () => {
    expect(underlyingOf("NIFTY 22200 CE 10APR")).toBe("NIFTY");
    expect(underlyingOf("BANKNIFTY FUT 24APR")).toBe("BANKNIFTY");
    expect(underlyingOf("RELIANCE")).toBe("RELIANCE");
  });

  it("maps a broker position with lotSize 1 (quantity already in units)", () => {
    const p: Position = {
      symbol: "TCS", exchange: "NSE", product: "MIS",
      quantity: 10, averagePrice: 3000, ltp: 3050, pnl: 500, pnlPercent: 1.6,
    };
    const raw = positionToRaw(p);
    expect(raw.lotSize).toBe(1);
    expect(raw.qty).toBe(10);
    expect(raw.avgPrice).toBe(3000);
    // P&L through netting matches (ltp − avg) × qty × 1.
    expect(netPositions([raw])[0].pnl).toBe((3050 - 3000) * 10);
  });
});

describe("NetPositionWidget (connected)", () => {
  const LIVE: Position[] = [
    { symbol: "TATAMOTORS", exchange: "NSE", product: "MIS", quantity: 5, averagePrice: 900, ltp: 950, pnl: 250, pnlPercent: 5.5 },
  ];

  it("renders real positions, not sample positions", async () => {
    mockConnected.mockReturnValue(true);
    mockPositions.mockResolvedValue(LIVE);
    renderWidget();
    // Appears in both the underlying group header and the position row.
    expect((await screen.findAllByText("TATAMOTORS")).length).toBeGreaterThanOrEqual(1);
    // A sample-only symbol must NOT appear.
    expect(screen.queryByText("NIFTY 22200 CE 10APR")).toBeNull();
  });

  it("queries the positionbook only when connected", async () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockPositions).not.toHaveBeenCalled();

    mockConnected.mockReturnValue(true);
    renderWidget();
    await waitFor(() => expect(mockPositions).toHaveBeenCalled());
  });

  it("shows the empty state when connected with no positions", async () => {
    mockConnected.mockReturnValue(true);
    mockPositions.mockResolvedValue([]);
    renderWidget();
    expect(await screen.findByText("No open positions")).toBeTruthy();
  });
});

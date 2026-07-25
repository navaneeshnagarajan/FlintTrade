import { describe, it, expect } from "vitest";
import { realisedFromTrades, realisedBySymbol, positionMtm, totalPositionMtm } from "./pnl";
import type { Trade } from "@/types/api";

function trade(symbol: string, action: "BUY" | "SELL", quantity: number, price: number): Trade {
  return {
    tradeId: `${symbol}-${action}-${quantity}-${price}`,
    orderId: "O",
    symbol,
    exchange: "NSE",
    action,
    quantity,
    price,
    timestamp: "2026-07-09T09:20:00Z",
  };
}

describe("realisedFromTrades", () => {
  it("returns 0 for no trades", () => {
    expect(realisedFromTrades([])).toBe(0);
  });

  it("books a full intraday round-trip", () => {
    // BUY 10 @ 100, SELL 10 @ 110 → (110 − 100) × 10 = 100.
    expect(realisedFromTrades([trade("SBIN", "BUY", 10, 100), trade("SBIN", "SELL", 10, 110)])).toBe(100);
  });

  it("books only the matched quantity of a partial close", () => {
    // BUY 100 @ 100, SELL 40 @ 110 → (110 − 100) × 40 = 400; 60 stay open.
    expect(realisedFromTrades([trade("SBIN", "BUY", 100, 100), trade("SBIN", "SELL", 40, 110)])).toBe(400);
  });

  it("pairs legs FIFO across multiple buys", () => {
    // BUY 10 @ 100, BUY 10 @ 120, SELL 15 @ 130.
    // FIFO: 10 vs first buy → (130−100)×10 = 300; 5 vs second buy → (130−120)×5 = 50. Total 350.
    expect(
      realisedFromTrades([
        trade("SBIN", "BUY", 10, 100),
        trade("SBIN", "BUY", 10, 120),
        trade("SBIN", "SELL", 15, 130),
      ]),
    ).toBe(350);
  });

  it("keeps symbols independent", () => {
    const realised = realisedFromTrades([
      trade("SBIN", "BUY", 10, 100),
      trade("SBIN", "SELL", 10, 110), // +100
      trade("TCS", "BUY", 5, 3000),
      trade("TCS", "SELL", 5, 2990), // −50
    ]);
    expect(realised).toBe(50);
  });

  it("realisedBySymbol attributes realised per symbol", () => {
    const bySymbol = realisedBySymbol([
      trade("SBIN", "BUY", 10, 100),
      trade("SBIN", "SELL", 10, 110),
      trade("TCS", "BUY", 5, 3000),
      trade("TCS", "SELL", 5, 2990),
    ]);
    expect(bySymbol.get("SBIN")).toBe(100);
    expect(bySymbol.get("TCS")).toBe(-50);
  });
});

// ---------------------------------------------------------------------------
// positionMtm / totalPositionMtm — the single "what is my P&L right now"
// definition. MTM Monitor and the P&L dashboard used to sum the raw broker
// `pnl` field while the Intraday P&L widget corrected it, so two widgets
// docked side by side reported different totals for the same book.
// ---------------------------------------------------------------------------

describe("positionMtm", () => {
  const open = (over: Record<string, unknown> = {}) => ({
    symbol: "NIFTY24JUL24000CE",
    exchange: "NFO",
    product: "MIS",
    quantity: 75,
    averagePrice: 100,
    ltp: 110,
    pnl: 9999, // deliberately wrong broker figure
    ...over,
  }) as never;

  it("computes the local mark-to-market instead of trusting a wrong broker pnl", () => {
    expect(positionMtm(open())).toBe(750); // (110 − 100) × 75
  });

  it("coerces string-typed wire numerics", () => {
    expect(positionMtm(open({ quantity: "75", averagePrice: "100", ltp: "110" }))).toBe(750);
  });

  it("reads the snake_case average price some adapters send", () => {
    expect(positionMtm(open({ averagePrice: undefined, average_price: 100 }))).toBe(750);
  });

  it("falls back to the broker figure for a closed position", () => {
    expect(positionMtm(open({ quantity: 0, pnl: 1234 }))).toBe(1234);
  });

  it("treats a zero LTP as missing rather than fabricating a total loss", () => {
    // Several brokers report ltp: 0 for an open position (illiquid option,
    // pre-market). (0 − 100) × 75 would invent a ₹7,500 loss.
    expect(positionMtm(open({ ltp: 0, pnl: 250 }))).toBe(250);
  });

  it("treats a zero average price as missing", () => {
    expect(positionMtm(open({ averagePrice: 0, pnl: 250 }))).toBe(250);
  });

  it("returns zero rather than NaN when everything is missing", () => {
    expect(positionMtm({ quantity: 0 } as never)).toBe(0);
  });
});

describe("totalPositionMtm", () => {
  it("sums the corrected per-position figures, not the broker ones", () => {
    const book = [
      { quantity: 75, averagePrice: 100, ltp: 110, pnl: 1 },
      { quantity: 50, averagePrice: 200, ltp: 190, pnl: 2 },
    ] as never[];
    // (110−100)×75 = 750, (190−200)×50 = −500 → 250. Broker sum would be 3.
    expect(totalPositionMtm(book)).toBe(250);
  });
});

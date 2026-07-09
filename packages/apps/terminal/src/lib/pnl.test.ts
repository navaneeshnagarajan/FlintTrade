import { describe, it, expect } from "vitest";
import { realisedFromTrades, realisedBySymbol } from "./pnl";
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

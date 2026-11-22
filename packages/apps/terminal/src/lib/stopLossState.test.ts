import { describe, expect, it, vi } from "vitest";

import {
  exitNowTicket,
  isStopLossTriggeredNotFilled,
  openExitTicket,
  stopLossNotFilledKeys,
} from "./stopLossState";

describe("stop-loss triggered, not filled", () => {
  it("flags a Practice stop-limit whose trigger was hit", () => {
    expect(isStopLossTriggeredNotFilled({ pricetype: "SL", status: "PENDING", stop_triggered: true, quantity: 75 })).toBe(true);
  });

  it("flags a broker TRIGGERED status", () => {
    expect(isStopLossTriggeredNotFilled({ orderType: "STOP_LIMIT", status: "TRIGGERED", quantity: 75, filledQuantity: 0 })).toBe(true);
  });

  it("clears once the stop fills, or when it was never triggered", () => {
    expect(isStopLossTriggeredNotFilled({ pricetype: "SL", status: "COMPLETE", stop_triggered: true, quantity: 75 })).toBe(false);
    expect(isStopLossTriggeredNotFilled({ pricetype: "SL", status: "TRIGGERED", quantity: 75, filled_quantity: 75 })).toBe(false);
    expect(isStopLossTriggeredNotFilled({ pricetype: "SL", status: "PENDING", stop_triggered: false, quantity: 75 })).toBe(false);
    expect(isStopLossTriggeredNotFilled({ pricetype: "LIMIT", status: "TRIGGERED", quantity: 75 })).toBe(false);
  });

  it("keys by contract", () => {
    const keys = stopLossNotFilledKeys([
      { symbol: "NIFTY25NOV2624000CE", exchange: "NFO", pricetype: "SL", status: "OPEN", stop_triggered: true, quantity: 75 },
      { symbol: "BANKNIFTY", exchange: "NFO", pricetype: "LIMIT", status: "OPEN", quantity: 30 },
    ]);
    expect([...keys]).toEqual(["NFO:NIFTY25NOV2624000CE"]);
  });

  it("exits a long at the bid for the full open quantity, as a limit", () => {
    expect(exitNowTicket({ symbol: "X", exchange: "NFO", quantity: 150, product: "MIS" }, { bid: 41.2, ask: 41.5, ltp: 41.3 })).toEqual({
      symbol: "X", exchange: "NFO", action: "SELL", orderType: "LIMIT", qty: 150, product: "MIS", price: 41.2,
      exitOnly: true, openQuantity: 150,
    });
  });

  it("exits a short at the ask, falling back to the last price", () => {
    expect(exitNowTicket({ symbol: "X", exchange: "NFO", quantity: -75 }, { ltp: 12.33 })).toMatchObject({
      action: "BUY", qty: 75, price: 12.35, orderType: "LIMIT", exitOnly: true, openQuantity: 75,
    });
    expect(exitNowTicket({ symbol: "X", exchange: "NFO", quantity: -75 }, null)).not.toHaveProperty("price");
    expect(exitNowTicket({ symbol: "X", exchange: "NFO", quantity: 0 }, null)).toBeNull();
  });

  it("opens the order ticket and sends nothing", () => {
    const seen = vi.fn();
    window.addEventListener("flinttrade:addWidget", seen);
    openExitTicket({
      symbol: "X", exchange: "NFO", action: "SELL", orderType: "LIMIT", qty: 75, price: 10, exitOnly: true, openQuantity: 75,
    });
    window.removeEventListener("flinttrade:addWidget", seen);
    expect(seen).toHaveBeenCalledTimes(1);
    expect((seen.mock.calls[0][0] as CustomEvent).detail).toEqual({
      widgetId: "orderpad",
      props: {
        symbol: "X", exchange: "NFO", action: "SELL", orderType: "LIMIT", qty: 75, price: 10, exitOnly: true, openQuantity: 75,
      },
    });
  });
});

import { describe, it, expect } from "vitest";
import {
  DERIVATIVE_EXCHANGES,
  isDerivativeExchange,
  checkOrderEntryMode,
  checkLotSizeVerified,
  checkLotMultiple,
  resolveLotQuantity,
  checkFreezeQuantity,
  checkOrderQuantityLimit,
  checkPriceForOrderType,
  orderQuantityLimit,
  parseWholeNumber,
  parsePriceValue,
  extractBrokerOrderId,
  isTerminalOrderStatus,
  isOpenOrderStatus,
  needsLargeOrderConfirmation,
  LARGE_ORDER_LOTS,
} from "../orderGuards";

describe("derivative exchange classification", () => {
  it("covers every derivative segment the terminal can trade", () => {
    // The union of the per-widget copies this module replaced. BCD came from
    // Quick Trade only — dropping it would let a currency-derivative order be
    // sized in units instead of lots.
    for (const ex of ["NFO", "BFO", "MCX", "CDS", "BCD"]) {
      expect(isDerivativeExchange(ex)).toBe(true);
      expect(DERIVATIVE_EXCHANGES.has(ex)).toBe(true);
    }
  });

  it("treats cash segments as unconstrained", () => {
    expect(isDerivativeExchange("NSE")).toBe(false);
    expect(isDerivativeExchange("BSE")).toBe(false);
    expect(isDerivativeExchange("NSE_INDEX")).toBe(false);
  });
});

describe("checkOrderEntryMode", () => {
  it("refuses order entry in explore mode", () => {
    expect(checkOrderEntryMode("explore")).toBe("Connect a broker to place orders");
  });

  it("allows practice and live", () => {
    expect(checkOrderEntryMode("practice")).toBeNull();
    expect(checkOrderEntryMode("live")).toBeNull();
  });
});

describe("checkLotSizeVerified", () => {
  it("fails closed on a derivative with an unverified lot size", () => {
    expect(
      checkLotSizeVerified("NFO", { lotSize: 75, verified: false }, "NIFTY25JUL22000CE"),
    ).toBe("Lot size for NIFTY25JUL22000CE isn't verified, so the order wasn't sent.");
  });

  it("fails closed when the lot size is missing entirely", () => {
    expect(checkLotSizeVerified("NFO", { lotSize: null, verified: true }, "X")).toBe(
      "Lot size for X isn't verified, so the order wasn't sent.",
    );
    expect(checkLotSizeVerified("NFO", { lotSize: 0, verified: true }, "X")).toBe(
      "Lot size for X isn't verified, so the order wasn't sent.",
    );
  });

  it("passes a verified derivative lot size", () => {
    expect(checkLotSizeVerified("NFO", { lotSize: 75, verified: true }, "X")).toBeNull();
  });

  it("imposes no lot constraint on equities", () => {
    expect(checkLotSizeVerified("NSE", { lotSize: null, verified: false }, "RELIANCE")).toBeNull();
  });
});

describe("checkLotMultiple", () => {
  const verified = { lotSize: 75, verified: true };

  it("accepts exact multiples", () => {
    expect(checkLotMultiple("NFO", 75, verified, "X")).toBeNull();
    expect(checkLotMultiple("NFO", 150, verified, "X")).toBeNull();
  });

  it("rejects a non-multiple", () => {
    expect(checkLotMultiple("NFO", 100, verified, "X")).toBe(
      "Quantity must be a multiple of the lot size (75).",
    );
  });

  it("rejects a zero or negative quantity", () => {
    expect(checkLotMultiple("NFO", 0, verified, "X")).not.toBeNull();
    expect(checkLotMultiple("NFO", -75, verified, "X")).not.toBeNull();
  });

  it("reports the unverified lot size before the multiple check", () => {
    expect(checkLotMultiple("NFO", 100, { lotSize: 75, verified: false }, "X")).toBe(
      "Lot size for X isn't verified, so the order wasn't sent.",
    );
  });

  it("leaves equity quantities alone", () => {
    expect(checkLotMultiple("NSE", 7, { lotSize: null, verified: false }, "X")).toBeNull();
  });
});

describe("resolveLotQuantity", () => {
  it("multiplies lots by a verified derivative lot size", () => {
    expect(resolveLotQuantity("NFO", 2, { lotSize: 75, verified: true })).toBe(150);
  });

  it("returns null for a derivative with an unverified lot size", () => {
    expect(resolveLotQuantity("NFO", 2, { lotSize: 75, verified: false })).toBeNull();
    expect(resolveLotQuantity("NFO", 2, { lotSize: null, verified: true })).toBeNull();
  });

  it("never silently falls back to a lot size of one on a derivative", () => {
    // The fallback would send 2 units where the operator asked for 2 lots.
    expect(resolveLotQuantity("MCX", 2, { lotSize: 0, verified: false })).toBeNull();
  });

  it("treats an equity lot count as the quantity", () => {
    expect(resolveLotQuantity("NSE", 5, { lotSize: null, verified: false })).toBe(5);
    expect(resolveLotQuantity("NSE", 5, { lotSize: 1, verified: true })).toBe(5);
  });
});

describe("checkPriceForOrderType", () => {
  it("refuses a zero-price LIMIT order", () => {
    expect(checkPriceForOrderType("LIMIT", 0)).toContain("price above zero");
  });

  it("refuses a missing or non-finite LIMIT price", () => {
    expect(checkPriceForOrderType("LIMIT", null)).not.toBeNull();
    expect(checkPriceForOrderType("LIMIT", Number.NaN)).not.toBeNull();
    expect(checkPriceForOrderType("LIMIT", undefined)).not.toBeNull();
  });

  it("accepts a real LIMIT price", () => {
    expect(checkPriceForOrderType("LIMIT", 145.5)).toBeNull();
  });

  it("requires both price and trigger for SL", () => {
    expect(checkPriceForOrderType("SL", 100, 0)).toContain("trigger price");
    expect(checkPriceForOrderType("SL", 0, 99)).toContain("price above zero");
    expect(checkPriceForOrderType("SL", 100, 99)).toBeNull();
  });

  it("requires only a trigger for SL-M", () => {
    expect(checkPriceForOrderType("SL-M", 0, 99)).toBeNull();
    expect(checkPriceForOrderType("SL-M", 0, 0)).toContain("trigger price");
  });

  it("imposes no price rule on MARKET orders", () => {
    expect(checkPriceForOrderType("MARKET", 0, 0)).toBeNull();
  });
});

describe("checkOrderQuantityLimit", () => {
  it("matches the L1 ceilings", () => {
    expect(orderQuantityLimit("NSE")).toBe(50_000);
    expect(orderQuantityLimit("nse")).toBe(50_000);
    expect(orderQuantityLimit("MCX")).toBe(1_000);
    expect(orderQuantityLimit("NFO")).toBe(5_000);
    expect(orderQuantityLimit("UNKNOWN")).toBe(50_000);
  });

  it("refuses a quantity above the exchange ceiling", () => {
    expect(checkOrderQuantityLimit("NSE", 9999999)).toBe(
      "Quantity 9999999 exceeds NSE limit of 50000",
    );
    expect(checkOrderQuantityLimit("MCX", 1001)).toBe(
      "Quantity 1001 exceeds MCX limit of 1000",
    );
  });

  it("accepts a quantity on the ceiling and leaves minimum checks alone", () => {
    expect(checkOrderQuantityLimit("NSE", 50_000)).toBeNull();
    expect(checkOrderQuantityLimit("NSE", 1)).toBeNull();
    expect(checkOrderQuantityLimit("NSE", 0)).toBeNull();
  });
});

describe("checkFreezeQuantity", () => {
  it("uses NSE/FAOP/76693 when the broker does not send a freeze quantity", () => {
    expect(checkFreezeQuantity("NIFTY 24500 CE", 3510)).toBeNull();
    expect(checkFreezeQuantity("NIFTY 24500 CE", 3575)).toBe(
      "Max 3510 per order for NIFTY 24500 CE. Place smaller orders.",
    );
    expect(checkFreezeQuantity("NIFTYNXT50-OCT2026-FUT", 1126)).toBe(
      "Max 1125 per order for NIFTYNXT50-OCT2026-FUT. Place smaller orders.",
    );
    expect(checkFreezeQuantity("BANKNIFTY", 1440)).toBeNull();
    expect(checkFreezeQuantity("SBIN", 100)).toBeNull();
  });

  it("uses the broker freeze quantity ahead of the circular", () => {
    expect(checkFreezeQuantity("NIFTY", 130, 100)).toBe(
      "Max 100 per order for NIFTY. Place smaller orders.",
    );
  });
});

describe("strict parsers", () => {
  it("parses grouped whole numbers", () => {
    expect(parseWholeNumber("1,000")).toBe(1000);
    expect(parseWholeNumber(" 25 ")).toBe(25);
  });

  it("rejects garbage instead of truncating it", () => {
    expect(parseWholeNumber("12abc")).toBeNull();
    expect(parseWholeNumber("")).toBeNull();
    expect(parseWholeNumber("-5")).toBeNull();
    expect(parseWholeNumber("0")).toBeNull();
  });

  it("parses prices and keeps an explicit zero", () => {
    expect(parsePriceValue("123.45")).toBe(123.45);
    expect(parsePriceValue("0")).toBe(0);
    expect(parsePriceValue("-1")).toBeNull();
    expect(parsePriceValue("abc")).toBeNull();
  });
});

describe("extractBrokerOrderId", () => {
  it("reads every broker alias", () => {
    expect(extractBrokerOrderId({ orderId: "A1" })).toBe("A1");
    expect(extractBrokerOrderId({ orderid: "B2" })).toBe("B2");
    expect(extractBrokerOrderId({ order_id: "C3" })).toBe("C3");
  });

  it("accepts a bare string and a numeric id", () => {
    expect(extractBrokerOrderId("D4")).toBe("D4");
    expect(extractBrokerOrderId({ orderId: 12345 })).toBe("12345");
  });

  it("fails closed rather than fabricating an id", () => {
    expect(extractBrokerOrderId(null)).toBeNull();
    expect(extractBrokerOrderId({})).toBeNull();
    expect(extractBrokerOrderId({ orderId: "" })).toBeNull();
    expect(extractBrokerOrderId("")).toBeNull();
    expect(extractBrokerOrderId({ orderId: {} })).toBeNull();
  });
});

describe("order status classification", () => {
  it("treats fills, rejections and cancellations as terminal", () => {
    for (const s of ["COMPLETE", "filled", "EXECUTED", "REJECTED", "cancelled", "canceled"]) {
      expect(isTerminalOrderStatus(s)).toBe(true);
      expect(isOpenOrderStatus(s)).toBe(false);
    }
  });

  it("keeps pending and partial states open", () => {
    for (const s of ["open pending", "trigger pending", "cancel pending", "PARTIALLY FILLED"]) {
      expect(isTerminalOrderStatus(s)).toBe(false);
      expect(isOpenOrderStatus(s)).toBe(true);
    }
  });
});

describe("needsLargeOrderConfirmation", () => {
  it("asks for confirmation at the threshold and above", () => {
    expect(needsLargeOrderConfirmation(LARGE_ORDER_LOTS)).toBe(true);
    expect(needsLargeOrderConfirmation(LARGE_ORDER_LOTS + 5)).toBe(true);
  });

  it("stays quiet below the threshold", () => {
    expect(needsLargeOrderConfirmation(1)).toBe(false);
    expect(needsLargeOrderConfirmation(LARGE_ORDER_LOTS - 1)).toBe(false);
  });
});

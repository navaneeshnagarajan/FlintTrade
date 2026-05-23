/**
 * cryptoPairs.test.ts
 *
 * Tests for Delta Exchange crypto pair helpers in cryptoPairs.ts.
 *
 * Coverage:
 *  - Exchange identification (isCryptoExchange)
 *  - Pair membership check (isCryptoPair)
 *  - Metadata retrieval (getCryptoPairInfo)
 *  - Lot size lookup (getCryptoLotSize)
 *  - Tick size lookup (getCryptoTickSize)
 *  - Price formatting (formatCryptoPrice)
 *  - Fee schedule (getCryptoTradingFee)
 *  - Market hours (isCryptoMarketOpen)
 *  - Order rounding (roundToLotSize, roundToTickSize)
 *  - Catalogue integrity (CRYPTO_PAIRS, CRYPTO_SYMBOLS)
 */

import { describe, it, expect } from "vitest";
import {
  CRYPTO_PAIRS,
  CRYPTO_SYMBOLS,
  DELTA_EXCHANGE_NAMES,
  isCryptoExchange,
  isCryptoPair,
  getCryptoPairInfo,
  getCryptoLotSize,
  getCryptoTickSize,
  formatCryptoPrice,
  getCryptoTradingFee,
  isCryptoMarketOpen,
  roundToLotSize,
  roundToTickSize,
} from "../cryptoPairs";

// ---------------------------------------------------------------------------
// isCryptoExchange()
// ---------------------------------------------------------------------------

describe("isCryptoExchange()", () => {
  it("returns true for DELTA (uppercase)", () => {
    expect(isCryptoExchange("DELTA")).toBe(true);
  });

  it("returns true for delta (lowercase)", () => {
    expect(isCryptoExchange("delta")).toBe(true);
  });

  it("returns true for DELTAEXCHANGE", () => {
    expect(isCryptoExchange("DELTAEXCHANGE")).toBe(true);
  });

  it("returns true for CRYPTO alias", () => {
    expect(isCryptoExchange("CRYPTO")).toBe(true);
  });

  it("returns false for NSE", () => {
    expect(isCryptoExchange("NSE")).toBe(false);
  });

  it("returns false for MCX", () => {
    expect(isCryptoExchange("MCX")).toBe(false);
  });

  it("returns false for empty string", () => {
    expect(isCryptoExchange("")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isCryptoPair()
// ---------------------------------------------------------------------------

describe("isCryptoPair()", () => {
  it("returns true for BTCUSD", () => {
    expect(isCryptoPair("BTCUSD")).toBe(true);
  });

  it("returns true for ETHINR", () => {
    expect(isCryptoPair("ETHINR")).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(isCryptoPair("btcusd")).toBe(true);
    expect(isCryptoPair("EthInr")).toBe(true);
  });

  it("returns false for equity symbol", () => {
    expect(isCryptoPair("RELIANCE")).toBe(false);
  });

  it("returns false for unknown pair", () => {
    expect(isCryptoPair("DOGEUSD")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getCryptoPairInfo()
// ---------------------------------------------------------------------------

describe("getCryptoPairInfo()", () => {
  it("returns full info for BTCUSD", () => {
    const info = getCryptoPairInfo("BTCUSD");
    expect(info).toBeDefined();
    expect(info?.base).toBe("BTC");
    expect(info?.quote).toBe("USD");
    expect(info?.lotSize).toBe(0.001);
    expect(info?.tickSize).toBe(0.5);
  });

  it("returns full info for ETHINR", () => {
    const info = getCryptoPairInfo("ETHINR");
    expect(info?.base).toBe("ETH");
    expect(info?.quote).toBe("INR");
  });

  it("returns undefined for unknown symbol", () => {
    expect(getCryptoPairInfo("DOGEUSD")).toBeUndefined();
  });

  it("is case-insensitive", () => {
    expect(getCryptoPairInfo("btcusd")).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// getCryptoLotSize()
// ---------------------------------------------------------------------------

describe("getCryptoLotSize()", () => {
  it("returns 0.001 for BTCUSD", () => {
    expect(getCryptoLotSize("BTCUSD")).toBe(0.001);
  });

  it("returns 0.01 for ETHUSD", () => {
    expect(getCryptoLotSize("ETHUSD")).toBe(0.01);
  });

  it("returns 0.0001 for BTCINR", () => {
    expect(getCryptoLotSize("BTCINR")).toBe(0.0001);
  });

  it("returns 1.0 for XRPUSD", () => {
    expect(getCryptoLotSize("XRPUSD")).toBe(1.0);
  });

  it("is case-insensitive", () => {
    expect(getCryptoLotSize("btcusd")).toBe(0.001);
  });

  it("returns BTC default (0.001) for unknown symbol", () => {
    expect(getCryptoLotSize("DOGEUSD")).toBe(0.001);
  });
});

// ---------------------------------------------------------------------------
// getCryptoTickSize()
// ---------------------------------------------------------------------------

describe("getCryptoTickSize()", () => {
  it("returns 0.5 for BTCUSD", () => {
    expect(getCryptoTickSize("BTCUSD")).toBe(0.5);
  });

  it("returns 0.05 for ETHUSD", () => {
    expect(getCryptoTickSize("ETHUSD")).toBe(0.05);
  });

  it("returns 0.0001 for XRPUSD", () => {
    expect(getCryptoTickSize("XRPUSD")).toBe(0.0001);
  });

  it("returns default 0.01 for unknown symbol", () => {
    expect(getCryptoTickSize("DOGEUSD")).toBe(0.01);
  });
});

// ---------------------------------------------------------------------------
// formatCryptoPrice()
// ---------------------------------------------------------------------------

describe("formatCryptoPrice()", () => {
  it("formats USD pair to 2 decimal places", () => {
    expect(formatCryptoPrice(67432.5, "BTCUSD")).toBe("67432.50");
  });

  it("formats INR pair to 2 decimal places", () => {
    expect(formatCryptoPrice(5000000.0, "BTCINR")).toBe("5000000.00");
  });

  it("formats small ETH price correctly", () => {
    expect(formatCryptoPrice(0.05, "ETHUSD")).toBe("0.05");
  });

  it("formats zero price", () => {
    expect(formatCryptoPrice(0, "BTCUSD")).toBe("0.00");
  });

  it("falls back to 2 dp for unknown symbol", () => {
    expect(formatCryptoPrice(1.23456, "DOGEUSD")).toBe("1.23");
  });

  it("throws RangeError for negative price", () => {
    expect(() => formatCryptoPrice(-1.0, "BTCUSD")).toThrow(RangeError);
  });

  it("is case-insensitive", () => {
    expect(formatCryptoPrice(100, "btcusd")).toBe("100.00");
  });
});

// ---------------------------------------------------------------------------
// getCryptoTradingFee()
// ---------------------------------------------------------------------------

describe("getCryptoTradingFee()", () => {
  it("returns standard fees for BTCUSD", () => {
    expect(getCryptoTradingFee("BTCUSD")).toEqual({
      maker: 0.0002,
      taker: 0.0005,
    });
  });

  it("taker fee is greater than maker fee", () => {
    const fees = getCryptoTradingFee("ETHUSD");
    expect(fees.taker).toBeGreaterThan(fees.maker);
  });

  it("falls back to standard tier for unknown symbol", () => {
    expect(getCryptoTradingFee("DOGEUSD")).toEqual({
      maker: 0.0002,
      taker: 0.0005,
    });
  });

  it("every catalogued pair has maker and taker keys", () => {
    for (const symbol of Object.keys(CRYPTO_PAIRS)) {
      const fees = getCryptoTradingFee(symbol);
      expect(fees).toHaveProperty("maker");
      expect(fees).toHaveProperty("taker");
    }
  });
});

// ---------------------------------------------------------------------------
// isCryptoMarketOpen()
// ---------------------------------------------------------------------------

describe("isCryptoMarketOpen()", () => {
  it("always returns true (24/7 market)", () => {
    expect(isCryptoMarketOpen()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// roundToLotSize()
// ---------------------------------------------------------------------------

describe("roundToLotSize()", () => {
  it("leaves exact lot size unchanged", () => {
    expect(roundToLotSize(0.003, "BTCUSD")).toBeCloseTo(0.003);
  });

  it("floors to nearest lot — 0.0037 → 0.003 for BTCUSD", () => {
    expect(roundToLotSize(0.0037, "BTCUSD")).toBeCloseTo(0.003);
  });

  it("works for whole-number lot sizes (XRP)", () => {
    expect(roundToLotSize(5.9, "XRPUSD")).toBeCloseTo(5.0);
  });

  it("throws RangeError for zero quantity", () => {
    expect(() => roundToLotSize(0, "BTCUSD")).toThrow(RangeError);
  });

  it("throws RangeError for negative quantity", () => {
    expect(() => roundToLotSize(-1, "BTCUSD")).toThrow(RangeError);
  });
});

// ---------------------------------------------------------------------------
// roundToTickSize()
// ---------------------------------------------------------------------------

describe("roundToTickSize()", () => {
  it("leaves exact tick unchanged", () => {
    expect(roundToTickSize(67432.5, "BTCUSD")).toBeCloseTo(67432.5);
  });

  it("rounds 67432.3 to 67432.5 for BTCUSD (tick=0.5)", () => {
    expect(roundToTickSize(67432.3, "BTCUSD")).toBeCloseTo(67432.5);
  });

  it("rounds 3200.07 to 3200.05 for ETHUSD (tick=0.05)", () => {
    expect(roundToTickSize(3200.07, "ETHUSD")).toBeCloseTo(3200.05);
  });

  it("throws RangeError for zero price", () => {
    expect(() => roundToTickSize(0, "BTCUSD")).toThrow(RangeError);
  });

  it("throws RangeError for negative price", () => {
    expect(() => roundToTickSize(-100, "BTCUSD")).toThrow(RangeError);
  });
});

// ---------------------------------------------------------------------------
// CRYPTO_PAIRS catalogue integrity
// ---------------------------------------------------------------------------

describe("CRYPTO_PAIRS catalogue", () => {
  it("contains BTCUSD", () => {
    expect(CRYPTO_PAIRS).toHaveProperty("BTCUSD");
  });

  it("contains BTCINR", () => {
    expect(CRYPTO_PAIRS).toHaveProperty("BTCINR");
  });

  it("contains ETHUSD", () => {
    expect(CRYPTO_PAIRS).toHaveProperty("ETHUSD");
  });

  it("contains ETHINR", () => {
    expect(CRYPTO_PAIRS).toHaveProperty("ETHINR");
  });

  it("every pair has a positive lot size", () => {
    for (const [, info] of Object.entries(CRYPTO_PAIRS)) {
      expect(info.lotSize).toBeGreaterThan(0);
    }
  });

  it("every pair has a positive tick size", () => {
    for (const [, info] of Object.entries(CRYPTO_PAIRS)) {
      expect(info.tickSize).toBeGreaterThan(0);
    }
  });

  it("every pair has a non-empty description", () => {
    for (const [, info] of Object.entries(CRYPTO_PAIRS)) {
      expect(info.description.length).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// CRYPTO_SYMBOLS sorted list
// ---------------------------------------------------------------------------

describe("CRYPTO_SYMBOLS", () => {
  it("is sorted alphabetically", () => {
    expect(CRYPTO_SYMBOLS).toEqual([...CRYPTO_SYMBOLS].sort());
  });

  it("includes all CRYPTO_PAIRS keys", () => {
    for (const symbol of Object.keys(CRYPTO_PAIRS)) {
      expect(CRYPTO_SYMBOLS).toContain(symbol);
    }
  });
});

// ---------------------------------------------------------------------------
// DELTA_EXCHANGE_NAMES set
// ---------------------------------------------------------------------------

describe("DELTA_EXCHANGE_NAMES", () => {
  it("contains DELTA", () => {
    expect(DELTA_EXCHANGE_NAMES.has("DELTA")).toBe(true);
  });

  it("contains DELTAEXCHANGE", () => {
    expect(DELTA_EXCHANGE_NAMES.has("DELTAEXCHANGE")).toBe(true);
  });

  it("contains CRYPTO", () => {
    expect(DELTA_EXCHANGE_NAMES.has("CRYPTO")).toBe(true);
  });
});

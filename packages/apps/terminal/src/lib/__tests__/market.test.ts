/**
 * market.test.ts
 *
 * Behavioural tests for isMarketHours() in market.ts.
 *
 * NSE/BSE rules:
 *   Open  : 9:15 AM IST  (minutes since midnight = 555)
 *   Close : 3:30 PM IST  (minutes since midnight = 930)
 *   Days  : Monday–Friday only (day 1–5)
 *
 * Time control strategy:
 *   isMarketHours() reads wall-clock time via `new Date()`.  We pin the clock
 *   with vi.setSystemTime() so tests are deterministic and timezone-safe.
 *
 *   The function converts to IST internally:
 *     new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" })
 *   jsdom honours the timezone string, so we express all test times as UTC
 *   offsets: IST = UTC+5:30.
 *
 *   Reference trading day: Tuesday 24 March 2026 (not a public holiday).
 *   Reference weekend   : Saturday 28 March 2026 / Sunday 29 March 2026.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { isMarketHours, getMCXStatus, getExchangeStatus, EXCHANGE_HOURS } from "../market";

// ---------------------------------------------------------------------------
// Helpers — UTC times that correspond to well-known IST moments
// ---------------------------------------------------------------------------

/** Build a UTC Date string that, when converted to IST, lands at the given
 *  IST hour and minute on the given day (expressed in UTC terms).
 *
 *  IST = UTC + 5:30, so UTC = IST - 5:30.
 */
function istToUtc(
  year: number,
  month: number, // 1-based
  day: number,
  istHour: number,
  istMinute: number,
): Date {
  // We construct the IST time as if it were UTC, then subtract 5h30m.
  const utcMs =
    Date.UTC(year, month - 1, day, istHour, istMinute, 0, 0) -
    (5 * 60 + 30) * 60 * 1000;
  return new Date(utcMs);
}

// All tests are on Tuesday 2026-03-24 unless stated otherwise.
const TUE = { y: 2026, m: 3, d: 24 } as const;
const SAT = { y: 2026, m: 3, d: 28 } as const;
const SUN = { y: 2026, m: 3, d: 29 } as const;
const MON = { y: 2026, m: 3, d: 23 } as const;
const FRI = { y: 2026, m: 3, d: 27 } as const;

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Core trading hours — returns true
// ---------------------------------------------------------------------------

describe("returns true during NSE market hours (Mon–Fri 9:15–15:30 IST)", () => {
  it("returns true at 11:00 AM IST on a Tuesday", () => {
    // Arrange
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 11, 0));
    // Act + Assert
    expect(isMarketHours()).toBe(true);
  });

  it("returns true at 9:15 AM IST (market open — inclusive boundary)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 9, 15));
    expect(isMarketHours()).toBe(true);
  });

  it("returns true at 15:30 IST (market close — inclusive boundary)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 15, 30));
    expect(isMarketHours()).toBe(true);
  });

  it("returns true at 12:45 PM IST (mid-session)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 12, 45));
    expect(isMarketHours()).toBe(true);
  });

  it("returns true on a Monday during trading hours", () => {
    vi.setSystemTime(istToUtc(MON.y, MON.m, MON.d, 10, 0));
    expect(isMarketHours()).toBe(true);
  });

  it("returns true on a Friday during trading hours", () => {
    vi.setSystemTime(istToUtc(FRI.y, FRI.m, FRI.d, 14, 0));
    expect(isMarketHours()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Outside trading hours on a weekday — returns false
// ---------------------------------------------------------------------------

describe("returns false outside market hours on weekdays", () => {
  it("returns false at 9:14 AM IST (one minute before open)", () => {
    // Arrange
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 9, 14));
    // Act + Assert
    expect(isMarketHours()).toBe(false);
  });

  it("returns false at 15:31 IST (one minute after close)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 15, 31));
    expect(isMarketHours()).toBe(false);
  });

  it("returns false at midnight (00:00 IST)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 0, 0));
    expect(isMarketHours()).toBe(false);
  });

  it("returns false in the pre-market at 9:00 AM IST", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 9, 0));
    expect(isMarketHours()).toBe(false);
  });

  it("returns false in the evening at 6:00 PM IST", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 18, 0));
    expect(isMarketHours()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Edge cases at the exact open/close boundary
// ---------------------------------------------------------------------------

describe("boundary behaviour at exact open and close times", () => {
  it("9:15 AM exactly is inside market hours (>= 555 minutes)", () => {
    // 9 * 60 + 15 = 555
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 9, 15));
    expect(isMarketHours()).toBe(true);
  });

  it("9:14 AM exactly is outside market hours (< 555 minutes)", () => {
    // 9 * 60 + 14 = 554
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 9, 14));
    expect(isMarketHours()).toBe(false);
  });

  it("15:30 exactly is inside market hours (<= 930 minutes)", () => {
    // 15 * 60 + 30 = 930
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 15, 30));
    expect(isMarketHours()).toBe(true);
  });

  it("15:31 exactly is outside market hours (> 930 minutes)", () => {
    // 15 * 60 + 31 = 931
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 15, 31));
    expect(isMarketHours()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Weekend detection
// ---------------------------------------------------------------------------

describe("returns false on weekends regardless of the time", () => {
  it("returns false at 11:00 AM IST on Saturday", () => {
    // Arrange
    vi.setSystemTime(istToUtc(SAT.y, SAT.m, SAT.d, 11, 0));
    // Act + Assert
    expect(isMarketHours()).toBe(false);
  });

  it("returns false at 11:00 AM IST on Sunday", () => {
    vi.setSystemTime(istToUtc(SUN.y, SUN.m, SUN.d, 11, 0));
    expect(isMarketHours()).toBe(false);
  });

  it("returns false at 9:15 AM IST on Saturday (would be open on a weekday)", () => {
    vi.setSystemTime(istToUtc(SAT.y, SAT.m, SAT.d, 9, 15));
    expect(isMarketHours()).toBe(false);
  });

  it("returns false at 15:30 IST on Sunday (would be open on a weekday)", () => {
    vi.setSystemTime(istToUtc(SUN.y, SUN.m, SUN.d, 15, 30));
    expect(isMarketHours()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// MCX market hours — 9:00 AM to 11:30 PM IST (Mon–Fri)
// ---------------------------------------------------------------------------

describe("MCX market hours (9:00–23:30 IST)", () => {
  it("returns true at 9:00 AM IST (MCX open)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 9, 0));
    expect(isMarketHours("MCX")).toBe(true);
  });

  it("returns true at 10:00 PM IST (MCX evening session)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 22, 0));
    expect(isMarketHours("MCX")).toBe(true);
  });

  it("returns true at 23:30 IST (MCX close — inclusive boundary)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 23, 30));
    expect(isMarketHours("MCX")).toBe(true);
  });

  it("returns false at 23:31 IST (one minute after MCX close)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 23, 31));
    expect(isMarketHours("MCX")).toBe(false);
  });

  it("returns false at 8:59 AM IST (one minute before MCX open)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 8, 59));
    expect(isMarketHours("MCX")).toBe(false);
  });

  it("returns false on Saturday even during MCX hours", () => {
    vi.setSystemTime(istToUtc(SAT.y, SAT.m, SAT.d, 22, 0));
    expect(isMarketHours("MCX")).toBe(false);
  });

  it("MCX is open when NSE is closed (evening)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 20, 0));
    expect(isMarketHours("MCX")).toBe(true);
    expect(isMarketHours("NSE")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// CDS market hours — 9:00 AM to 5:00 PM IST
// ---------------------------------------------------------------------------

describe("CDS market hours (9:00–17:00 IST)", () => {
  it("returns true at 16:00 IST (CDS open, NSE closed)", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 16, 0));
    expect(isMarketHours("CDS")).toBe(true);
    expect(isMarketHours("NSE")).toBe(false);
  });

  it("returns false at 17:01 IST", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 17, 1));
    expect(isMarketHours("CDS")).toBe(false);
  });
});

describe("CDS cross-currency market hours (9:00–19:30 IST)", () => {
  it.each([
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "EURUSD29JUL26FUT",
    "GBPUSD29JUL261.35PE",
    "USDJPY29JUL26150CE",
  ])("keeps %s open after the ordinary CDS session closes", (symbol) => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 18, 0));

    expect(isMarketHours({ exchange: "CDS", symbol })).toBe(true);
  });

  it("is open at the inclusive 19:30 close boundary", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 19, 30));

    expect(isMarketHours({ exchange: "CDS", symbol: "EURUSD29JUL26FUT" })).toBe(true);
  });

  it("is closed one minute after the 19:30 close", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 19, 31));

    expect(isMarketHours({ exchange: "CDS", symbol: "EURUSD29JUL26FUT" })).toBe(false);
  });

  it("does not extend the session for INR currency pairs or exchange-only callers", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 18, 0));

    expect(isMarketHours({ exchange: "CDS", symbol: "USDINR29JUL26FUT" })).toBe(false);
    expect(isMarketHours("CDS")).toBe(false);
  });

  it("reports instrument-aware status without changing the CDS label", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 18, 0));

    expect(getExchangeStatus({ exchange: "CDS", symbol: "GBPUSD29JUL26FUT" })).toEqual({
      status: "open",
      label: "CDS Open",
    });
  });
});

// ---------------------------------------------------------------------------
// getMCXStatus()
// ---------------------------------------------------------------------------

describe("getMCXStatus()", () => {
  it("returns 'open' during MCX hours", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 22, 0));
    const status = getMCXStatus();
    expect(status.status).toBe("open");
    expect(status.label).toBe("MCX Open");
  });

  it("returns 'pre-market' before MCX open", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 8, 30));
    const status = getMCXStatus();
    expect(status.status).toBe("pre-market");
  });

  it("returns 'closed' after MCX close", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 23, 45));
    const status = getMCXStatus();
    expect(status.status).toBe("closed");
  });

  it("returns 'weekend' on Saturday", () => {
    vi.setSystemTime(istToUtc(SAT.y, SAT.m, SAT.d, 12, 0));
    const status = getMCXStatus();
    expect(status.status).toBe("weekend");
  });
});

// ---------------------------------------------------------------------------
// getExchangeStatus()
// ---------------------------------------------------------------------------

describe("getExchangeStatus()", () => {
  it("returns 'open' for DELTA at any time", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 3, 0));
    expect(getExchangeStatus("DELTA").status).toBe("open");
  });

  it("returns 'closed' for unknown exchange", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 12, 0));
    expect(getExchangeStatus("FAKE").status).toBe("closed");
  });

  it("returns correct status for NFO during hours", () => {
    vi.setSystemTime(istToUtc(TUE.y, TUE.m, TUE.d, 12, 0));
    expect(getExchangeStatus("NFO").status).toBe("open");
  });
});

// ---------------------------------------------------------------------------
// EXCHANGE_HOURS data integrity
// ---------------------------------------------------------------------------

describe("EXCHANGE_HOURS data", () => {
  it("has MCX hours 9:00–23:30", () => {
    expect(EXCHANGE_HOURS.MCX.open).toBe(9 * 60);      // 540
    expect(EXCHANGE_HOURS.MCX.close).toBe(23 * 60 + 30); // 1410
  });

  it("has NSE hours 9:15–15:30", () => {
    expect(EXCHANGE_HOURS.NSE.open).toBe(9 * 60 + 15);  // 555
    expect(EXCHANGE_HOURS.NSE.close).toBe(15 * 60 + 30); // 930
  });

  it("has CDS hours 9:00–17:00", () => {
    expect(EXCHANGE_HOURS.CDS.open).toBe(9 * 60);
    expect(EXCHANGE_HOURS.CDS.close).toBe(17 * 60);
  });

  it("contains all major exchanges", () => {
    const expected = ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX"];
    for (const exch of expected) {
      expect(EXCHANGE_HOURS).toHaveProperty(exch);
    }
  });
});

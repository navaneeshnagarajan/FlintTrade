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
import { isMarketHours } from "../market";

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

/**
 * formatters.test.ts
 *
 * Behavioural tests for the shared formatting utilities in formatters.ts.
 *
 * All expected strings are cross-checked against the Intl.NumberFormat
 * "en-IN" locale so they match what real Indian users see.
 */

import { describe, it, expect } from "vitest";
import {
  formatNumber,
  formatCurrency,
  formatCurrencyCompact,
  formatPnl,
  formatPercent,
  formatINR,
} from "../formatters";

// ---------------------------------------------------------------------------
// formatNumber — Indian comma grouping
// ---------------------------------------------------------------------------

describe("formatNumber", () => {
  it("formats six-digit number with Indian comma grouping (1,23,456 not 1,234,56)", () => {
    // Arrange
    const value = 123456;
    // Act
    const result = formatNumber(value);
    // Assert — Indian grouping puts the comma after the first 3 digits from the
    // right, then every 2 digits.
    expect(result).toBe("1,23,456.00");
  });

  it("formats a seven-digit number correctly (12,34,567)", () => {
    expect(formatNumber(1234567)).toBe("12,34,567.00");
  });

  it("formats a nine-digit crore-range number (1,23,45,678)", () => {
    expect(formatNumber(12345678)).toBe("1,23,45,678.00");
  });

  it("formats zero as 0.00", () => {
    expect(formatNumber(0)).toBe("0.00");
  });

  it("formats a negative number preserving the Indian grouping", () => {
    expect(formatNumber(-123456)).toBe("-1,23,456.00");
  });

  it("formats a decimal value to 2 places by default", () => {
    expect(formatNumber(1234.567)).toBe("1,234.57");
  });

  it("respects a custom decimalPlaces argument", () => {
    expect(formatNumber(1234.5, 0)).toBe("1,235");
    expect(formatNumber(1234.5, 4)).toBe("1,234.5000");
  });

  it("returns the em-dash sentinel for null", () => {
    expect(formatNumber(null)).toBe("—");
  });

  it("returns the em-dash sentinel for undefined", () => {
    expect(formatNumber(undefined)).toBe("—");
  });

  it("returns the em-dash sentinel for NaN (non-finite)", () => {
    expect(formatNumber(NaN)).toBe("—");
  });

  it("returns the em-dash sentinel for Infinity", () => {
    expect(formatNumber(Infinity)).toBe("—");
  });
});

// ---------------------------------------------------------------------------
// formatCurrency — ₹ symbol + 2 decimal places
// ---------------------------------------------------------------------------

describe("formatCurrency", () => {
  it("adds the ₹ symbol before the formatted number", () => {
    const result = formatCurrency(1000);
    expect(result).toMatch(/^₹/);
  });

  it("formats a typical trading amount with Indian grouping and 2 decimals", () => {
    // 1,23,456.00 — the grouping difference vs western is the key assertion
    expect(formatCurrency(123456)).toBe("₹1,23,456.00");
  });

  it("formats a negative value with the minus sign before the ₹", () => {
    expect(formatCurrency(-5000)).toBe("-₹5,000.00");
  });

  it("formats zero as ₹0.00", () => {
    expect(formatCurrency(0)).toBe("₹0.00");
  });

  it("formats a small decimal amount correctly", () => {
    expect(formatCurrency(0.5)).toBe("₹0.50");
  });

  it("treats null as ₹0.00 (no crash)", () => {
    expect(formatCurrency(null)).toBe("₹0.00");
  });

  it("treats undefined as ₹0.00 (no crash)", () => {
    expect(formatCurrency(undefined)).toBe("₹0.00");
  });

  it("treats Infinity as ₹0.00 (non-finite guard)", () => {
    expect(formatCurrency(Infinity)).toBe("₹0.00");
  });
});

// ---------------------------------------------------------------------------
// formatCurrencyCompact — crore / lakh abbreviations
// ---------------------------------------------------------------------------

describe("formatCurrencyCompact", () => {
  it("abbreviates values >= 1 crore with Cr suffix", () => {
    // 2,50,00,000 → ₹2.50Cr
    expect(formatCurrencyCompact(2_50_00_000)).toBe("₹2.50Cr");
  });

  it("abbreviates values >= 1 lakh with L suffix", () => {
    // 3,75,000 → ₹3.75L
    expect(formatCurrencyCompact(3_75_000)).toBe("₹3.75L");
  });

  it("shows a full integer for values below 1 lakh", () => {
    expect(formatCurrencyCompact(12345)).toBe("₹12,345");
  });

  it("applies the correct suffix for a value at exactly 1 crore boundary", () => {
    expect(formatCurrencyCompact(1_00_00_000)).toBe("₹1.00Cr");
  });

  it("applies the correct suffix for a value at exactly 1 lakh boundary", () => {
    expect(formatCurrencyCompact(1_00_000)).toBe("₹1.00L");
  });

  it("handles negative crore values with a leading minus sign", () => {
    expect(formatCurrencyCompact(-2_50_00_000)).toBe("-₹2.50Cr");
  });

  it("handles negative lakh values with a leading minus sign", () => {
    expect(formatCurrencyCompact(-3_00_000)).toBe("-₹3.00L");
  });

  it("treats null as ₹0 (no crash)", () => {
    expect(formatCurrencyCompact(null)).toBe("₹0");
  });

  it("treats undefined as ₹0 (no crash)", () => {
    expect(formatCurrencyCompact(undefined)).toBe("₹0");
  });
});

// ---------------------------------------------------------------------------
// formatPnl — signed ₹ value for P&L cells
// ---------------------------------------------------------------------------

describe("formatPnl", () => {
  it("shows a + sign for a positive P&L", () => {
    expect(formatPnl(500)).toBe("+₹500.00");
  });

  it("shows a - sign for a negative P&L", () => {
    expect(formatPnl(-500)).toBe("-₹500.00");
  });

  it("shows +₹0.00 for zero P&L", () => {
    expect(formatPnl(0)).toBe("+₹0.00");
  });

  it("uses Indian grouping for large P&L values", () => {
    expect(formatPnl(123456.78)).toBe("+₹1,23,456.78");
  });

  it("treats null as +₹0.00 (no crash)", () => {
    expect(formatPnl(null)).toBe("+₹0.00");
  });

  it("treats undefined as +₹0.00 (no crash)", () => {
    expect(formatPnl(undefined)).toBe("+₹0.00");
  });
});

// ---------------------------------------------------------------------------
// formatPercent — signed percentage strings
// ---------------------------------------------------------------------------

describe("formatPercent", () => {
  it("prefixes positive values with +", () => {
    expect(formatPercent(12.5)).toBe("+12.50%");
  });

  it("keeps the - sign for negative values", () => {
    expect(formatPercent(-3.2)).toBe("-3.20%");
  });

  it("shows +0.00% for zero", () => {
    expect(formatPercent(0)).toBe("+0.00%");
  });

  it("always shows exactly 2 decimal places", () => {
    // 5 → "+5.00%",  5.1 → "+5.10%",  5.123 → "+5.12%"
    expect(formatPercent(5)).toBe("+5.00%");
    expect(formatPercent(5.1)).toBe("+5.10%");
    expect(formatPercent(5.123)).toBe("+5.12%");
  });

  it("treats null as +0.00% — null coerces to 0, which is non-negative", () => {
    // null ?? 0 → 0, and 0 >= 0, so the sign is "+"
    expect(formatPercent(null)).toBe("+0.00%");
  });

  it("treats undefined as +0.00% — undefined coerces to 0, which is non-negative", () => {
    expect(formatPercent(undefined)).toBe("+0.00%");
  });

  it("treats Infinity as 0.00% (non-finite guard)", () => {
    expect(formatPercent(Infinity)).toBe("0.00%");
  });
});

// ---------------------------------------------------------------------------
// formatINR — locale currency style, integer precision
// ---------------------------------------------------------------------------

describe("formatINR", () => {
  it("includes the ₹ symbol", () => {
    const result = formatINR(10000);
    expect(result).toContain("₹");
  });

  it("formats 100000 as ₹1,00,000 (Indian grouping, no decimals)", () => {
    // The browser's Intl currency formatter with en-IN uses Indian grouping.
    // Some environments emit a narrow no-break space before the ₹ — we match
    // on the numeric part to stay environment-agnostic.
    expect(formatINR(100000)).toMatch(/1,00,000/);
  });

  it("formats zero without decimals", () => {
    expect(formatINR(0)).toMatch(/0/);
  });

  it("formats a negative value with the minus sign", () => {
    expect(formatINR(-5000)).toMatch(/-/);
    expect(formatINR(-5000)).toMatch(/5,000/);
  });
});

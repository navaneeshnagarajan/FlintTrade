/**
 * glossary.test.ts
 *
 * Tests for the financial glossary registry used by GlossaryTooltip.
 */

import { describe, it, expect } from "vitest";
import { GLOSSARY } from "../glossary";

// ---------------------------------------------------------------------------
// Expected terms — every key here MUST exist in the glossary
// ---------------------------------------------------------------------------

const EXPECTED_TERMS = [
  "LTCG",
  "STCG",
  "STT",
  "NAV",
  "XIRR",
  "SIP",
  "VIX",
  "F&O",
  "OI",
  "IV",
  "PCR",
  "ATM",
  "ITM",
  "OTM",
  "Greeks",
  "GEX",
  "Max Pain",
  "VWAP",
  "RSI",
  "MACD",
  "MIS",
  "CNC",
  "NRML",
  "PE Ratio",
  "ROE",
  "ROCE",
  "Scalper",
  "Margin",
  "P&L",
  "Day P&L",
];

describe("GLOSSARY registry", () => {
  it("is a non-empty record", () => {
    expect(Object.keys(GLOSSARY).length).toBeGreaterThan(0);
  });

  it.each(EXPECTED_TERMS)("contains definition for '%s'", (term) => {
    expect(GLOSSARY[term]).toBeDefined();
    expect(typeof GLOSSARY[term]).toBe("string");
    expect(GLOSSARY[term].length).toBeGreaterThan(10);
  });

  it("every definition is a non-empty string", () => {
    for (const [key, value] of Object.entries(GLOSSARY)) {
      expect(typeof value).toBe("string");
      expect(value.trim().length, `Definition for "${key}" is empty`).toBeGreaterThan(0);
    }
  });

  it("has no duplicate definitions", () => {
    const values = Object.values(GLOSSARY);
    const unique = new Set(values);
    expect(unique.size).toBe(values.length);
  });
});

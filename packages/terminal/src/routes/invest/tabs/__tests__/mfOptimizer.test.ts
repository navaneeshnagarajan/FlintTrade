/**
 * mfOptimizer.test.ts — Unit tests for MF expense ratio optimizer calculations.
 */

import { describe, it, expect } from "vitest";
import {
  matchFunds,
  calculateCompoundedSavings,
  calculateProjections,
  FUND_DATABASE,
} from "../MfOptimizerTab";

// ---------------------------------------------------------------------------
// matchFunds
// ---------------------------------------------------------------------------

describe("matchFunds", () => {
  it("returns empty array for empty input", () => {
    expect(matchFunds("")).toHaveLength(0);
    expect(matchFunds("   ")).toHaveLength(0);
  });

  it("matches HDFC Flexi Cap by partial name", () => {
    const result = matchFunds("HDFC Flexi");
    expect(result.length).toBeGreaterThanOrEqual(1);
    expect(result[0].name).toBe("HDFC Flexi Cap Fund");
  });

  it("matches by alias", () => {
    const result = matchFunds("ppfas");
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("Parag Parikh Flexi Cap Fund");
  });

  it("matches multiple funds from comma-separated input", () => {
    const result = matchFunds("HDFC Flexi, SBI Bluechip");
    expect(result.length).toBe(2);
    const names = result.map((f) => f.name);
    expect(names).toContain("HDFC Flexi Cap Fund");
    expect(names).toContain("SBI Bluechip Fund");
  });

  it("does not duplicate funds when multiple queries match the same fund", () => {
    const result = matchFunds("HDFC Flexi, hdfc flexicap");
    const hdfcFlexi = result.filter((f) => f.name === "HDFC Flexi Cap Fund");
    expect(hdfcFlexi.length).toBe(1);
  });

  it("is case-insensitive", () => {
    const result = matchFunds("sbi bluechip");
    expect(result.length).toBeGreaterThanOrEqual(1);
    expect(result[0].name).toBe("SBI Bluechip Fund");
  });

  it("calculates expenseDiff correctly", () => {
    const result = matchFunds("HDFC Flexi");
    const fund = result[0];
    expect(fund.expenseDiff).toBeCloseTo(
      fund.expenseRegular - fund.expenseDirect,
      4,
    );
  });

  it("calculates annualSavingsPerLakh correctly", () => {
    const result = matchFunds("HDFC Flexi");
    const fund = result[0];
    // expenseDiff * 1000 = savings per lakh
    expect(fund.annualSavingsPerLakh).toBeCloseTo(fund.expenseDiff * 1000, 2);
  });

  it("returns empty for non-existent fund", () => {
    const result = matchFunds("nonexistent fund xyz");
    expect(result).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// FUND_DATABASE sanity
// ---------------------------------------------------------------------------

describe("FUND_DATABASE", () => {
  it("has exactly 20 funds", () => {
    expect(FUND_DATABASE).toHaveLength(20);
  });

  it("all funds have positive expense ratios", () => {
    for (const fund of FUND_DATABASE) {
      expect(fund.expenseRegular).toBeGreaterThan(0);
      expect(fund.expenseDirect).toBeGreaterThan(0);
    }
  });

  it("regular expense is always >= direct expense", () => {
    for (const fund of FUND_DATABASE) {
      expect(fund.expenseRegular).toBeGreaterThanOrEqual(fund.expenseDirect);
    }
  });

  it("all funds have non-empty names and categories", () => {
    for (const fund of FUND_DATABASE) {
      expect(fund.name.length).toBeGreaterThan(0);
      expect(fund.category.length).toBeGreaterThan(0);
      expect(fund.aliases.length).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// calculateCompoundedSavings
// ---------------------------------------------------------------------------

describe("calculateCompoundedSavings", () => {
  it("returns 0 for 0 years", () => {
    expect(calculateCompoundedSavings(100_000, 1.0, 12, 0)).toBe(0);
  });

  it("returns 0 for negative years", () => {
    expect(calculateCompoundedSavings(100_000, 1.0, 12, -5)).toBe(0);
  });

  it("returns 0 for 0 expense difference", () => {
    expect(calculateCompoundedSavings(100_000, 0, 12, 10)).toBe(0);
  });

  it("returns 0 for 0 investment", () => {
    expect(calculateCompoundedSavings(0, 1.0, 12, 10)).toBe(0);
  });

  it("returns positive savings for valid inputs", () => {
    const savings = calculateCompoundedSavings(100_000, 1.0, 12, 10);
    expect(savings).toBeGreaterThan(0);
  });

  it("savings increase with more years", () => {
    const savings5 = calculateCompoundedSavings(100_000, 1.0, 12, 5);
    const savings10 = calculateCompoundedSavings(100_000, 1.0, 12, 10);
    const savings20 = calculateCompoundedSavings(100_000, 1.0, 12, 20);
    expect(savings10).toBeGreaterThan(savings5);
    expect(savings20).toBeGreaterThan(savings10);
  });

  it("savings increase with higher expense difference", () => {
    const savingsLow = calculateCompoundedSavings(100_000, 0.5, 12, 10);
    const savingsHigh = calculateCompoundedSavings(100_000, 1.5, 12, 10);
    expect(savingsHigh).toBeGreaterThan(savingsLow);
  });

  it("savings increase with higher investment", () => {
    const savingsLow = calculateCompoundedSavings(50_000, 1.0, 12, 10);
    const savingsHigh = calculateCompoundedSavings(200_000, 1.0, 12, 10);
    expect(savingsHigh).toBeGreaterThan(savingsLow);
  });

  it("computes a reasonable 10-year savings for 1L at 1% diff", () => {
    // 1L/year, 1% expense diff, 12% return, 10 years
    // Should be roughly ~1-2L in savings (order of magnitude check)
    const savings = calculateCompoundedSavings(100_000, 1.0, 12, 10);
    expect(savings).toBeGreaterThan(50_000);
    expect(savings).toBeLessThan(500_000);
  });
});

// ---------------------------------------------------------------------------
// calculateProjections
// ---------------------------------------------------------------------------

describe("calculateProjections", () => {
  it("returns 3 projections (5, 10, 20 years)", () => {
    const funds = matchFunds("HDFC Flexi");
    const projections = calculateProjections(funds, 100_000, 12);
    expect(projections).toHaveLength(3);
    expect(projections.map((p) => p.years)).toEqual([5, 10, 20]);
  });

  it("all projection values are positive when funds matched", () => {
    const funds = matchFunds("HDFC Flexi");
    const projections = calculateProjections(funds, 100_000, 12);
    for (const p of projections) {
      expect(p.totalSavings).toBeGreaterThan(0);
    }
  });

  it("returns zero savings when no funds matched", () => {
    const projections = calculateProjections([], 100_000, 12);
    for (const p of projections) {
      expect(p.totalSavings).toBe(0);
    }
  });

  it("projections increase with more years", () => {
    const funds = matchFunds("SBI Bluechip");
    const projections = calculateProjections(funds, 100_000, 12);
    expect(projections[1].totalSavings).toBeGreaterThan(projections[0].totalSavings);
    expect(projections[2].totalSavings).toBeGreaterThan(projections[1].totalSavings);
  });

  it("scales with number of funds", () => {
    const oneFund = matchFunds("HDFC Flexi");
    const twoFunds = matchFunds("HDFC Flexi, SBI Bluechip");

    const proj1 = calculateProjections(oneFund, 100_000, 12);
    const proj2 = calculateProjections(twoFunds, 100_000, 12);

    // Two funds should save more than one
    expect(proj2[1].totalSavings).toBeGreaterThan(proj1[1].totalSavings);
  });
});

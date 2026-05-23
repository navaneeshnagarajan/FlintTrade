/**
 * CompanySnapshot.test.ts — Unit tests for snapshot pure logic functions.
 */

import { describe, it, expect } from "vitest";
import {
  getMarketCapTier,
  assessPE,
  assessPB,
  assessROE,
  assessROCE,
  assessDividendYield,
  calculate52WeekPosition,
  buildRatioHealthList,
  generateSummary,
  type SnapshotData,
} from "../CompanySnapshot";

// ---------------------------------------------------------------------------
// getMarketCapTier
// ---------------------------------------------------------------------------

describe("getMarketCapTier", () => {
  it("classifies >= 50000 Cr as Large Cap", () => {
    expect(getMarketCapTier(50_000)).toBe("Large Cap");
    expect(getMarketCapTier(150_000)).toBe("Large Cap");
  });

  it("classifies 10000-49999 Cr as Mid Cap", () => {
    expect(getMarketCapTier(10_000)).toBe("Mid Cap");
    expect(getMarketCapTier(49_999)).toBe("Mid Cap");
  });

  it("classifies < 10000 Cr as Small Cap", () => {
    expect(getMarketCapTier(9_999)).toBe("Small Cap");
    expect(getMarketCapTier(1_000)).toBe("Small Cap");
  });
});

// ---------------------------------------------------------------------------
// Health assessments
// ---------------------------------------------------------------------------

describe("assessPE", () => {
  it("returns green for PE <= 20", () => {
    expect(assessPE(15)).toBe("green");
    expect(assessPE(20)).toBe("green");
  });

  it("returns amber for PE 21-35", () => {
    expect(assessPE(25)).toBe("amber");
    expect(assessPE(35)).toBe("amber");
  });

  it("returns red for PE > 35", () => {
    expect(assessPE(50)).toBe("red");
  });

  it("returns red for negative PE", () => {
    expect(assessPE(-5)).toBe("red");
    expect(assessPE(0)).toBe("red");
  });
});

describe("assessPB", () => {
  it("returns green for PB <= 3", () => {
    expect(assessPB(2)).toBe("green");
    expect(assessPB(3)).toBe("green");
  });

  it("returns amber for PB 3-6", () => {
    expect(assessPB(4)).toBe("amber");
    expect(assessPB(6)).toBe("amber");
  });

  it("returns red for PB > 6 or negative", () => {
    expect(assessPB(7)).toBe("red");
    expect(assessPB(-1)).toBe("red");
  });
});

describe("assessROE", () => {
  it("returns green for ROE >= 20", () => {
    expect(assessROE(20)).toBe("green");
    expect(assessROE(30)).toBe("green");
  });

  it("returns amber for ROE 12-19", () => {
    expect(assessROE(12)).toBe("amber");
    expect(assessROE(19)).toBe("amber");
  });

  it("returns red for ROE < 12", () => {
    expect(assessROE(5)).toBe("red");
  });
});

describe("assessROCE", () => {
  it("returns green for ROCE >= 20", () => {
    expect(assessROCE(25)).toBe("green");
  });

  it("returns amber for ROCE 12-19", () => {
    expect(assessROCE(15)).toBe("amber");
  });

  it("returns red for ROCE < 12", () => {
    expect(assessROCE(8)).toBe("red");
  });
});

describe("assessDividendYield", () => {
  it("returns green for DY >= 3", () => {
    expect(assessDividendYield(3)).toBe("green");
    expect(assessDividendYield(5)).toBe("green");
  });

  it("returns amber for DY 1-2.9", () => {
    expect(assessDividendYield(1)).toBe("amber");
    expect(assessDividendYield(2.5)).toBe("amber");
  });

  it("returns red for DY < 1", () => {
    expect(assessDividendYield(0.5)).toBe("red");
    expect(assessDividendYield(0)).toBe("red");
  });
});

// ---------------------------------------------------------------------------
// calculate52WeekPosition
// ---------------------------------------------------------------------------

describe("calculate52WeekPosition", () => {
  it("returns 0 when at 52-week low", () => {
    expect(calculate52WeekPosition(100, 100, 200)).toBe(0);
  });

  it("returns 100 when at 52-week high", () => {
    expect(calculate52WeekPosition(200, 100, 200)).toBe(100);
  });

  it("returns 50 when at midpoint", () => {
    expect(calculate52WeekPosition(150, 100, 200)).toBe(50);
  });

  it("clamps to 0-100 range", () => {
    expect(calculate52WeekPosition(50, 100, 200)).toBe(0);
    expect(calculate52WeekPosition(250, 100, 200)).toBe(100);
  });

  it("returns 50 when high equals low", () => {
    expect(calculate52WeekPosition(100, 100, 100)).toBe(50);
  });
});

// ---------------------------------------------------------------------------
// buildRatioHealthList
// ---------------------------------------------------------------------------

describe("buildRatioHealthList", () => {
  const sampleData: SnapshotData = {
    symbol: "RELIANCE",
    name: "Reliance Industries",
    sector: "Energy",
    market_cap: 150_000,
    pe_ratio: 25,
    pb_ratio: 2.5,
    roe: 22,
    roce: 18,
    dividend_yield: 0.5,
  };

  it("returns 5 ratio health entries", () => {
    const list = buildRatioHealthList(sampleData);
    expect(list).toHaveLength(5);
  });

  it("labels match expected names", () => {
    const list = buildRatioHealthList(sampleData);
    const labels = list.map((r) => r.label);
    expect(labels).toEqual(["PE Ratio", "PB Ratio", "ROE", "ROCE", "Div Yield"]);
  });

  it("correctly assesses the sample stock", () => {
    const list = buildRatioHealthList(sampleData);
    const levels = list.map((r) => r.level);
    expect(levels).toEqual(["amber", "green", "green", "amber", "red"]);
  });
});

// ---------------------------------------------------------------------------
// generateSummary
// ---------------------------------------------------------------------------

describe("generateSummary", () => {
  it("generates a summary string with quality and valuation", () => {
    const data: SnapshotData = {
      symbol: "TCS",
      name: "Tata Consultancy Services",
      sector: "IT",
      market_cap: 120_000,
      pe_ratio: 18,
      pb_ratio: 2,
      roe: 25,
      roce: 28,
      dividend_yield: 3.5,
    };

    const summary = generateSummary(data);
    expect(summary).toContain("strong fundamentals");
    expect(summary).toContain("attractively valued");
    expect(summary).toContain("good dividend payer");
    expect(summary).toContain("solid overall");
  });

  it("generates a cautious summary for weak stocks", () => {
    const data: SnapshotData = {
      symbol: "WEAK",
      name: "Weak Corp",
      sector: "Misc",
      market_cap: 5_000,
      pe_ratio: 50,
      pb_ratio: 8,
      roe: 5,
      roce: 4,
      dividend_yield: 0.2,
    };

    const summary = generateSummary(data);
    expect(summary).toContain("weak fundamentals");
    expect(summary).toContain("appears expensive");
    expect(summary).toContain("careful evaluation");
  });

  it("returns a non-empty string for any input", () => {
    const data: SnapshotData = {
      symbol: "TEST",
      name: "Test",
      sector: "Test",
      market_cap: 0,
      pe_ratio: 0,
      pb_ratio: 0,
      roe: 0,
      roce: 0,
      dividend_yield: 0,
    };

    const summary = generateSummary(data);
    expect(summary.length).toBeGreaterThan(0);
  });
});

import { describe, it, expect } from "vitest";
import type { RawOptionChain } from "@/widgets/analysis/OptionChain/types";
import {
  parseExpiry,
  daysToExpiry,
  labelFor,
  buildGreeksHeatmap,
} from "../greeksHeatmapTransform";

const NOW = Date.UTC(2026, 3, 9); // 9 Apr 2026

describe("parseExpiry", () => {
  it("parses ISO YYYY-MM-DD", () => {
    expect(parseExpiry("2026-04-17")).toBe(Date.UTC(2026, 3, 17));
  });
  it("parses DD-MON-YY", () => {
    expect(parseExpiry("17-APR-26")).toBe(Date.UTC(2026, 3, 17));
  });
  it("parses DD-MON-YYYY", () => {
    expect(parseExpiry("17-Apr-2026")).toBe(Date.UTC(2026, 3, 17));
  });
  it("returns null for unknown formats", () => {
    expect(parseExpiry("garbage")).toBeNull();
    expect(parseExpiry("17-XYZ-26")).toBeNull();
  });
});

describe("daysToExpiry", () => {
  it("computes whole days from now", () => {
    expect(daysToExpiry("2026-04-17", NOW)).toBe(8);
  });
  it("clamps past expiries to 0", () => {
    expect(daysToExpiry("2026-04-01", NOW)).toBe(0);
  });
  it("returns 0 for unparseable expiries", () => {
    expect(daysToExpiry("garbage", NOW)).toBe(0);
  });
});

describe("labelFor", () => {
  it("formats a parseable expiry as 'D Mon'", () => {
    expect(labelFor("17-APR-26")).toBe("17 Apr");
  });
  it("falls back to the raw string when unparseable", () => {
    expect(labelFor("WEEKLY1")).toBe("WEEKLY1");
  });
});

describe("buildGreeksHeatmap", () => {
  const chainA: RawOptionChain = {
    underlying_ltp: 22000,
    atm_strike: 22000,
    chain: [
      { strike: 21800, ce: { delta: 0.7, gamma: 0.002, theta: -0.3, vega: 0.1 }, pe: null },
      { strike: 22000, ce: { delta: 0.5, gamma: 0.003, theta: -0.4, vega: 0.12 }, pe: null },
      { strike: 22200, ce: { delta: 0.3, gamma: 0.002, theta: -0.3, vega: 0.1 }, pe: null },
    ],
  };
  const chainB: RawOptionChain = {
    underlying_ltp: 22000,
    atm_strike: 22000,
    chain: [
      { strike: 22000, ce: { delta: 0.52, gamma: 0.0025, theta: -0.5, vega: 0.18 }, pe: null },
      { strike: 22200, ce: { delta: 0.33, gamma: 0.0018, theta: -0.45, vega: 0.16 }, pe: null },
      { strike: 22400, ce: { delta: 0.2, gamma: 0.0012, theta: -0.4, vega: 0.14 }, pe: null },
    ],
  };

  it("aligns rows to the common strike set across expiries", () => {
    const rows = buildGreeksHeatmap(
      [
        { expiry: "17-APR-26", raw: chainA },
        { expiry: "24-APR-26", raw: chainB },
      ],
      NOW,
    );
    expect(rows).not.toBeNull();
    expect(rows).toHaveLength(2);
    // Intersection of strikes carrying greeks: {22000, 22200}.
    expect(rows![0].cells.map((c) => c.strike)).toEqual([22000, 22200]);
    expect(rows![1].cells.map((c) => c.strike)).toEqual([22000, 22200]);
  });

  it("classifies ATM strike and uses CE greeks", () => {
    const rows = buildGreeksHeatmap([{ expiry: "17-APR-26", raw: chainA }], NOW)!;
    const cells = rows[0].cells;
    const atm = cells.find((c) => c.strike === 22000)!;
    expect(atm.moneyness).toBe("ATM");
    expect(atm.delta).toBeCloseTo(0.5, 6);
    expect(atm.vega).toBeCloseTo(0.12, 6);
    // Call convention: strike below ATM is ITM, above is OTM.
    expect(cells.find((c) => c.strike === 21800)!.moneyness).toBe("ITM");
    expect(cells.find((c) => c.strike === 22200)!.moneyness).toBe("OTM");
  });

  it("computes dte and label per expiry", () => {
    const rows = buildGreeksHeatmap([{ expiry: "17-APR-26", raw: chainA }], NOW)!;
    expect(rows[0].dte).toBe(8);
    expect(rows[0].label).toBe("17 Apr");
  });

  it("returns null when chains share no greek-bearing strike", () => {
    const noOverlap: RawOptionChain = {
      atm_strike: 30000,
      chain: [{ strike: 30000, ce: { delta: 0.5, gamma: 0.001, theta: -0.2, vega: 0.1 }, pe: null }],
    };
    const rows = buildGreeksHeatmap(
      [
        { expiry: "17-APR-26", raw: chainA },
        { expiry: "24-APR-26", raw: noOverlap },
      ],
      NOW,
    );
    expect(rows).toBeNull();
  });

  it("returns null when no strike carries greeks", () => {
    const noGreeks: RawOptionChain = {
      chain: [{ strike: 22000, ce: { ltp: 100 }, pe: { ltp: 90 } }],
    };
    expect(buildGreeksHeatmap([{ expiry: "x", raw: noGreeks }], NOW)).toBeNull();
  });
});

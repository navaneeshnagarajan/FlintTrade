import { describe, it, expect } from "vitest";
import type { IVSmileData } from "@/types/api";
import { approxGreeks, buildGreeksHeatmap } from "../greeksHeatmapTransform";

describe("approxGreeks", () => {
  it("returns zeros for non-positive IV or ATM", () => {
    expect(approxGreeks(22000, 22000, 0, 7)).toEqual({ delta: 0, gamma: 0, theta: 0, vega: 0 });
    expect(approxGreeks(22000, 0, 0.15, 7)).toEqual({ delta: 0, gamma: 0, theta: 0, vega: 0 });
  });

  it("gives an ATM call delta near 0.5", () => {
    const g = approxGreeks(22000, 22000, 0.15, 7);
    expect(g.delta).toBeGreaterThan(0.4);
    expect(g.delta).toBeLessThan(0.6);
  });

  it("ITM call (strike below ATM) has higher delta than OTM (strike above ATM)", () => {
    const itm = approxGreeks(21600, 22000, 0.15, 7);
    const otm = approxGreeks(22400, 22000, 0.15, 7);
    expect(itm.delta).toBeGreaterThan(otm.delta);
  });

  it("produces finite, signed greeks (theta <= 0, vega >= 0)", () => {
    const g = approxGreeks(22000, 22000, 0.15, 30);
    expect(Number.isFinite(g.gamma)).toBe(true);
    expect(g.theta).toBeLessThanOrEqual(0);
    expect(g.vega).toBeGreaterThanOrEqual(0);
  });
});

function smile(): IVSmileData {
  return {
    underlying: "NIFTY",
    spot_price: 22000,
    curves: [
      {
        expiry: "17-APR-26",
        days_to_expiry: 8,
        atm_iv: 0.15,
        atm_strike: 22000,
        skew_25delta: 0.02,
        points: [
          { strike: 21800, call_iv: 0.16, put_iv: 0.165, moneyness: 0.991 },
          { strike: 22000, call_iv: 0.15, put_iv: 0.15, moneyness: 1.0 },
          { strike: 22200, call_iv: 0.145, put_iv: 0.148, moneyness: 1.009 },
        ],
      },
      {
        expiry: "24-APR-26",
        days_to_expiry: 15,
        atm_iv: 0.155,
        atm_strike: 22000,
        skew_25delta: 0.018,
        points: [
          { strike: 22000, call_iv: 0.155, put_iv: 0.155, moneyness: 1.0 },
          { strike: 22200, call_iv: 0.15, put_iv: 0.152, moneyness: 1.009 },
          { strike: 22400, call_iv: 0.146, put_iv: 0.149, moneyness: 1.018 },
        ],
      },
    ],
  };
}

describe("buildGreeksHeatmap", () => {
  it("aligns rows to the common strike set across expiries", () => {
    const rows = buildGreeksHeatmap(smile())!;
    expect(rows).toHaveLength(2);
    // Intersection of strikes carrying IV: {22000, 22200}.
    expect(rows[0].cells.map((c) => c.strike)).toEqual([22000, 22200]);
    expect(rows[1].cells.map((c) => c.strike)).toEqual([22000, 22200]);
  });

  it("classifies ATM and derives greeks from the IV smile", () => {
    const rows = buildGreeksHeatmap(smile())!;
    const atm = rows[0].cells.find((c) => c.strike === 22000)!;
    expect(atm.moneyness).toBe("ATM");
    expect(atm.delta).toBeGreaterThan(0.4);
    expect(atm.delta).toBeLessThan(0.6);
    expect(atm.theta).toBeLessThanOrEqual(0);
    // 22200 is above ATM → OTM for a call.
    expect(rows[0].cells.find((c) => c.strike === 22200)!.moneyness).toBe("OTM");
  });

  it("carries expiry, dte and label from the curve", () => {
    const rows = buildGreeksHeatmap(smile())!;
    expect(rows[0].dte).toBe(8);
    expect(rows[0].label).toBe("17-APR-26");
  });

  it("returns null when there are no curves", () => {
    expect(buildGreeksHeatmap(null)).toBeNull();
    expect(buildGreeksHeatmap(undefined)).toBeNull();
    expect(buildGreeksHeatmap({ underlying: "X", spot_price: 0, curves: [] })).toBeNull();
  });

  it("returns null when every expiry is degenerate (dte <= 0)", () => {
    const zeroDte = smile();
    zeroDte.curves = zeroDte.curves.map((c) => ({ ...c, days_to_expiry: 0 }));
    expect(buildGreeksHeatmap(zeroDte)).toBeNull();
  });

  it("returns null when curves share no IV-bearing strike", () => {
    const noOverlap: IVSmileData = {
      underlying: "NIFTY",
      spot_price: 22000,
      curves: [
        {
          expiry: "a", days_to_expiry: 8, atm_iv: 0.15, atm_strike: 22000, skew_25delta: 0,
          points: [{ strike: 22000, call_iv: 0.15, put_iv: 0.15, moneyness: 1 }],
        },
        {
          expiry: "b", days_to_expiry: 15, atm_iv: 0.15, atm_strike: 30000, skew_25delta: 0,
          points: [{ strike: 30000, call_iv: 0.15, put_iv: 0.15, moneyness: 1 }],
        },
      ],
    };
    expect(buildGreeksHeatmap(noOverlap)).toBeNull();
  });
});

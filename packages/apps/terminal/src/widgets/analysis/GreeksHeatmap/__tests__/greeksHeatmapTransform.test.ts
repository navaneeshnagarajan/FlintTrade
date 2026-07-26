import { describe, it, expect } from "vitest";
import type { IVSmileData } from "@/types/api";
import { bsGreeks, yearsFromDays } from "@/lib/optionsMath";
import { approxGreeks, buildGreeksHeatmap, ivPercent } from "../greeksHeatmapTransform";

describe("approxGreeks", () => {
  it("returns zeros for non-positive IV, ATM, strike or dte", () => {
    expect(approxGreeks(22000, 22000, 0, 7)).toEqual({ delta: 0, gamma: 0, theta: 0, vega: 0 });
    expect(approxGreeks(22000, 0, 0.15, 7)).toEqual({ delta: 0, gamma: 0, theta: 0, vega: 0 });
    expect(approxGreeks(0, 22000, 0.15, 7)).toEqual({ delta: 0, gamma: 0, theta: 0, vega: 0 });
    // dte<=0 → no time value → fully inert (delta 0 too, not a lone delta).
    expect(approxGreeks(22000, 22000, 0.15, 0)).toEqual({ delta: 0, gamma: 0, theta: 0, vega: 0 });
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

  // Numeric cross-check. Neither retired widget asserted a single greek VALUE —
  // only signs and ranges — so an argument-order or scale mistake (spot/strike
  // swapped, dte passed as years, IV passed as percentage points) would have
  // gone unnoticed. This pins the derivation against the shared module it is a
  // thin adapter over.
  it("matches the shared Black–Scholes module, at display precision", () => {
    const expected = bsGreeks({
      spot: 22000,
      strike: 22200,
      timeToExpiryYears: yearsFromDays(8),
      volatility: 0.1465,
      optionType: "call",
    });
    const g = approxGreeks(22200, 22000, 0.1465, 8);

    expect(g.delta).toBeCloseTo(expected.delta, 4);
    expect(g.gamma).toBeCloseTo(expected.gamma, 6);
    expect(g.theta).toBeCloseTo(expected.theta, 2);
    expect(g.vega).toBeCloseTo(expected.vega, 4);
  });

  it("puts ATM greeks in their known numeric neighbourhood", () => {
    // NIFTY-scale ATM call, 15% IV, 8 days: delta just above 0.5, gamma of
    // order 0.8 per 1,000 units, vega ~13 per IV point, theta ~ −12/day.
    const g = approxGreeks(22000, 22000, 0.15, 8);
    expect(g.delta).toBeGreaterThan(0.5);
    expect(g.delta).toBeLessThan(0.52);
    expect(g.gamma).toBeGreaterThan(0.7);
    expect(g.gamma).toBeLessThan(0.9);
    expect(g.vega).toBeGreaterThan(12);
    expect(g.vega).toBeLessThan(14);
    expect(g.theta).toBeLessThan(-11);
    expect(g.theta).toBeGreaterThan(-13);
  });

  it("scales gamma and vega with time as Black–Scholes requires", () => {
    const near = approxGreeks(22000, 22000, 0.15, 8);
    const far = approxGreeks(22000, 22000, 0.15, 50);
    // ATM gamma falls with time to expiry; ATM vega rises with it.
    expect(near.gamma).toBeGreaterThan(far.gamma);
    expect(far.vega).toBeGreaterThan(near.vega);
    // And time decay is fiercest on the near expiry.
    expect(near.theta).toBeLessThan(far.theta);
  });
});

describe("ivPercent", () => {
  it("converts a decimal IV fraction to percentage points", () => {
    expect(ivPercent(0.15)).toBe(15);
    expect(ivPercent(0.1465)).toBe(14.65);
    expect(ivPercent(0)).toBe(0);
  });
});

function smile(): IVSmileData {
  return {
    underlying: "NIFTY",
    spot_price: 22000,
    is_sample_data: false,
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

  // Ported from the retired useGreeksSurface suite: the display IV must be the
  // MID of the two option legs, converted to percentage points.
  it("carries the mid IV of both option legs in percentage points", () => {
    const rows = buildGreeksHeatmap(smile())!;
    // 22000: call 0.15 / put 0.15 → 15.00%.
    expect(rows[0].cells.find((c) => c.strike === 22000)!.iv).toBeCloseTo(15, 6);
    // 22200 on the near curve: call 0.145 / put 0.148 → 14.65%.
    expect(rows[0].cells.find((c) => c.strike === 22200)!.iv).toBeCloseTo(14.65, 6);
    // Same strike, far curve: call 0.15 / put 0.152 → 15.10%.
    expect(rows[1].cells.find((c) => c.strike === 22200)!.iv).toBeCloseTo(15.1, 6);
  });

  it("derives each cell's greeks from that cell's own mid IV", () => {
    const rows = buildGreeksHeatmap(smile())!;
    const cell = rows[0].cells.find((c) => c.strike === 22200)!;
    const expected = bsGreeks({
      spot: 22000, // the curve's ATM strike stands in for spot
      strike: 22200,
      timeToExpiryYears: yearsFromDays(8),
      volatility: (0.145 + 0.148) / 2,
      optionType: "call",
    });
    expect(cell.delta).toBeCloseTo(expected.delta, 4);
    expect(cell.vega).toBeCloseTo(expected.vega, 4);
    // OTM call: delta below the ATM cell's.
    expect(cell.delta).toBeLessThan(rows[0].cells.find((c) => c.strike === 22000)!.delta);
  });

  it("carries expiry, dte and label from the curve", () => {
    const rows = buildGreeksHeatmap(smile())!;
    expect(rows[0].dte).toBe(8);
    expect(rows[0].label).toBe("17-APR-26");
  });

  it("returns null when there are no curves", () => {
    expect(buildGreeksHeatmap(null)).toBeNull();
    expect(buildGreeksHeatmap(undefined)).toBeNull();
    expect(buildGreeksHeatmap({
      underlying: "X",
      spot_price: 0,
      curves: [],
      is_sample_data: false,
    })).toBeNull();
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
      is_sample_data: false,
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

  it("rejects a strike when either option leg lacks IV", () => {
    const incomplete = smile();
    incomplete.curves = [
      {
        ...incomplete.curves[0],
        points: [{ strike: 22000, call_iv: 0.15, put_iv: 0, moneyness: 1 }],
      },
    ];
    expect(buildGreeksHeatmap(incomplete)).toBeNull();
  });
});

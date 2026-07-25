/**
 * ivSkewTransform tests — moved here with the module when IVSkew merged into
 * IVSmile (merge 2.1). The scale-detection cases are the reason the transform
 * had to survive the merge: without them a percentage-points payload renders at
 * 100×, and the IVSmile widget had no equivalent normalisation of its own.
 */

import { describe, it, expect } from "vitest";
import type { IVSmileData } from "@/types/api";
import { normaliseIv, mapIVSmileToSkew } from "../ivSkewTransform";

describe("normaliseIv", () => {
  it("returns 0 for non-positive / non-finite values", () => {
    expect(normaliseIv(0)).toBe(0);
    expect(normaliseIv(-5)).toBe(0);
    expect(normaliseIv(Number.NaN)).toBe(0);
  });

  it("passes a decimal IV through unchanged", () => {
    expect(normaliseIv(0.148)).toBeCloseTo(0.148, 6);
  });

  it("converts a percentage IV (>1.5) to a decimal", () => {
    expect(normaliseIv(14.8)).toBeCloseTo(0.148, 6);
  });
});

function smile(): IVSmileData {
  return {
    underlying: "NIFTY",
    spot_price: 22400,
    is_sample_data: false,
    curves: [
      {
        expiry: "10-Apr-2026",
        days_to_expiry: 1,
        atm_iv: 0.148,
        atm_strike: 22400,
        skew_25delta: 0.032,
        points: [
          { strike: 22200, call_iv: 0.155, put_iv: 0.16, moneyness: 0.991 },
          { strike: 22400, call_iv: 0.148, put_iv: 0.148, moneyness: 1.0 },
          { strike: 22600, call_iv: 0.141, put_iv: 0.143, moneyness: 1.009 },
        ],
      },
      {
        expiry: "24-Apr-2026",
        days_to_expiry: 15,
        atm_iv: 0.162,
        atm_strike: 22400,
        skew_25delta: 0.024,
        points: [
          { strike: 22400, call_iv: 0.162, put_iv: 0.162, moneyness: 1.0 },
          { strike: 22600, call_iv: 0.156, put_iv: 0.158, moneyness: 1.009 },
        ],
      },
    ],
  };
}

describe("mapIVSmileToSkew", () => {
  it("maps curves, points, spot and symbol from the IV-smile payload", () => {
    const data = mapIVSmileToSkew(smile())!;
    expect(data.symbol).toBe("NIFTY");
    expect(data.spot).toBe(22400);
    expect(data.curves).toHaveLength(2);
    const c0 = data.curves[0];
    expect(c0.atm_strike).toBe(22400);
    expect(c0.atm_iv).toBeCloseTo(0.148, 6);
    expect(c0.skew_25delta).toBeCloseTo(0.032, 6);
    expect(c0.points).toHaveLength(3);
    const atm = c0.points.find((p) => p.strike === 22400)!;
    expect(atm.moneyness).toBeCloseTo(1.0, 6);
    expect(atm.call_iv).toBeCloseTo(0.148, 6);
  });

  it("normalises a percentage-points payload (IVs AND skew) to decimals", () => {
    // Screener live shape: IVs in percent (14.8), skew in percentage points (2.0).
    const pct = smile();
    pct.curves[0].atm_iv = 14.8;
    pct.curves[0].skew_25delta = 2.0;
    pct.curves[0].points = pct.curves[0].points.map((p) => ({
      ...p,
      call_iv: p.call_iv * 100,
      put_iv: p.put_iv * 100,
    }));
    const data = mapIVSmileToSkew(pct)!;
    expect(data.curves[0].atm_iv).toBeCloseTo(0.148, 6);
    expect(data.curves[0].points[0].call_iv).toBeLessThan(1);
    // skew must be scaled with the IVs → 2.0 percentage points → 0.02 (renders +2 %).
    expect(data.curves[0].skew_25delta).toBeCloseTo(0.02, 6);
  });

  it("leaves an already-decimal payload (incl. skew) unscaled", () => {
    const data = mapIVSmileToSkew(smile())!;
    // smile() is decimal: skew 0.032 stays 0.032 (renders +3.2 %).
    expect(data.curves[0].skew_25delta).toBeCloseTo(0.032, 6);
  });

  it("preserves a negative skew sign through scaling", () => {
    const pct = smile();
    pct.curves[0].atm_iv = 14.8;
    pct.curves[0].skew_25delta = -1.5;
    pct.curves[0].points = pct.curves[0].points.map((p) => ({
      ...p,
      call_iv: p.call_iv * 100,
      put_iv: p.put_iv * 100,
    }));
    const data = mapIVSmileToSkew(pct)!;
    expect(data.curves[0].skew_25delta).toBeCloseTo(-0.015, 6);
  });

  it("returns null when there are no curves", () => {
    expect(mapIVSmileToSkew(null)).toBeNull();
    expect(mapIVSmileToSkew(undefined)).toBeNull();
    expect(mapIVSmileToSkew({
      underlying: "X",
      spot_price: 0,
      curves: [],
      is_sample_data: false,
    })).toBeNull();
  });

  it("drops curves whose points carry no positive IV", () => {
    const empty: IVSmileData = {
      underlying: "NIFTY",
      spot_price: 22400,
      is_sample_data: false,
      curves: [
        {
          expiry: "x",
          days_to_expiry: 1,
          atm_iv: 0,
          atm_strike: 22400,
          skew_25delta: 0,
          points: [{ strike: 22400, call_iv: 0, put_iv: 0, moneyness: 1 }],
        },
      ],
    };
    expect(mapIVSmileToSkew(empty)).toBeNull();
  });

  it("drops curves whose points carry IV for only one option leg", () => {
    const incomplete = smile();
    incomplete.curves = [
      {
        ...incomplete.curves[0],
        points: [{ strike: 22400, call_iv: 0.15, put_iv: 0, moneyness: 1 }],
      },
    ];
    expect(mapIVSmileToSkew(incomplete)).toBeNull();
  });
});

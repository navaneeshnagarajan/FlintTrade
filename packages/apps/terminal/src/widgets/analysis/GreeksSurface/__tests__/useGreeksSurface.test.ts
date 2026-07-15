import { describe, expect, it } from "vitest";
import type { IVSmileData } from "@/types/api";
import { buildSurfaceFromIVSmile } from "../useGreeksSurface";

function smile(callIv: number, putIv: number): IVSmileData {
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
          { strike: 22000, call_iv: callIv, put_iv: putIv, moneyness: 1 },
        ],
      },
    ],
  };
}

describe("buildSurfaceFromIVSmile", () => {
  it("derives percentage display IV from complete decimal option-leg IV", () => {
    const surface = buildSurfaceFromIVSmile(smile(0.14, 0.16));
    expect(surface).toHaveLength(1);
    expect(surface[0].points[5].iv).toBeCloseTo(15, 6);
  });

  it("rejects a curve when either option leg lacks IV", () => {
    expect(buildSurfaceFromIVSmile(smile(0.15, 0))).toEqual([]);
  });
});

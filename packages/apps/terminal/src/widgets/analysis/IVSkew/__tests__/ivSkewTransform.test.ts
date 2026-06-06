import { describe, it, expect } from "vitest";
import type { RawOptionChain } from "@/widgets/analysis/OptionChain/types";
import {
  normaliseIv,
  skew25Delta,
  curveFromChain,
  buildIVSkewData,
} from "../ivSkewTransform";

describe("normaliseIv", () => {
  it("returns 0 for missing/empty rows", () => {
    expect(normaliseIv(null)).toBe(0);
    expect(normaliseIv(undefined)).toBe(0);
    expect(normaliseIv({})).toBe(0);
  });

  it("passes through a decimal IV unchanged", () => {
    expect(normaliseIv({ iv: 0.148 })).toBeCloseTo(0.148, 6);
  });

  it("converts a percentage IV (>1.5) to a decimal", () => {
    expect(normaliseIv({ iv: 14.8 })).toBeCloseTo(0.148, 6);
  });

  it("prefers iv over implied_volatility, falling back when absent", () => {
    expect(normaliseIv({ implied_volatility: 16.0 })).toBeCloseTo(0.16, 6);
    expect(normaliseIv({ iv: 12.0, implied_volatility: 99 })).toBeCloseTo(0.12, 6);
  });

  it("ignores non-positive / non-finite IV", () => {
    expect(normaliseIv({ iv: 0 })).toBe(0);
    expect(normaliseIv({ iv: -5 })).toBe(0);
    expect(normaliseIv({ iv: Number.NaN })).toBe(0);
  });
});

describe("skew25Delta", () => {
  it("returns put25IV - call25IV using the strikes closest to 0.25 delta", () => {
    const chain = [
      { strike: 100, ce: { delta: 0.7, iv: 20 }, pe: { delta: -0.3, iv: 24 } },
      { strike: 110, ce: { delta: 0.25, iv: 18 }, pe: { delta: -0.75, iv: 30 } }, // 25Δ call → 18%
      { strike: 90, ce: { delta: 0.9, iv: 26 }, pe: { delta: -0.25, iv: 27 } },   // 25Δ put  → 27%
    ];
    // 0.27 - 0.18 = 0.09
    expect(skew25Delta(chain)).toBeCloseTo(0.09, 6);
  });

  it("returns 0 (flat) when deltas are absent", () => {
    const chain = [
      { strike: 100, ce: { iv: 20 }, pe: { iv: 24 } },
      { strike: 110, ce: { iv: 18 }, pe: { iv: 30 } },
    ];
    expect(skew25Delta(chain)).toBe(0);
  });
});

describe("curveFromChain", () => {
  const raw: RawOptionChain = {
    underlying_ltp: 22400,
    atm_strike: 22400,
    chain: [
      { strike: 22200, ce: { iv: 15.5, delta: 0.65 }, pe: { iv: 16.0, delta: -0.35 } },
      { strike: 22400, ce: { iv: 14.8, delta: 0.5 }, pe: { iv: 14.8, delta: -0.5 } },
      { strike: 22600, ce: { iv: 14.1, delta: 0.25 }, pe: { iv: 14.3, delta: -0.75 } },
    ],
  };

  it("builds points with moneyness and normalised decimal IVs", () => {
    const curve = curveFromChain("10-Apr-2026", raw);
    expect(curve).not.toBeNull();
    expect(curve!.points).toHaveLength(3);
    const atm = curve!.points.find((p) => p.strike === 22400)!;
    expect(atm.moneyness).toBeCloseTo(1.0, 4);
    expect(atm.call_iv).toBeCloseTo(0.148, 4);
  });

  it("uses the chain's atm_strike and its IV", () => {
    const curve = curveFromChain("10-Apr-2026", raw);
    expect(curve!.atm_strike).toBe(22400);
    expect(curve!.atm_iv).toBeCloseTo(0.148, 4);
  });

  it("returns null for an empty chain", () => {
    expect(curveFromChain("x", { chain: [] })).toBeNull();
    expect(curveFromChain("x", {})).toBeNull();
  });

  it("falls back to the nearest strike when atm_strike is absent", () => {
    const noAtm: RawOptionChain = { underlying_ltp: 22410, chain: raw.chain };
    const curve = curveFromChain("x", noAtm);
    expect(curve!.atm_strike).toBe(22400); // nearest to 22410
  });
});

describe("buildIVSkewData", () => {
  const raw: RawOptionChain = {
    underlying_ltp: 22400,
    atm_strike: 22400,
    chain: [{ strike: 22400, ce: { iv: 14.8, delta: 0.5 }, pe: { iv: 14.8, delta: -0.5 } }],
  };

  it("assembles curves and spot from per-expiry chains", () => {
    const data = buildIVSkewData(
      "NIFTY",
      [
        { expiry: "10-Apr-2026", raw },
        { expiry: "24-Apr-2026", raw },
      ],
      "2026-04-09T10:15:00",
    );
    expect(data).not.toBeNull();
    expect(data!.symbol).toBe("NIFTY");
    expect(data!.spot).toBe(22400);
    expect(data!.curves).toHaveLength(2);
  });

  it("returns null when no expiry yields a usable curve", () => {
    const empty: RawOptionChain = { chain: [] };
    expect(buildIVSkewData("NIFTY", [{ expiry: "x", raw: empty }], "t")).toBeNull();
  });
});

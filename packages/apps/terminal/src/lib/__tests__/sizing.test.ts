/**
 * sizing.test.ts — unit tests for the shared position-sizing kernel.
 *
 * The numeric cases here mirror the characterisation pins in the Calculator,
 * PositionSizing and ProfitTarget widget suites, so a change to the kernel
 * fails here first with a much smaller reproduction.
 */

import { describe, it, expect } from "vitest";
import {
  HALF_KELLY,
  breakevenWinRate,
  deriveTarget,
  formatRR,
  kellyFraction,
  riskBudget,
  rrRatio,
  sizeFixedFractional,
} from "../sizing";

describe("riskBudget", () => {
  it("takes the stated percentage of capital", () => {
    expect(riskBudget(500_000, 1)).toBe(5_000);
    expect(riskBudget(200_000, 2)).toBe(4_000);
    expect(riskBudget(100_000, 3)).toBe(3_000);
  });

  it("returns 0 for unusable inputs rather than NaN", () => {
    expect(riskBudget(0, 2)).toBe(0);
    expect(riskBudget(-500_000, 2)).toBe(0);
    expect(riskBudget(500_000, 0)).toBe(0);
    expect(riskBudget(Number.NaN, 2)).toBe(0);
    expect(riskBudget(Number.POSITIVE_INFINITY, 2)).toBe(0);
  });
});

describe("sizeFixedFractional", () => {
  it("sizes in whole lots within the budget", () => {
    // ₹5,000 budget / (50 points × 50 per lot = ₹2,500) → 2 lots.
    const result = sizeFixedFractional({
      capital: 500_000,
      riskPct: 1,
      stopDistance: 50,
      lotSize: 50,
    });
    expect(result).toEqual({
      lots: 2,
      units: 100,
      rupeeRisk: 5_000,
      capitalAtRiskPct: 1,
      exceedsRisk: false,
    });
  });

  it("floors part-lots down and reports the real rupee risk", () => {
    // ₹5,000 budget / (60 points × 50 = ₹3,000) → 1.66 → 1 lot risking ₹3,000.
    const result = sizeFixedFractional({
      capital: 500_000,
      riskPct: 1,
      stopDistance: 60,
      lotSize: 50,
    });
    expect(result?.lots).toBe(1);
    expect(result?.rupeeRisk).toBe(3_000);
    expect(result?.exceedsRisk).toBe(false);
  });

  it("sizes in shares when lotSize is 1", () => {
    // ₹4,000 budget / 10 points → 400 shares.
    const result = sizeFixedFractional({
      capital: 200_000,
      riskPct: 2,
      stopDistance: 10,
      lotSize: 1,
    });
    expect(result?.lots).toBe(400);
    expect(result?.units).toBe(400);
    expect(result?.rupeeRisk).toBe(4_000);
    expect(result?.exceedsRisk).toBe(false);
  });

  // ── The decision that this module exists to settle ────────────────────────

  it("flags — and does not hide — a single lot that breaches the budget", () => {
    // ₹5,000 budget but one lot risks 200 × 50 = ₹10,000.
    const result = sizeFixedFractional({
      capital: 500_000,
      riskPct: 1,
      stopDistance: 200,
      lotSize: 50,
    });
    expect(result).not.toBeNull();
    expect(result?.exceedsRisk).toBe(true);
    // The clamp still recommends one lot, so the caller can show a number…
    expect(result?.lots).toBe(1);
    expect(result?.units).toBe(50);
    // …but the honest risk is double what the operator asked for.
    expect(result?.rupeeRisk).toBe(10_000);
    expect(result?.capitalAtRiskPct).toBe(2);
    expect(result!.rupeeRisk).toBeGreaterThan(riskBudget(500_000, 1));
  });

  it("does not flag a position that exactly consumes the budget", () => {
    const result = sizeFixedFractional({
      capital: 500_000,
      riskPct: 2,
      stopDistance: 200,
      lotSize: 50,
    });
    expect(result?.lots).toBe(1);
    expect(result?.rupeeRisk).toBe(10_000);
    expect(result?.exceedsRisk).toBe(false);
  });

  it("returns null for unusable inputs", () => {
    const base = { capital: 500_000, riskPct: 1, stopDistance: 200, lotSize: 50 };
    expect(sizeFixedFractional({ ...base, capital: 0 })).toBeNull();
    expect(sizeFixedFractional({ ...base, capital: -1 })).toBeNull();
    expect(sizeFixedFractional({ ...base, riskPct: 0 })).toBeNull();
    expect(sizeFixedFractional({ ...base, stopDistance: 0 })).toBeNull();
    expect(sizeFixedFractional({ ...base, lotSize: 0 })).toBeNull();
    expect(sizeFixedFractional({ ...base, capital: Number.NaN })).toBeNull();
    expect(sizeFixedFractional({ ...base, stopDistance: Number.NaN })).toBeNull();
  });
});

describe("kellyFraction", () => {
  it("defaults to half-Kelly", () => {
    // Full Kelly at 55% / 2R = (0.55 × 2 − 0.45) / 2 = 0.325 → half = 0.1625.
    expect(kellyFraction({ winRate: 55, rewardRisk: 2 })).toBeCloseTo(0.1625, 10);
    expect(HALF_KELLY).toBe(0.5);
  });

  it("honours an explicit fraction", () => {
    expect(kellyFraction({ winRate: 55, rewardRisk: 2, fraction: 1 })).toBeCloseTo(0.325, 10);
    expect(kellyFraction({ winRate: 55, rewardRisk: 2, fraction: 0.25 })).toBeCloseTo(0.08125, 10);
  });

  it("stakes nothing on a negative edge", () => {
    // 30% win rate at 1R is a losing system.
    expect(kellyFraction({ winRate: 30, rewardRisk: 1 })).toBe(0);
    expect(kellyFraction({ winRate: 50, rewardRisk: 1 })).toBe(0);
  });

  it("clamps a nonsensical win rate at 100%", () => {
    expect(kellyFraction({ winRate: 150, rewardRisk: 2 })).toBe(
      kellyFraction({ winRate: 100, rewardRisk: 2 }),
    );
    expect(kellyFraction({ winRate: 100, rewardRisk: 2 })).toBe(0.5);
  });

  it("returns 0 for unusable inputs", () => {
    expect(kellyFraction({ winRate: 0, rewardRisk: 2 })).toBe(0);
    expect(kellyFraction({ winRate: 55, rewardRisk: 0 })).toBe(0);
    expect(kellyFraction({ winRate: Number.NaN, rewardRisk: 2 })).toBe(0);
    expect(kellyFraction({ winRate: 55, rewardRisk: 2, fraction: 0 })).toBe(0);
  });

  it("composes with sizeFixedFractional to reproduce the widget default", () => {
    const fraction = kellyFraction({ winRate: 55, rewardRisk: 2 });
    const result = sizeFixedFractional({
      capital: 500_000,
      riskPct: fraction * 100,
      stopDistance: 200,
      lotSize: 50,
    });
    // ₹81,250 budget / ₹10,000 per lot → 8 lots.
    expect(result?.lots).toBe(8);
    expect(result?.units).toBe(400);
    expect(result?.rupeeRisk).toBe(80_000);
  });
});

describe("rrRatio", () => {
  it("measures reward against risk", () => {
    expect(rrRatio(22_000, 21_800, 22_500)).toBe(2.5);
    expect(rrRatio(500, 490, 530)).toBe(3);
    expect(rrRatio(500, 490, 520)).toBe(2);
  });

  it("is direction-agnostic", () => {
    // SELL: stop above entry, target below.
    expect(rrRatio(22_000, 22_200, 21_500)).toBe(2.5);
  });

  it("returns null when there is no risk to measure", () => {
    expect(rrRatio(500, 500, 520)).toBeNull();
    expect(rrRatio(Number.NaN, 490, 520)).toBeNull();
    expect(rrRatio(500, Number.NaN, 520)).toBeNull();
    expect(rrRatio(500, 490, Number.NaN)).toBeNull();
  });
});

describe("breakevenWinRate", () => {
  it("is 50% at 1R and falls as reward grows", () => {
    expect(breakevenWinRate(1)).toBe(50);
    expect(breakevenWinRate(2.5)).toBeCloseTo(28.5714, 4);
    expect(breakevenWinRate(3)).toBe(25);
  });

  it("demands every trade wins when there is no reward", () => {
    expect(breakevenWinRate(0)).toBe(100);
    expect(breakevenWinRate(-1)).toBe(100);
    expect(breakevenWinRate(Number.NaN)).toBe(100);
  });
});

describe("deriveTarget", () => {
  it("projects above the entry for a BUY", () => {
    expect(deriveTarget(500, 10, 2, "BUY")).toBe(520);
    expect(deriveTarget(500, 10, 3, "BUY")).toBe(530);
  });

  it("projects below the entry for a SELL", () => {
    expect(deriveTarget(490, 10, 2, "SELL")).toBe(470);
  });
});

describe("formatRR", () => {
  it("always renders reward-first with two decimals", () => {
    expect(formatRR(2.5)).toBe("2.50 : 1");
    expect(formatRR(2)).toBe("2.00 : 1");
    expect(formatRR(1)).toBe("1.00 : 1");
    expect(formatRR(0.5)).toBe("0.50 : 1");
  });

  it("degrades to an em dash for unusable input", () => {
    expect(formatRR(Number.NaN)).toBe("—");
    expect(formatRR(Number.POSITIVE_INFINITY)).toBe("—");
  });
});

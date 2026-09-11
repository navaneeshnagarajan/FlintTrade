/**
 * Strategy Builder payoff maths.
 *
 * The Payoff tab used to take min/max of a ±15% sampled curve. That caps
 * unbounded legs (a zero-premium NIFTY ATM long call reported ₹2,53,125)
 * and misses breakevens that sit on a flat-zero segment (zero-premium
 * long call never changes sign).
 */

import { describe, expect, it } from "vitest";

import type { Leg } from "../types";
import {
  SAMPLE_PREMIUM_HELPER,
  UNSET_PREMIUM_HELPER,
  ZERO_PREMIUM_WARNING,
  calculateNetPremium,
  computePayoff,
  computePayoffSummary,
  hasExplicitZeroPremium,
  hasUnsetPremium,
  pnlAtExpiry,
  validateLegs,
} from "../utils";

function leg(partial: Partial<Leg> & Pick<Leg, "action" | "optionType" | "strike">): Leg {
  return {
    id: "leg-1",
    lots: 1,
    premium: 0,
    ...partial,
  };
}

function pricedSummary(legs: Leg[]) {
  const summary = computePayoffSummary(legs);
  expect(summary).not.toBeNull();
  if (!summary) throw new Error("expected a priced payoff summary");
  return summary;
}

describe("pnlAtExpiry", () => {
  it("returns intrinsic minus premium for a long call", () => {
    const call = leg({ action: "BUY", optionType: "CE", strike: 22500, premium: 100 });
    expect(pnlAtExpiry([call], 22000)).toBe(-100);
    expect(pnlAtExpiry([call], 22500)).toBe(-100);
    expect(pnlAtExpiry([call], 22700)).toBe(100);
  });
});

describe("computePayoffSummary", () => {
  it("treats a zero-premium long call as unbounded profit with breakeven at the strike", () => {
    // Tester FT-LAB-001: Explore → /lab → Options Builder → Long Call → Payoff.
    // Default NIFTY ATM 22500, lot size 75, template premium 0.
    const call = leg({ action: "BUY", optionType: "CE", strike: 22500, premium: 0 });
    const summary = pricedSummary([call]);

    expect(summary.maxProfit).toBe(Infinity);
    expect(summary.maxLoss).toBe(0);
    expect(summary.breakevens).toEqual([22500]);

    // The sampled curve still peaks at +15% of spot — that figure must not
    // leak into the summary (22500 × 0.15 × 75 = 2,53,125).
    const sampled = computePayoff([call], 22500);
    const sampledMax = Math.max(...sampled.map((p) => p.pnl));
    expect(sampledMax * 75).toBe(253125);
    expect(summary.maxProfit).not.toBe(sampledMax);
  });

  it("keeps paid-premium long calls unbounded with max loss equal to the premium", () => {
    const call = leg({ action: "BUY", optionType: "CE", strike: 22500, premium: 180 });
    const summary = pricedSummary([call]);

    expect(summary.maxProfit).toBe(Infinity);
    expect(summary.maxLoss).toBe(-180);
    expect(summary.breakevens).toEqual([22680]);
  });

  it("bounds a long put at strike minus premium", () => {
    const put = leg({ action: "BUY", optionType: "PE", strike: 22500, premium: 150 });
    const summary = pricedSummary([put]);

    expect(summary.maxProfit).toBe(22350);
    expect(summary.maxLoss).toBe(-150);
    expect(summary.breakevens).toEqual([22350]);
  });

  it("treats a short call as unbounded loss", () => {
    const call = leg({ action: "SELL", optionType: "CE", strike: 22500, premium: 90 });
    const summary = pricedSummary([call]);

    expect(summary.maxProfit).toBe(90);
    expect(summary.maxLoss).toBe(-Infinity);
    expect(summary.breakevens).toEqual([22590]);
  });

  it("does not invent a breakeven at spot zero for a flat-zero long call", () => {
    const call = leg({ action: "BUY", optionType: "CE", strike: 24000, premium: 0 });
    expect(pricedSummary([call]).breakevens).toEqual([24000]);
  });

  it("computes a bounded bull-call spread from the shared kink scan", () => {
    const legs = [
      leg({ id: "long", action: "BUY", optionType: "CE", strike: 22500, premium: 100 }),
      leg({ id: "short", action: "SELL", optionType: "CE", strike: 22600, premium: 40 }),
    ];
    const summary = pricedSummary(legs);

    expect(summary.maxProfit).toBe(40);
    expect(summary.maxLoss).toBe(-60);
    expect(summary.breakevens).toEqual([22560]);
  });

  it("leaves a long straddle unbounded on the upside", () => {
    const legs = [
      leg({ id: "ce", action: "BUY", optionType: "CE", strike: 22500, premium: 120 }),
      leg({ id: "pe", action: "BUY", optionType: "PE", strike: 22500, premium: 80 }),
    ];
    const summary = pricedSummary(legs);

    expect(summary.maxProfit).toBe(Infinity);
    expect(summary.maxLoss).toBe(-200);
    expect(summary.breakevens).toEqual([22300, 22700]);
  });

  it("scales lots into max loss without changing the breakeven strike of a long call", () => {
    const call = leg({ action: "BUY", optionType: "CE", strike: 22500, premium: 50, lots: 2 });
    const summary = pricedSummary([call]);

    expect(summary.maxProfit).toBe(Infinity);
    expect(summary.maxLoss).toBe(-100);
    expect(summary.breakevens).toEqual([22550]);
  });

  it("does not run a blank premium as honest zero-risk (FT-LAB-003)", () => {
    const unset = leg({ action: "BUY", optionType: "CE", strike: 22500, premium: null });
    expect(hasUnsetPremium([unset])).toBe(true);
    expect(hasExplicitZeroPremium([unset])).toBe(false);
    expect(calculateNetPremium([unset])).toBeNull();
    expect(computePayoffSummary([unset])).toBeNull();
    expect(validateLegs([unset]).valid).toBe(true);
  });

  it("keeps an explicit ₹0 distinct from unset so FT-LAB-001 math still applies", () => {
    const free = leg({ action: "BUY", optionType: "CE", strike: 22500, premium: 0 });
    expect(hasUnsetPremium([free])).toBe(false);
    expect(hasExplicitZeroPremium([free])).toBe(true);
    expect(calculateNetPremium([free])).toBe(0);
    const summary = computePayoffSummary([free]);
    expect(summary).not.toBeNull();
    expect(summary?.maxLoss).toBe(0);
    expect(summary?.breakevens).toEqual([22500]);
  });
});

describe("premium honesty copy", () => {
  it("keeps the FT-LAB-003 helper strings stable", () => {
    expect(UNSET_PREMIUM_HELPER).toBe("Enter premium to model payoff");
    expect(SAMPLE_PREMIUM_HELPER).toBe("Sample premium — edit to model");
    expect(ZERO_PREMIUM_WARNING).toBe("Premium is ₹0 — payoff treats cost as free");
  });
});

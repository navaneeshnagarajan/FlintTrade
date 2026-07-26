import { describe, it, expect } from "vitest";
import {
  DAYS_PER_YEAR,
  GAMMA_SCALE,
  bsGreeks,
  d1,
  d2,
  normCdf,
  normPdf,
  normaliseIv,
  yearsFromDays,
} from "../optionsMath";

// ---------------------------------------------------------------------------
// Normal distribution
// ---------------------------------------------------------------------------

describe("normCdf", () => {
  it("is a half at the mean", () => {
    // A&S 26.2.17 is a rational approximation with ≤ 7.5e-8 absolute error;
    // it lands within ~5e-10 of 0.5 here, which is far tighter than any greek
    // the terminal renders (4 decimal places at most).
    expect(normCdf(0)).toBeCloseTo(0.5, 8);
  });

  it("matches the published 95% two-sided critical value", () => {
    // N(1.96) = 0.9750021049…, the textbook 97.5th percentile.
    expect(normCdf(1.96)).toBeCloseTo(0.975, 4);
    expect(normCdf(-1.96)).toBeCloseTo(0.025, 4);
  });

  it("matches known one-sigma / two-sigma values", () => {
    expect(normCdf(1)).toBeCloseTo(0.8413447, 6);
    expect(normCdf(-1)).toBeCloseTo(0.1586553, 6);
    expect(normCdf(2)).toBeCloseTo(0.9772499, 6);
    expect(normCdf(-2.5758)).toBeCloseTo(0.005, 4);
  });

  it("is symmetric: N(x) + N(-x) = 1", () => {
    for (const x of [0.1, 0.5, 1.234, 2.5, 4]) {
      expect(normCdf(x) + normCdf(-x)).toBeCloseTo(1, 9);
    }
  });

  it("is monotonic increasing and bounded to [0, 1]", () => {
    let previous = -1;
    for (let x = -6; x <= 6; x += 0.25) {
      const value = normCdf(x);
      expect(value).toBeGreaterThanOrEqual(previous);
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1);
      previous = value;
    }
  });

  it("is NOT the logistic approximation the widgets used before", () => {
    // The old `1 / (1 + exp(-1.7·d1))` sigmoid peaks at ~0.009 of error around
    // ±0.5σ — nearly a full delta point, which is what motivated this module.
    const logistic = (x: number) => 1 / (1 + Math.exp(-1.7 * x));
    expect(Math.abs(normCdf(0.5) - logistic(0.5))).toBeGreaterThan(0.008);
    expect(Math.abs(normCdf(1) - logistic(1))).toBeGreaterThan(0.004);
  });

  it("saturates at the infinities and fails inert on NaN", () => {
    expect(normCdf(Number.POSITIVE_INFINITY)).toBe(1);
    expect(normCdf(Number.NEGATIVE_INFINITY)).toBe(0);
    expect(normCdf(Number.NaN)).toBe(0);
  });
});

describe("normPdf", () => {
  it("peaks at 1/√(2π)", () => {
    expect(normPdf(0)).toBeCloseTo(0.3989422804, 9);
  });

  it("matches known densities and is symmetric", () => {
    expect(normPdf(1)).toBeCloseTo(0.2419707, 6);
    expect(normPdf(2)).toBeCloseTo(0.05399097, 7);
    expect(normPdf(-1.5)).toBeCloseTo(normPdf(1.5), 12);
  });

  it("returns 0 for non-finite input", () => {
    expect(normPdf(Number.NaN)).toBe(0);
    expect(normPdf(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// d1 / d2
// ---------------------------------------------------------------------------

describe("d1 / d2", () => {
  it("computes the textbook at-the-money d1 with a zero rate", () => {
    // d1 = (ln(1) + (0 + 0.5·0.2²)·0.25) / (0.2·√0.25) = 0.005 / 0.1 = 0.05
    expect(d1(100, 100, 0.25, 0.2)).toBeCloseTo(0.05, 10);
  });

  it("adds the rate carry to the numerator", () => {
    // d1 = ((0.05 + 0.02)·0.25) / 0.1 = 0.175
    expect(d1(100, 100, 0.25, 0.2, 0.05)).toBeCloseTo(0.175, 10);
  });

  it("keeps d2 exactly σ√T below d1", () => {
    const spread = 0.2 * Math.sqrt(0.25);
    expect(d1(100, 100, 0.25, 0.2) - d2(100, 100, 0.25, 0.2)).toBeCloseTo(spread, 12);
  });

  it("is higher for an in-the-money call strike", () => {
    expect(d1(100, 90, 0.25, 0.2)).toBeGreaterThan(d1(100, 110, 0.25, 0.2));
  });

  it("returns NaN for degenerate input", () => {
    expect(d1(0, 100, 0.25, 0.2)).toBeNaN();
    expect(d1(100, 0, 0.25, 0.2)).toBeNaN();
    expect(d1(100, 100, 0, 0.2)).toBeNaN();
    expect(d1(100, 100, 0.25, 0)).toBeNaN();
    expect(d2(100, 100, 0, 0.2)).toBeNaN();
  });
});

// ---------------------------------------------------------------------------
// bsGreeks
// ---------------------------------------------------------------------------

const ATM_CASE = {
  spot: 100,
  strike: 100,
  timeToExpiryYears: 0.25,
  volatility: 0.2,
} as const;

describe("bsGreeks", () => {
  it("prices the known at-the-money call", () => {
    const call = bsGreeks({ ...ATM_CASE, optionType: "call" });
    // d1 = 0.05 → N(d1) = 0.51994…; the ≈0.54 figure quoted for this case
    // assumes a small positive rate, and this module defaults to r = 0.
    expect(call.delta).toBeCloseTo(0.51994, 4);
    expect(call.delta).toBeCloseTo(0.54, 1);
  });

  it("satisfies put–call parity on delta (call − put = 1)", () => {
    const call = bsGreeks({ ...ATM_CASE, optionType: "call" });
    const put = bsGreeks({ ...ATM_CASE, optionType: "put" });
    expect(call.delta - put.delta).toBeCloseTo(1, 10);
    // Gamma and vega are side-independent.
    expect(call.gamma).toBeCloseTo(put.gamma, 12);
    expect(call.vega).toBeCloseTo(put.vega, 12);
  });

  it("returns the documented gamma scale (×1000)", () => {
    const { gamma } = bsGreeks({ ...ATM_CASE, optionType: "call" });
    // φ(0.05) / (100 · 0.2 · 0.5) = 0.0398444…; ×1000 = 39.8444…
    const raw = normPdf(0.05) / (100 * 0.2 * Math.sqrt(0.25));
    expect(gamma).toBeCloseTo(raw * GAMMA_SCALE, 9);
    expect(gamma).toBeCloseTo(39.8444, 3);
  });

  it("returns theta per calendar day, not annualised", () => {
    const { theta } = bsGreeks({ ...ATM_CASE, optionType: "call" });
    // Annualised: −S·φ(d1)·σ / (2√T) = −100 · 0.398444 · 0.2 / 1 = −7.96888
    const annual = -(100 * normPdf(0.05) * 0.2) / (2 * Math.sqrt(0.25));
    expect(theta).toBeCloseTo(annual / DAYS_PER_YEAR, 10);
    expect(theta).toBeLessThan(0);
    expect(theta).toBeCloseTo(-0.021833, 5);
  });

  it("returns vega per 1 percentage-point IV move", () => {
    const { vega } = bsGreeks({ ...ATM_CASE, optionType: "call" });
    // S·φ(d1)·√T / 100 = 100 · 0.398444 · 0.5 / 100 = 0.199222
    expect(vega).toBeCloseTo(0.199222, 6);
    expect(vega).toBeGreaterThan(0);
  });

  it("signs rho by side", () => {
    const call = bsGreeks({ ...ATM_CASE, rate: 0.05, optionType: "call" });
    const put = bsGreeks({ ...ATM_CASE, rate: 0.05, optionType: "put" });
    expect(call.rho).toBeGreaterThan(0);
    expect(put.rho).toBeLessThan(0);
  });

  it("keeps call delta in [0, 1] and put delta in [-1, 0] across the chain", () => {
    for (const strike of [50, 80, 95, 100, 105, 120, 200]) {
      const call = bsGreeks({ ...ATM_CASE, strike, optionType: "call" });
      const put = bsGreeks({ ...ATM_CASE, strike, optionType: "put" });
      expect(call.delta).toBeGreaterThanOrEqual(0);
      expect(call.delta).toBeLessThanOrEqual(1);
      expect(put.delta).toBeGreaterThanOrEqual(-1);
      expect(put.delta).toBeLessThanOrEqual(0);
      expect(call.theta).toBeLessThanOrEqual(0);
      expect(call.gamma).toBeGreaterThanOrEqual(0);
      expect(call.vega).toBeGreaterThanOrEqual(0);
    }
  });

  it("gives a deep in-the-money call delta near 1 and a deep out-of-the-money one near 0", () => {
    expect(bsGreeks({ ...ATM_CASE, strike: 20, optionType: "call" }).delta).toBeCloseTo(1, 3);
    expect(bsGreeks({ ...ATM_CASE, strike: 500, optionType: "call" }).delta).toBeCloseTo(0, 3);
  });

  it("peaks gamma at the money", () => {
    const atm = bsGreeks({ ...ATM_CASE, optionType: "call" }).gamma;
    expect(atm).toBeGreaterThan(bsGreeks({ ...ATM_CASE, strike: 80, optionType: "call" }).gamma);
    expect(atm).toBeGreaterThan(bsGreeks({ ...ATM_CASE, strike: 120, optionType: "call" }).gamma);
  });

  it("shows the gamma/theta term structure — a near expiry is sharper", () => {
    const near = bsGreeks({ ...ATM_CASE, timeToExpiryYears: yearsFromDays(7), optionType: "call" });
    const far = bsGreeks({ ...ATM_CASE, timeToExpiryYears: yearsFromDays(90), optionType: "call" });
    expect(near.gamma).toBeGreaterThan(far.gamma);
    expect(near.theta).toBeLessThan(far.theta); // more negative
    expect(near.vega).toBeLessThan(far.vega);
  });

  it("fails inert on degenerate input rather than emitting a lone delta", () => {
    const inert = { delta: 0, gamma: 0, theta: 0, vega: 0, rho: 0 };
    expect(bsGreeks({ ...ATM_CASE, timeToExpiryYears: 0, optionType: "call" })).toEqual(inert);
    expect(bsGreeks({ ...ATM_CASE, volatility: 0, optionType: "call" })).toEqual(inert);
    expect(bsGreeks({ ...ATM_CASE, spot: 0, optionType: "call" })).toEqual(inert);
    expect(bsGreeks({ ...ATM_CASE, strike: 0, optionType: "call" })).toEqual(inert);
    expect(bsGreeks({ ...ATM_CASE, spot: Number.NaN, optionType: "call" })).toEqual(inert);
    expect(bsGreeks({ ...ATM_CASE, rate: Number.NaN, optionType: "call" })).toEqual(inert);
  });

  it("cross-checks an NIFTY-scale weekly call against hand-computed values", () => {
    // S = 22,000, K = 22,000, 8 DTE, IV 15%, r = 0.
    const g = bsGreeks({
      spot: 22000,
      strike: 22000,
      timeToExpiryYears: yearsFromDays(8),
      volatility: 0.15,
      optionType: "call",
    });
    const T = 8 / 365;
    const dOne = (0.5 * 0.15 * 0.15 * T) / (0.15 * Math.sqrt(T));
    expect(g.delta).toBeCloseTo(normCdf(dOne), 9);
    expect(g.delta).toBeGreaterThan(0.5);
    expect(g.delta).toBeLessThan(0.51);
    expect(g.gamma).toBeCloseTo(0.8163, 3);
    expect(g.vega).toBeCloseTo(12.99, 1);
  });
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

describe("yearsFromDays", () => {
  it("divides by the calendar year", () => {
    expect(yearsFromDays(365)).toBe(1);
    expect(yearsFromDays(8)).toBeCloseTo(8 / 365, 12);
  });

  it("returns 0 for a non-positive or non-finite count", () => {
    expect(yearsFromDays(0)).toBe(0);
    expect(yearsFromDays(-3)).toBe(0);
    expect(yearsFromDays(Number.NaN)).toBe(0);
  });
});

describe("normaliseIv", () => {
  it("passes a decimal fraction through untouched", () => {
    expect(normaliseIv(0.148)).toBeCloseTo(0.148, 6);
    expect(normaliseIv(1.5)).toBeCloseTo(1.5, 6);
  });

  it("scales percentage points down to a fraction", () => {
    expect(normaliseIv(14.8)).toBeCloseTo(0.148, 6);
    expect(normaliseIv(1.51)).toBeCloseTo(0.0151, 6);
  });

  it("returns 0 for non-positive or non-finite input", () => {
    expect(normaliseIv(0)).toBe(0);
    expect(normaliseIv(-5)).toBe(0);
    expect(normaliseIv(Number.NaN)).toBe(0);
    expect(normaliseIv(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

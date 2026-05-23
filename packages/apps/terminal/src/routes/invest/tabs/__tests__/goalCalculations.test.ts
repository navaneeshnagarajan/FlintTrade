/**
 * goalCalculations.test.ts — Unit tests for goal-based investment calculations
 */

import { describe, it, expect } from "vitest";
import {
  computeProjectedValue,
  computeRequiredSip,
  monthsUntil,
} from "../GoalTab";

describe("computeProjectedValue", () => {
  it("returns current savings when months remaining is 0", () => {
    expect(computeProjectedValue(100_000, 10_000, 12, 0)).toBe(100_000);
  });

  it("returns current savings when months remaining is negative", () => {
    expect(computeProjectedValue(100_000, 10_000, 12, -5)).toBe(100_000);
  });

  it("calculates correctly with 0% return rate", () => {
    // Simple addition: 1L + 10K * 12 = 2.2L
    expect(computeProjectedValue(100_000, 10_000, 0, 12)).toBe(220_000);
  });

  it("calculates lump sum growth correctly with no SIP", () => {
    // 1L at 12% for 12 months (monthly compounding)
    const result = computeProjectedValue(100_000, 0, 12, 12);
    // Expected: 100000 * (1 + 0.01)^12 = ~112682.50
    expect(result).toBeCloseTo(112_682.5, 0);
  });

  it("calculates SIP growth correctly with no lump sum", () => {
    // 10K/month at 12% for 12 months
    const result = computeProjectedValue(0, 10_000, 12, 12);
    // SIP FV: 10000 * ((1.01^12 - 1) / 0.01) = ~126825.03
    expect(result).toBeCloseTo(126_825, 0);
  });

  it("calculates combined lump sum + SIP correctly", () => {
    const result = computeProjectedValue(100_000, 10_000, 12, 12);
    // Lump ~112682 + SIP ~126825 = ~239507
    expect(result).toBeCloseTo(239_507, -1);
  });

  it("handles large durations (20 years = 240 months)", () => {
    const result = computeProjectedValue(500_000, 25_000, 12, 240);
    // Should be a large number, just verify it's positive and larger than inputs
    expect(result).toBeGreaterThan(500_000 + 25_000 * 240);
  });
});

describe("computeRequiredSip", () => {
  it("returns 0 when months remaining is 0", () => {
    expect(computeRequiredSip(1_000_000, 100_000, 12, 0)).toBe(0);
  });

  it("returns 0 when current savings already exceed target (with growth)", () => {
    // 10L invested, target 10L, 12% for 12 months — already on track
    expect(computeRequiredSip(1_000_000, 1_000_000, 12, 12)).toBe(0);
  });

  it("calculates correctly with 0% return", () => {
    // Need 10L more over 10 months = 1L/month
    const result = computeRequiredSip(1_000_000, 0, 0, 10);
    expect(result).toBe(100_000);
  });

  it("calculates a realistic SIP requirement", () => {
    // Target: 50L, Current: 5L, Rate: 12%, Time: 5 years (60 months)
    const result = computeRequiredSip(5_000_000, 500_000, 12, 60);
    // Should be a reasonable monthly amount
    expect(result).toBeGreaterThan(0);
    expect(result).toBeLessThan(100_000); // Should be well under 1L/month for this target
  });

  it("returns 0 when lump sum growth alone meets target", () => {
    // 40L at 12% for 5 years = 40L * (1.01)^60 ~ 72.7L > 50L target
    const result = computeRequiredSip(5_000_000, 4_000_000, 12, 60);
    expect(result).toBe(0);
  });
});

describe("monthsUntil", () => {
  it("returns 0 for past dates", () => {
    expect(monthsUntil("2020-01-01")).toBe(0);
  });

  it("returns positive months for future dates", () => {
    const future = new Date();
    future.setFullYear(future.getFullYear() + 2);
    const result = monthsUntil(future.toISOString().split("T")[0]);
    expect(result).toBeGreaterThanOrEqual(23);
    expect(result).toBeLessThanOrEqual(25);
  });

  it("returns 12 for exactly one year ahead", () => {
    const future = new Date();
    future.setFullYear(future.getFullYear() + 1);
    const result = monthsUntil(future.toISOString().split("T")[0]);
    expect(result).toBe(12);
  });
});

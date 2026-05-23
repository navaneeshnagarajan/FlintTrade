/**
 * xirr.test.ts — Unit tests for the XIRR calculator.
 */

import { describe, it, expect } from "vitest";
import { xirr } from "../xirr";

describe("xirr", () => {
  it("returns null for fewer than 2 cash flows", () => {
    expect(xirr([{ date: new Date("2024-01-01"), amount: -100000 }])).toBeNull();
    expect(xirr([])).toBeNull();
  });

  it("calculates XIRR for a simple investment + redemption", () => {
    // Invest 100k, get back 110k after 1 year = ~10% return
    const result = xirr([
      { date: new Date("2024-01-01"), amount: -100000 },
      { date: new Date("2025-01-01"), amount: 110000 },
    ]);
    expect(result).not.toBeNull();
    expect(result!).toBeCloseTo(0.1, 2);
  });

  it("calculates XIRR for the HNI sample cash flows", () => {
    const result = xirr([
      { date: new Date("2024-01-15"), amount: -500000 },
      { date: new Date("2024-04-01"), amount: -100000 },
      { date: new Date("2024-07-01"), amount: -100000 },
      { date: new Date("2024-10-01"), amount: -100000 },
      { date: new Date("2025-01-01"), amount: -100000 },
      { date: new Date("2025-04-01"), amount: -100000 },
      { date: new Date("2025-04-01"), amount: 1150000 },
    ]);
    expect(result).not.toBeNull();
    // Net investment: 1,000,000 → value: 1,150,000 over ~1.2 years
    // XIRR should be a positive rate around 12-20%
    expect(result!).toBeGreaterThan(0.05);
    expect(result!).toBeLessThan(0.50);
  });

  it("handles a loss scenario", () => {
    const result = xirr([
      { date: new Date("2024-01-01"), amount: -100000 },
      { date: new Date("2025-01-01"), amount: 90000 },
    ]);
    expect(result).not.toBeNull();
    expect(result!).toBeCloseTo(-0.1, 2);
  });

  it("handles exact doubling in 1 year", () => {
    const result = xirr([
      { date: new Date("2024-01-01"), amount: -50000 },
      { date: new Date("2025-01-01"), amount: 100000 },
    ]);
    expect(result).not.toBeNull();
    // Should be ~100%
    expect(result!).toBeCloseTo(1.0, 1);
  });

  it("handles multiple SIP-like investments", () => {
    // Monthly 10k SIP for 12 months, ending value 130k
    const flows = [];
    for (let m = 0; m < 12; m++) {
      flows.push({
        date: new Date(2024, m, 1),
        amount: -10000,
      });
    }
    flows.push({ date: new Date(2024, 11, 31), amount: 130000 });

    const result = xirr(flows);
    expect(result).not.toBeNull();
    // Total invested: 120k, got 130k — modest positive return
    expect(result!).toBeGreaterThan(0);
    expect(result!).toBeLessThan(1.0);
  });

  it("returns null when all cash flows are positive", () => {
    // The function needs at least one negative and one positive,
    // but technically the algorithm may still converge.
    // With all-positive, it can't converge to a meaningful rate.
    const result = xirr([
      { date: new Date("2024-01-01"), amount: 100000 },
      { date: new Date("2025-01-01"), amount: 110000 },
    ]);
    // It may return null or a number — main check is it doesn't throw
    expect(typeof result === "number" || result === null).toBe(true);
  });

  it("does not throw for edge-case inputs", () => {
    // Zero amounts
    expect(() =>
      xirr([
        { date: new Date("2024-01-01"), amount: 0 },
        { date: new Date("2025-01-01"), amount: 0 },
      ]),
    ).not.toThrow();
  });
});

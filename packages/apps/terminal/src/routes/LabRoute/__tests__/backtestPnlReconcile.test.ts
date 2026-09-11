/**
 * backtestPnlReconcile.test.ts
 *
 * Pins FT-LAB-004: Lab headline Total Return is initial capital → final
 * equity. Net trade P&L is the Trade Log *net* sum when ``net_pnl`` is
 * present; otherwise the helper reports a labelled gross fallback.
 */

import { describe, expect, it } from "vitest";
import {
  backtestPnlHelper,
  equityCurveDelta,
  headlineTotalReturnFraction,
  sumTradeLogPnl,
} from "../backtestPnlReconcile";

describe("sumTradeLogPnl", () => {
  it("sums net_pnl when every trade carries it", () => {
    expect(
      sumTradeLogPnl([
        { pnl: 2000, net_pnl: 1960 },
        { pnl: 1000, net_pnl: 960 },
        { pnl: -1500, net_pnl: -1540 },
      ]),
    ).toEqual({ amount: 1380, basis: "net" });
  });

  it("falls back to gross pnl and says so when net_pnl is missing", () => {
    expect(
      sumTradeLogPnl([{ pnl: 2000 }, { pnl: 1000 }, { pnl: -1500 }]),
    ).toEqual({ amount: 1500, basis: "gross" });
  });

  it("is a zero net sum when the trade log is empty", () => {
    expect(sumTradeLogPnl([])).toEqual({ amount: 0, basis: "net" });
  });
});

describe("equityCurveDelta", () => {
  it("is final equity minus the first equity-curve point", () => {
    expect(
      equityCurveDelta(
        [{ equity: 100000 }, { equity: 102000 }, { equity: 104500 }],
        104500,
      ),
    ).toBe(4500);
  });

  it("uses final equity, not the last curve point, after a forced close", () => {
    expect(
      equityCurveDelta(
        [{ equity: 100000 }, { equity: 102000 }, { equity: 104000 }],
        104500,
      ),
    ).toBe(4500);
  });

  it("is zero when there is no curve to compare against final equity", () => {
    expect(equityCurveDelta([], 104500)).toBe(0);
  });
});

describe("headlineTotalReturnFraction", () => {
  it("derives the fraction from initial capital → final equity", () => {
    expect(headlineTotalReturnFraction(4.5, 104500, 100000)).toBeCloseTo(0.045);
    expect(headlineTotalReturnFraction(0.045, 104500, 100000)).toBeCloseTo(0.045);
  });

  it("does not use a live percentage-point total_return as a fraction", () => {
    // 4.5 means 4.5% on the backend. Treating it as a fraction would be 450%.
    expect(headlineTotalReturnFraction(4.5, 104500, 100000) * 100).toBeCloseTo(4.5);
  });

  it("falls back to a fraction when start equity is missing, accepting either unit", () => {
    expect(headlineTotalReturnFraction(0.045, 104500, undefined)).toBeCloseTo(0.045);
    expect(headlineTotalReturnFraction(4.5, 104500, undefined)).toBeCloseTo(0.045);
  });
});

describe("backtestPnlHelper", () => {
  it("quietly notes when the trade-log sum matches the equity change", () => {
    expect(backtestPnlHelper(4500, 4500)).toBe("Reconciles with trade log");
  });

  it("treats sub-paisa drift as a reconcile, matching displayed INR", () => {
    expect(backtestPnlHelper(4500.004, 4500)).toBe("Reconciles with trade log");
  });

  it("explains a diverge instead of leaving two mystery totals", () => {
    expect(backtestPnlHelper(1500, 4500)).toBe(
      "Trade log sum ≠ equity change — fees / open marks",
    );
  });
});

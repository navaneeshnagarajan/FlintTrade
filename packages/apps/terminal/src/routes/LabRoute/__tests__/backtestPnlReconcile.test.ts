/**
 * backtestPnlReconcile.test.ts
 *
 * Pins FT-LAB-004: Lab headline Total Return is an equity-curve figure.
 * Net trade P&L is the Trade Log sum. The helper is either a quiet
 * reconcile note or an explicit diverge line — never two unlabeled totals.
 */

import { describe, expect, it } from "vitest";
import {
  backtestPnlHelper,
  equityCurveDelta,
  sumTradeLogPnl,
} from "../backtestPnlReconcile";

describe("sumTradeLogPnl", () => {
  it("sums Trade Log P&L on the same rupee basis as the table", () => {
    expect(
      sumTradeLogPnl([{ pnl: 2000 }, { pnl: 1000 }, { pnl: -1500 }]),
    ).toBe(1500);
  });

  it("is zero when the trade log is empty", () => {
    expect(sumTradeLogPnl([])).toBe(0);
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

  it("is zero when there is no curve to compare against final equity", () => {
    expect(equityCurveDelta([], 104500)).toBe(0);
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

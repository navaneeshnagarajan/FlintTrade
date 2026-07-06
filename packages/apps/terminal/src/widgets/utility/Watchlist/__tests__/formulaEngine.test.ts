import { describe, it, expect } from "vitest";
import { compileFormula, FORMULA_FIELD_NAMES } from "../formulaEngine";
import type { PartialQuote } from "../types";

const QUOTE: PartialQuote = {
  ltp: 100,
  open: 98,
  high: 105,
  low: 95,
  close: 100,
  prev_close: 96,
  volume: 50000,
};

function evalExpr(expr: string, quote: PartialQuote = QUOTE): number | null {
  const res = compileFormula(expr);
  if (!res.ok) throw new Error(res.error);
  return res.formula.evaluate(quote);
}

describe("formulaEngine", () => {
  it("evaluates basic arithmetic over fields", () => {
    expect(evalExpr("high - low")).toBe(10);
    expect(evalExpr("(high - low) / ltp * 100")).toBeCloseTo(10);
    expect(evalExpr("ltp - prev_close")).toBe(4);
  });

  it("honours operator precedence and parentheses", () => {
    // ltp = 100: 2 * 100 + 3 = 203 (× before +); 2 * (100 + 3) = 206.
    expect(evalExpr("2 * ltp + 3")).toBe(203);
    expect(evalExpr("2 * (ltp + 3)")).toBe(206);
  });

  it("supports unary minus", () => {
    expect(evalExpr("-ltp + high")).toBe(5);
    expect(evalExpr("-(high - low)")).toBe(-10);
  });

  it("returns null on division by zero without throwing", () => {
    expect(evalExpr("ltp / (high - high)")).toBeNull();
  });

  it("returns null when a referenced field is missing", () => {
    expect(evalExpr("high - low", { ltp: 100 })).toBeNull();
  });

  it("rejects unknown identifiers at compile time", () => {
    const res = compileFormula("foo + 1");
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.error).toMatch(/Unknown field/);
  });

  it("rejects an expression with no fields", () => {
    const res = compileFormula("1 + 2");
    expect(res.ok).toBe(false);
  });

  it("rejects unbalanced parentheses", () => {
    expect(compileFormula("(high - low").ok).toBe(false);
    expect(compileFormula("high - low)").ok).toBe(false);
  });

  it("rejects an empty formula", () => {
    expect(compileFormula("   ").ok).toBe(false);
  });

  it("does not execute arbitrary JavaScript", () => {
    // Property access, function calls and JS globals are not valid tokens.
    expect(compileFormula("ltp.constructor").ok).toBe(false);
    expect(compileFormula("alert(1)").ok).toBe(false);
    expect(compileFormula("ltp; return 1").ok).toBe(false);
  });

  it("exposes the allowed field names", () => {
    expect(FORMULA_FIELD_NAMES).toContain("ltp");
    expect(FORMULA_FIELD_NAMES).toContain("prev_close");
    expect(FORMULA_FIELD_NAMES).not.toContain("constructor");
  });
});

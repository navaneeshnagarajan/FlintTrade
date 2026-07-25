/**
 * spreadAnalysis.test.ts
 *
 * The `analyseSpread` block below is ported VERBATIM from the retired
 * `widgets/analysis/SpreadView/__tests__/SpreadViewWidget.test.tsx`. SpreadView
 * itself was template data (four hardcoded verticals, no data source, execution
 * hardwired off) and now lives in `lib/strategyTemplates`, but its economic
 * validator was the only one of its kind in the option-strategy family — so the
 * maths moved with its test suite rather than being deleted.
 *
 * The `analyseVerticalSpread` block is new: it covers the capability the Lab
 * Strategy Builder gained, namely recognising a two-leg vertical typed into its
 * legs table and applying exactly these rules to it.
 */

import { describe, it, expect } from "vitest";

import {
  analyseSpread,
  analyseVerticalSpread,
  asVerticalSpread,
  type PayoffPoint,
  type SpreadAnalysis,
  type SpreadInputs,
  type SpreadMetrics,
  type SpreadType,
  type VerticalSpreadLeg,
} from "../spreadAnalysis";

function expectValid(
  result: SpreadAnalysis,
): asserts result is Extract<SpreadAnalysis, { valid: true }> {
  expect(result.valid).toBe(true);
  if (!result.valid) {
    throw new Error(result.error);
  }
}

describe("analyseSpread", () => {
  const validCases: Array<{
    type: SpreadType;
    inputs: SpreadInputs;
    metrics: Pick<SpreadMetrics, "maxProfit" | "maxLoss" | "breakeven">;
    first: PayoffPoint;
    last: PayoffPoint;
  }> = [
    {
      type: "bull-call",
      inputs: { longStrike: 24000, shortStrike: 24200, premium: 45, lotSize: 25 },
      metrics: { maxProfit: 3875, maxLoss: 1125, breakeven: 24045 },
      first: { price: 23900, pnl: -1125 },
      last: { price: 24300, pnl: 3875 },
    },
    {
      type: "bear-put",
      inputs: { longStrike: 24000, shortStrike: 23800, premium: 50, lotSize: 25 },
      metrics: { maxProfit: 3750, maxLoss: 1250, breakeven: 23950 },
      first: { price: 23700, pnl: 3750 },
      last: { price: 24100, pnl: -1250 },
    },
    {
      type: "bull-put",
      inputs: { longStrike: 23800, shortStrike: 24000, premium: -30, lotSize: 25 },
      metrics: { maxProfit: 750, maxLoss: 4250, breakeven: 23970 },
      first: { price: 23700, pnl: -4250 },
      last: { price: 24100, pnl: 750 },
    },
    {
      type: "bear-call",
      inputs: { longStrike: 24200, shortStrike: 24000, premium: -35, lotSize: 25 },
      metrics: { maxProfit: 875, maxLoss: 4125, breakeven: 24035 },
      first: { price: 23900, pnl: 875 },
      last: { price: 24300, pnl: -4125 },
    },
  ];

  it.each(validCases)(
    "computes max profit, max loss, and breakeven for $type",
    ({ type, inputs, metrics }) => {
      const result = analyseSpread(type, inputs);
      expectValid(result);
      expect(result.metrics).toMatchObject(metrics);
    },
  );

  it.each(validCases)(
    "builds $type payoff endpoints from the explicit long and short legs",
    ({ type, inputs, first, last }) => {
      const result = analyseSpread(type, inputs);
      expectValid(result);
      expect(result.payoff[0]).toEqual(first);
      expect(result.payoff.at(-1)).toEqual(last);
    },
  );

  it.each([
    { name: "zero long strike", inputs: { longStrike: 0, shortStrike: 24200, premium: 45, lotSize: 25 } },
    { name: "negative short strike", inputs: { longStrike: 24000, shortStrike: -1, premium: 45, lotSize: 25 } },
    { name: "non-finite long strike", inputs: { longStrike: Number.POSITIVE_INFINITY, shortStrike: 24200, premium: 45, lotSize: 25 } },
    { name: "non-finite short strike", inputs: { longStrike: 24000, shortStrike: Number.NaN, premium: 45, lotSize: 25 } },
  ])("rejects $name", ({ inputs }) => {
    expect(analyseSpread("bull-call", inputs).valid).toBe(false);
  });

  it.each([
    { name: "zero", lotSize: 0 },
    { name: "negative", lotSize: -1 },
    { name: "fractional", lotSize: 1.5 },
    { name: "non-finite", lotSize: Number.POSITIVE_INFINITY },
  ])("rejects a $name lot size", ({ lotSize }) => {
    const result = analyseSpread("bull-call", {
      longStrike: 24000,
      shortStrike: 24200,
      premium: 45,
      lotSize,
    });
    expect(result.valid).toBe(false);
  });

  it.each([
    { type: "bull-call" as const, longStrike: 24200, shortStrike: 24000 },
    { type: "bear-put" as const, longStrike: 23800, shortStrike: 24000 },
    { type: "bull-put" as const, longStrike: 24000, shortStrike: 23800 },
    { type: "bear-call" as const, longStrike: 24000, shortStrike: 24200 },
  ])("rejects incorrectly ordered $type legs", ({ type, longStrike, shortStrike }) => {
    const premium = type === "bull-call" || type === "bear-put" ? 40 : -40;
    expect(analyseSpread(type, { longStrike, shortStrike, premium, lotSize: 25 }).valid).toBe(false);
  });

  it.each([
    { name: "zero debit", type: "bull-call" as const, premium: 0 },
    { name: "negative debit", type: "bear-put" as const, premium: -1 },
    { name: "debit above spread width", type: "bull-call" as const, premium: 201 },
    { name: "zero credit", type: "bull-put" as const, premium: 0 },
    { name: "positive credit", type: "bear-call" as const, premium: 1 },
    { name: "credit above spread width", type: "bull-put" as const, premium: -201 },
    { name: "non-finite premium", type: "bear-call" as const, premium: Number.NaN },
  ])("rejects $name", ({ type, premium }) => {
    const isLongLower = type === "bull-call" || type === "bull-put";
    const inputs = isLongLower
      ? { longStrike: 24000, shortStrike: 24200, premium, lotSize: 25 }
      : { longStrike: 24200, shortStrike: 24000, premium, lotSize: 25 };
    expect(analyseSpread(type, inputs).valid).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Builder bridge — the capability the Lab Strategy Builder gained
// ---------------------------------------------------------------------------

/** NIFTY's post-Nov-2024 contract lot size, matching StrategyBuilder types.ts. */
const NIFTY_LOT = 75;

function leg(partial: Partial<VerticalSpreadLeg> = {}): VerticalSpreadLeg {
  return { action: "BUY", optionType: "CE", strike: 24000, lots: 1, premium: 50, ...partial };
}

describe("asVerticalSpread — classification", () => {
  it.each([
    { type: "bull-call", optionType: "CE" as const, longStrike: 24000, shortStrike: 24200 },
    { type: "bear-call", optionType: "CE" as const, longStrike: 24200, shortStrike: 24000 },
    { type: "bull-put",  optionType: "PE" as const, longStrike: 23800, shortStrike: 24000 },
    { type: "bear-put",  optionType: "PE" as const, longStrike: 24000, shortStrike: 23800 },
  ])("derives $type from the option type and leg order", ({ type, optionType, longStrike, shortStrike }) => {
    const spread = asVerticalSpread(
      [
        leg({ action: "BUY", optionType, strike: longStrike, premium: 60 }),
        leg({ action: "SELL", optionType, strike: shortStrike, premium: 20 }),
      ],
      NIFTY_LOT,
    );
    expect(spread?.type).toBe(type);
  });

  it("scales the quantity by the contract lot size, not a hardcoded 25", () => {
    const spread = asVerticalSpread(
      [
        leg({ action: "BUY", strike: 24000, lots: 2, premium: 60 }),
        leg({ action: "SELL", strike: 24200, lots: 2, premium: 20 }),
      ],
      NIFTY_LOT,
    );
    expect(spread?.inputs.lotSize).toBe(150);
  });

  it("nets the two per-leg premiums into one signed spread premium", () => {
    const debit = asVerticalSpread(
      [
        leg({ action: "BUY", strike: 24000, premium: 60 }),
        leg({ action: "SELL", strike: 24200, premium: 20 }),
      ],
      NIFTY_LOT,
    );
    expect(debit?.inputs.premium).toBe(40);

    const credit = asVerticalSpread(
      [
        leg({ action: "BUY", optionType: "PE", strike: 23800, premium: 20 }),
        leg({ action: "SELL", optionType: "PE", strike: 24000, premium: 55 }),
      ],
      NIFTY_LOT,
    );
    expect(credit?.inputs.premium).toBe(-35);
  });

  it.each([
    { name: "a single leg", legs: [leg()] },
    { name: "three legs", legs: [leg(), leg({ action: "SELL", strike: 24200 }), leg({ strike: 24400 })] },
    { name: "both legs bought", legs: [leg({ strike: 24000 }), leg({ strike: 24200 })] },
    { name: "both legs sold", legs: [leg({ action: "SELL", strike: 24000 }), leg({ action: "SELL", strike: 24200 })] },
    { name: "mixed option types (a strangle)", legs: [leg({ optionType: "CE", strike: 24200 }), leg({ action: "SELL", optionType: "PE", strike: 23800 })] },
    { name: "unequal lots (a ratio spread)", legs: [leg({ strike: 24000, lots: 1 }), leg({ action: "SELL", strike: 24200, lots: 2 })] },
    { name: "the same strike on both legs", legs: [leg({ strike: 24000 }), leg({ action: "SELL", strike: 24000 })] },
  ])("does not classify $name as a vertical", ({ legs }) => {
    expect(asVerticalSpread(legs, NIFTY_LOT)).toBeNull();
  });
});

describe("analyseVerticalSpread — economic rejection in the builder", () => {
  it("says nothing about shapes that are not verticals", () => {
    const straddle: VerticalSpreadLeg[] = [
      leg({ action: "SELL", optionType: "CE", strike: 24000, premium: 120 }),
      leg({ action: "SELL", optionType: "PE", strike: 24000, premium: 110 }),
    ];
    expect(analyseVerticalSpread(straddle, NIFTY_LOT)).toEqual({ kind: "not-a-vertical" });
  });

  it("treats a freshly loaded template as unpriced rather than invalid", () => {
    // Templates land with premium 0 on every leg until the operator types one.
    const result = analyseVerticalSpread(
      [
        leg({ action: "BUY", strike: 24000, premium: 0 }),
        leg({ action: "SELL", strike: 24050, premium: 0 }),
      ],
      NIFTY_LOT,
    );
    expect(result.kind).toBe("unpriced");
  });

  it("accepts a coherent debit vertical and reports its economics", () => {
    const result = analyseVerticalSpread(
      [
        leg({ action: "BUY", strike: 24000, premium: 100 }),
        leg({ action: "SELL", strike: 24200, premium: 55 }),
      ],
      25, // the widget's old quantity, so the pinned numbers carry across
    );
    expect(result.kind).toBe("valid");
    if (result.kind !== "valid") throw new Error("expected a valid vertical");
    expect(result.spread.type).toBe("bull-call");
    expect(result.metrics).toMatchObject({ maxProfit: 3875, maxLoss: 1125, breakeven: 24045 });
    expect(result.payoff).toHaveLength(41);
  });

  it("accepts a coherent credit vertical", () => {
    const result = analyseVerticalSpread(
      [
        leg({ action: "BUY", optionType: "PE", strike: 23800, premium: 25 }),
        leg({ action: "SELL", optionType: "PE", strike: 24000, premium: 55 }),
      ],
      25,
    );
    expect(result.kind).toBe("valid");
    if (result.kind !== "valid") throw new Error("expected a valid vertical");
    expect(result.spread.type).toBe("bull-put");
    expect(result.metrics).toMatchObject({ maxProfit: 750, maxLoss: 4250, breakeven: 23970 });
  });

  it("rejects a debit larger than the strike width", () => {
    // 200-wide bull call bought for 210 — unrecoverable at expiry, and the
    // rejection `validateLegs` alone could never make.
    const result = analyseVerticalSpread(
      [
        leg({ action: "BUY", strike: 24000, premium: 250 }),
        leg({ action: "SELL", strike: 24200, premium: 40 }),
      ],
      NIFTY_LOT,
    );
    expect(result.kind).toBe("invalid");
    if (result.kind !== "invalid") throw new Error("expected an invalid vertical");
    expect(result.error).toMatch(/debit/i);
  });

  it("rejects a credit larger than the strike width", () => {
    const result = analyseVerticalSpread(
      [
        leg({ action: "BUY", optionType: "PE", strike: 23800, premium: 10 }),
        leg({ action: "SELL", optionType: "PE", strike: 24000, premium: 260 }),
      ],
      NIFTY_LOT,
    );
    expect(result.kind).toBe("invalid");
    if (result.kind !== "invalid") throw new Error("expected an invalid vertical");
    expect(result.error).toMatch(/credit/i);
  });

  it("rejects a debit structure priced as a credit", () => {
    // Buying the lower call for less than the higher one sells for is a free
    // lunch, not a bull call spread.
    const result = analyseVerticalSpread(
      [
        leg({ action: "BUY", strike: 24000, premium: 30 }),
        leg({ action: "SELL", strike: 24200, premium: 80 }),
      ],
      NIFTY_LOT,
    );
    expect(result.kind).toBe("invalid");
  });

  it("rejects a credit structure priced as a debit", () => {
    const result = analyseVerticalSpread(
      [
        leg({ action: "BUY", optionType: "PE", strike: 23800, premium: 90 }),
        leg({ action: "SELL", optionType: "PE", strike: 24000, premium: 40 }),
      ],
      NIFTY_LOT,
    );
    expect(result.kind).toBe("invalid");
  });

  it("rejects a non-positive contract lot size", () => {
    const result = analyseVerticalSpread(
      [
        leg({ action: "BUY", strike: 24000, premium: 100 }),
        leg({ action: "SELL", strike: 24200, premium: 55 }),
      ],
      0,
    );
    expect(result.kind).toBe("invalid");
    if (result.kind !== "invalid") throw new Error("expected an invalid vertical");
    expect(result.error).toMatch(/lot size/i);
  });

  it("never fails the leg-order rule, because the order defines the type", () => {
    // SpreadView made the operator pick a type and then rejected mismatched
    // legs. The builder derives the type instead, so every ordering is a
    // legitimate spread of some kind.
    for (const [lower, higher] of [[24000, 24200], [24200, 24000]]) {
      const result = analyseVerticalSpread(
        [
          leg({ action: "BUY", strike: lower, premium: 100 }),
          leg({ action: "SELL", strike: higher, premium: 55 }),
        ],
        NIFTY_LOT,
      );
      expect(result.kind).not.toBe("not-a-vertical");
      if (result.kind === "invalid") {
        expect(result.error).not.toMatch(/requires the long strike/i);
      }
    }
  });
});

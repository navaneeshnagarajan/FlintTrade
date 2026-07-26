/**
 * spreadAnalysis — vertical option-spread economics.
 *
 * This module is the surviving half of the retired `SpreadView` widget. That
 * widget was four hardcoded two-leg verticals over hand-typed premiums with no
 * data source and no execution path — a template, not a widget — so its four
 * shapes now live in `lib/strategyTemplates` (`bull-call-spread`,
 * `bear-put-spread`, `bull-put-spread`, `bear-call-spread`) and load into the
 * Lab Strategy Builder like any other catalogue entry.
 *
 * What did NOT exist anywhere else was its input validation, and that is what
 * this file carries forward. `validateLegs` in the builder only checks that a
 * leg has a positive strike, at least one lot, and a non-negative premium; it
 * cannot tell you that the vertical you just typed is economically impossible.
 * The rules below can:
 *
 *   - leg order must match the spread type (a bull call buys the LOWER call);
 *   - a debit spread must cost more than nothing and no more than the strike
 *     width — a debit above the width can never be recovered at expiry;
 *   - a credit spread must actually be a credit, and no larger than the width;
 *   - quantity must be a positive whole number, strikes finite and positive.
 *
 * `analyseSpread` keeps the exact signature and arithmetic the widget's test
 * suite pinned (see `__tests__/spreadAnalysis.test.ts`, ported verbatim).
 * `analyseVerticalSpread` is the new half: it recognises a two-leg vertical in
 * the builder's leg table and runs the same rules over it.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SpreadType = "bull-call" | "bear-put" | "bull-put" | "bear-call";

export interface SpreadInputs {
  longStrike: number;
  shortStrike: number;
  /** Per-unit net premium: positive = debit paid, negative = credit received. */
  premium: number;
  /** Quantity the per-unit premium is multiplied by (contract lot size × lots). */
  lotSize: number;
}

export interface SpreadMetrics {
  maxProfit: number;
  maxLoss: number;
  breakeven: number;
  netPremium: number;
  illustrativeMarginProxy: number;
  isDebit: boolean;
}

export interface PayoffPoint {
  price: number;
  pnl: number;
}

export type SpreadAnalysis =
  | { valid: true; metrics: SpreadMetrics; payoff: PayoffPoint[] }
  | { valid: false; error: string };

// ---------------------------------------------------------------------------
// Spread definitions
// ---------------------------------------------------------------------------

export interface SpreadTypeInfo {
  id: SpreadType;
  label: string;
  description: string;
  /** Catalogue entry in `lib/strategyTemplates` that builds this shape. */
  templateId: string;
}

export const SPREAD_TYPES: readonly SpreadTypeInfo[] = [
  { id: "bull-call", label: "Bull Call", templateId: "bull-call-spread", description: "Buy lower call, sell higher call. Debit spread. Bullish." },
  { id: "bear-put",  label: "Bear Put",  templateId: "bear-put-spread",  description: "Buy higher put, sell lower put. Debit spread. Bearish." },
  { id: "bull-put",  label: "Bull Put",  templateId: "bull-put-spread",  description: "Sell higher put, buy lower put. Credit spread. Bullish." },
  { id: "bear-call", label: "Bear Call", templateId: "bear-call-spread", description: "Sell lower call, buy higher call. Credit spread. Bearish." },
];

/** True when the type is paid for (debit) rather than received (credit). */
export function isDebitSpread(type: SpreadType): boolean {
  return type === "bull-call" || type === "bear-put";
}

/** True when the bought leg sits at the lower strike. */
export function longLegIsLower(type: SpreadType): boolean {
  return type === "bull-call" || type === "bull-put";
}

export function spreadTypeLabel(type: SpreadType): string {
  return SPREAD_TYPES.find((spread) => spread.id === type)?.label ?? "This spread";
}

// ---------------------------------------------------------------------------
// Metrics computation
// ---------------------------------------------------------------------------

function spreadWidth(type: SpreadType, inputs: SpreadInputs): number {
  return longLegIsLower(type)
    ? inputs.shortStrike - inputs.longStrike
    : inputs.longStrike - inputs.shortStrike;
}

/**
 * Reject a vertical whose economics cannot exist, returning a human-readable
 * reason (or null when the inputs are coherent).
 */
export function validateSpreadInputs(type: SpreadType, inputs: SpreadInputs): string | null {
  const { longStrike, shortStrike, premium, lotSize } = inputs;
  if (
    !Number.isFinite(longStrike)
    || !Number.isFinite(shortStrike)
    || longStrike <= 0
    || shortStrike <= 0
  ) {
    return "Strikes must be finite positive numbers.";
  }

  if (!Number.isFinite(lotSize) || !Number.isInteger(lotSize) || lotSize <= 0) {
    return "Lot size must be a positive whole number.";
  }

  const longMustBeLower = longLegIsLower(type);
  if (longMustBeLower ? longStrike >= shortStrike : longStrike <= shortStrike) {
    const requiredOrder = longMustBeLower ? "below" : "above";
    return `${spreadTypeLabel(type)} requires the long strike ${requiredOrder} the short strike.`;
  }

  if (!Number.isFinite(premium)) {
    return "Net premium must be finite.";
  }

  const width = spreadWidth(type, inputs);
  const isDebit = isDebitSpread(type);
  if (isDebit && (premium <= 0 || premium > width)) {
    return "Debit must be positive and no greater than the strike width.";
  }

  if (!isDebit && (premium >= 0 || -premium > width)) {
    return "Credit must be negative and no greater than the strike width.";
  }

  return null;
}

function computeMetrics(type: SpreadType, inputs: SpreadInputs): SpreadMetrics {
  const { longStrike, shortStrike, premium, lotSize } = inputs;
  const width = spreadWidth(type, inputs);
  const isDebit = isDebitSpread(type);

  let maxProfit: number;
  let maxLoss: number;
  let breakeven: number;

  if (type === "bull-call") {
    maxProfit = (width - premium) * lotSize;
    maxLoss = premium * lotSize;
    breakeven = longStrike + premium;
  } else if (type === "bear-put") {
    maxProfit = (width - premium) * lotSize;
    maxLoss = premium * lotSize;
    breakeven = longStrike - premium;
  } else if (type === "bull-put") {
    const credit = -premium;
    maxProfit = credit * lotSize;
    maxLoss = (width - credit) * lotSize;
    breakeven = shortStrike - credit;
  } else {
    // bear-call
    const credit = -premium;
    maxProfit = credit * lotSize;
    maxLoss = (width - credit) * lotSize;
    breakeven = shortStrike + credit;
  }

  // Heuristic visual proxy only. Broker margin requires live contract and portfolio data.
  const illustrativeMarginProxy = isDebit ? maxLoss : maxLoss * 1.5;

  return {
    maxProfit,
    maxLoss,
    breakeven,
    netPremium: premium * lotSize,
    illustrativeMarginProxy,
    isDebit,
  };
}

function buildPayoff(type: SpreadType, inputs: SpreadInputs): PayoffPoint[] {
  const { longStrike, shortStrike, premium, lotSize } = inputs;
  const lowerStrike = longLegIsLower(type) ? longStrike : shortStrike;
  const width = spreadWidth(type, inputs);
  const step = width / 20;
  const prices = Array.from({ length: 41 }, (_, i) => lowerStrike - width * 0.5 + i * step);

  return prices.map((price) => {
    let pnl: number;
    if (type === "bull-call") {
      const longPnl = Math.max(price - longStrike, 0);
      const shortPnl = -Math.max(price - shortStrike, 0);
      pnl = (longPnl + shortPnl - premium) * lotSize;
    } else if (type === "bear-put") {
      const longPnl = Math.max(longStrike - price, 0);
      const shortPnl = -Math.max(shortStrike - price, 0);
      pnl = (longPnl + shortPnl - premium) * lotSize;
    } else if (type === "bull-put") {
      const credit = -premium;
      const shortPnl = -Math.max(shortStrike - price, 0);
      const longPnl = Math.max(longStrike - price, 0);
      pnl = (credit + shortPnl + longPnl) * lotSize;
    } else {
      // bear-call
      const credit = -premium;
      const shortPnl = -Math.max(price - shortStrike, 0);
      const longPnl = Math.max(price - longStrike, 0);
      pnl = (credit + shortPnl + longPnl) * lotSize;
    }
    return { price, pnl };
  });
}

/** Validate a vertical and, when coherent, return its metrics and payoff. */
export function analyseSpread(type: SpreadType, inputs: SpreadInputs): SpreadAnalysis {
  const error = validateSpreadInputs(type, inputs);
  if (error) {
    return { valid: false, error };
  }

  return {
    valid: true,
    metrics: computeMetrics(type, inputs),
    payoff: buildPayoff(type, inputs),
  };
}

// ---------------------------------------------------------------------------
// Builder bridge — recognise a vertical in a free-form leg table
// ---------------------------------------------------------------------------

/**
 * Structural shape of a builder leg. Deliberately not an import of the Lab
 * builder's `Leg` (which carries a UI id) so any leg source can be checked.
 */
export interface VerticalSpreadLeg {
  action: "BUY" | "SELL";
  optionType: "CE" | "PE";
  strike: number;
  lots: number;
  /** Per-unit premium for this leg. Always a positive cost, never signed. */
  premium: number;
}

export interface VerticalSpread {
  type: SpreadType;
  label: string;
  inputs: SpreadInputs;
}

/**
 * Outcome of checking a leg table for vertical-spread economics.
 *
 * `not-a-vertical` is the common case (one leg, a straddle, a condor, a ratio
 * spread) and carries no judgement — those shapes have their own economics and
 * this validator says nothing about them. `unpriced` is the freshly loaded
 * template, whose legs carry a zero premium until the operator types one.
 */
export type VerticalSpreadCheck =
  | { kind: "not-a-vertical" }
  | { kind: "unpriced"; spread: VerticalSpread }
  | { kind: "invalid"; spread: VerticalSpread; error: string }
  | { kind: "valid"; spread: VerticalSpread; metrics: SpreadMetrics; payoff: PayoffPoint[] };

/**
 * Classify a leg table as a two-leg vertical, or null when it is not one.
 *
 * A vertical is exactly two legs of the same option type, one bought and one
 * sold, in equal lots, at different strikes. The spread TYPE then follows from
 * the option type and the leg order — which is why the builder can never fail
 * the leg-order rule: it is classified, not asserted.
 *
 * `contractLotSize` is the exchange lot size for the underlying (NIFTY = 75
 * post-Nov-2024), so per-unit premiums scale to rupees the same way the
 * builder's own margin estimate does.
 */
export function asVerticalSpread(
  legs: readonly VerticalSpreadLeg[],
  contractLotSize: number,
): VerticalSpread | null {
  if (legs.length !== 2) return null;

  const long = legs.find((leg) => leg.action === "BUY");
  const short = legs.find((leg) => leg.action === "SELL");
  if (!long || !short) return null;                        // both bought or both sold
  if (long.optionType !== short.optionType) return null;   // straddle/strangle family
  if (long.lots !== short.lots) return null;               // ratio spread
  if (!Number.isFinite(long.strike) || !Number.isFinite(short.strike)) return null;
  if (long.strike === short.strike) return null;           // same strike — no width

  const longIsLower = long.strike < short.strike;
  const type: SpreadType = long.optionType === "CE"
    ? (longIsLower ? "bull-call" : "bear-call")
    : (longIsLower ? "bull-put" : "bear-put");

  return {
    type,
    label: spreadTypeLabel(type),
    inputs: {
      longStrike: long.strike,
      shortStrike: short.strike,
      premium: long.premium - short.premium,
      lotSize: long.lots * contractLotSize,
    },
  };
}

/**
 * Run the vertical-spread economics over a builder leg table.
 *
 * Returns `not-a-vertical` for every other shape rather than a failure — this
 * check adds a rule for one recognisable structure, it does not gate the
 * builder.
 */
export function analyseVerticalSpread(
  legs: readonly VerticalSpreadLeg[],
  contractLotSize: number,
): VerticalSpreadCheck {
  const spread = asVerticalSpread(legs, contractLotSize);
  if (!spread) return { kind: "not-a-vertical" };

  // A template lands with zero premiums; that is "not yet priced", not
  // "impossible". Only judge the economics once a premium has been typed.
  if (legs.every((leg) => leg.premium === 0)) {
    return { kind: "unpriced", spread };
  }

  const analysis = analyseSpread(spread.type, spread.inputs);
  return analysis.valid
    ? { kind: "valid", spread, metrics: analysis.metrics, payoff: analysis.payoff }
    : { kind: "invalid", spread, error: analysis.error };
}

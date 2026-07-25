/**
 * strategyTemplates — the single option-strategy template catalogue.
 *
 * Three catalogues used to exist and they contradicted each other:
 *   - `widgets/utility/StrategyTemplates` (12 cards, prose metadata)
 *   - `tools/StrategyBuilder/types.ts`    (7 entries, Lab builder pills)
 *   - `widgets/analysis/OptionChain/LegBuilder` (7 entries, the LIVE builder
 *     that places a real gated basket order)
 *
 * They disagreed on direction: a template keyed `straddle` bought both legs in
 * two of them and SOLD both legs in the third — the same label over a
 * defined-risk debit in one place and an undefined-risk credit in another,
 * one click away from a live basket. That class of bug cannot survive a shared
 * catalogue, so there is deliberately **no bare `straddle` / `strangle` id**:
 * every entry names its direction (`long-straddle` / `short-straddle`,
 * `long-strangle` / `short-strangle`). `lib/__tests__/strategyTemplates.test.ts`
 * is the regression guard.
 *
 * Other conflicts resolved here:
 *   - Butterfly is the 3-leg / lots:2 form (payoff-identical to the old 4-leg
 *     lots:1 shape, but it occupies 3 rather than 4 of the builder's 6 slots).
 *   - Iron condor legs are ordered by ascending strike offset (−2, −1, +1, +2),
 *     the shape both builders already used; the widget's call-wing-first order
 *     was cosmetic and is dropped.
 *
 * Offsets are in strike-gap units relative to ATM (0 = ATM, +1 = one gap above,
 * −2 = two gaps below) so each consumer resolves real strikes against whatever
 * underlying and ATM it has.
 *
 * Four entries (covered call, protective put, collar, calendar spread) carry
 * stock legs or multi-expiry legs. No options builder in the terminal can
 * represent those, and loading a degenerate approximation (a covered call
 * without its stock leg) would misstate the strategy's risk — so they are
 * reference-only, gated by `builderLegsFor`.
 */

import type { BuilderTemplateLeg } from "@/tools/StrategyBuilder/templateBridge";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Market outlook a strategy expresses. Drives the widget's filter tabs. */
export type StrategyOutlook = "bullish" | "bearish" | "neutral" | "volatile";

/** Leg direction — uppercase throughout, matching the builder/bridge contract. */
export type StrategyLegAction = "BUY" | "SELL";

/**
 * Leg instrument. `STOCK` exists only so the reference-only entries can state
 * their real composition; it is never loadable into an options builder.
 */
export type StrategyLegInstrument = "CE" | "PE" | "STOCK";

/** Coarse moneyness label, for display only — `strikeOffset` is authoritative. */
export type StrategyStrikeLabel = "ITM" | "ATM" | "OTM";

export interface StrategyTemplateLeg {
  action: StrategyLegAction;
  optionType: StrategyLegInstrument;
  /**
   * Strike offset from ATM in strike-gap units. Absent for stock legs (and any
   * leg a builder therefore cannot place).
   */
  strikeOffset?: number;
  lots: number;
  /** Display-only moneyness hint shown on the template cards. */
  strikeLabel?: StrategyStrikeLabel;
  /** Present only on multi-expiry (calendar) legs — makes the entry reference-only. */
  expiry?: "near" | "far";
}

export interface StrategyTemplate {
  /** Stable kebab-case id. Never a bare `straddle` / `strangle`. */
  id: string;
  name: string;
  /** Compact pill label for space-constrained builders. */
  shortName: string;
  outlook: StrategyOutlook;
  description: string;
  /** Prose payoff summary — deliberately not a computed number. */
  maxProfit: string;
  maxLoss: string;
  breakeven: string;
  legs: readonly StrategyTemplateLeg[];
}

// ---------------------------------------------------------------------------
// Loadability gate
// ---------------------------------------------------------------------------

/**
 * Map a template onto builder legs, or null when it cannot be represented.
 *
 * A template is loadable only when every leg is a single-expiry option with an
 * explicit strike offset. Stock legs and calendar (multi-expiry) legs have no
 * representation in an options builder, and a partial load would misstate risk.
 */
export function builderLegsFor(template: StrategyTemplate): BuilderTemplateLeg[] | null {
  const legs: BuilderTemplateLeg[] = [];
  for (const leg of template.legs) {
    if (
      leg.optionType === "STOCK"
      || leg.expiry !== undefined
      || leg.strikeOffset === undefined
      || !Number.isFinite(leg.strikeOffset)
    ) {
      return null;
    }
    legs.push({
      action: leg.action,
      optionType: leg.optionType,
      strikeOffset: leg.strikeOffset,
      lots: Math.max(1, leg.lots),
    });
  }
  return legs.length > 0 ? legs : null;
}

/** True when the template can be loaded into an options builder. */
export function isLoadable(template: StrategyTemplate): boolean {
  return builderLegsFor(template) !== null;
}

// ---------------------------------------------------------------------------
// The catalogue — 14 strategy concepts
// ---------------------------------------------------------------------------

export const STRATEGY_TEMPLATES: readonly StrategyTemplate[] = [
  {
    id: "long-call",
    name: "Long Call",
    shortName: "LC",
    outlook: "bullish",
    description: "Right to buy. Profits when price rises above breakeven.",
    maxProfit: "Unlimited",
    maxLoss: "Premium paid",
    breakeven: "Strike + Premium",
    legs: [{ action: "BUY", optionType: "CE", strikeOffset: 0, lots: 1, strikeLabel: "ATM" }],
  },
  {
    id: "long-put",
    name: "Long Put",
    shortName: "LP",
    outlook: "bearish",
    description: "Right to sell. Profits when price falls below breakeven.",
    maxProfit: "Strike − Premium",
    maxLoss: "Premium paid",
    breakeven: "Strike − Premium",
    legs: [{ action: "BUY", optionType: "PE", strikeOffset: 0, lots: 1, strikeLabel: "ATM" }],
  },
  {
    id: "bull-call-spread",
    name: "Bull Call Spread",
    shortName: "BCS",
    outlook: "bullish",
    description: "Capped profit, reduced cost vs long call. Moderately bullish.",
    maxProfit: "Width − Net debit",
    maxLoss: "Net debit",
    breakeven: "Long strike + Net debit",
    legs: [
      { action: "BUY",  optionType: "CE", strikeOffset: 0, lots: 1, strikeLabel: "ATM" },
      { action: "SELL", optionType: "CE", strikeOffset: 1, lots: 1, strikeLabel: "OTM" },
    ],
  },
  {
    id: "bear-put-spread",
    name: "Bear Put Spread",
    shortName: "BPS",
    outlook: "bearish",
    description: "Capped profit, reduced cost vs long put. Moderately bearish.",
    maxProfit: "Width − Net debit",
    maxLoss: "Net debit",
    breakeven: "Long strike − Net debit",
    legs: [
      { action: "BUY",  optionType: "PE", strikeOffset:  0, lots: 1, strikeLabel: "ATM" },
      { action: "SELL", optionType: "PE", strikeOffset: -1, lots: 1, strikeLabel: "OTM" },
    ],
  },
  {
    id: "long-straddle",
    name: "Long Straddle",
    shortName: "LSTR",
    outlook: "volatile",
    description: "Buys both ATM legs. Profits from a large move either way; the whole premium decays if price sits still.",
    maxProfit: "Unlimited",
    maxLoss: "Total premium paid",
    breakeven: "ATM ± Total premium",
    legs: [
      { action: "BUY", optionType: "CE", strikeOffset: 0, lots: 1, strikeLabel: "ATM" },
      { action: "BUY", optionType: "PE", strikeOffset: 0, lots: 1, strikeLabel: "ATM" },
    ],
  },
  {
    id: "short-straddle",
    name: "Short Straddle",
    shortName: "SSTR",
    outlook: "neutral",
    description: "Sells both ATM legs for theta decay. Undefined risk — a large move either way loses without limit.",
    maxProfit: "Total premium received",
    maxLoss: "Unlimited",
    breakeven: "ATM ± Total premium",
    legs: [
      { action: "SELL", optionType: "CE", strikeOffset: 0, lots: 1, strikeLabel: "ATM" },
      { action: "SELL", optionType: "PE", strikeOffset: 0, lots: 1, strikeLabel: "ATM" },
    ],
  },
  {
    id: "long-strangle",
    name: "Long Strangle",
    shortName: "LSTG",
    outlook: "volatile",
    description: "Cheaper than a long straddle. Needs a larger move to profit.",
    maxProfit: "Unlimited",
    maxLoss: "Total premium paid",
    breakeven: "Strikes ± Total premium",
    legs: [
      { action: "BUY", optionType: "CE", strikeOffset:  1, lots: 1, strikeLabel: "OTM" },
      { action: "BUY", optionType: "PE", strikeOffset: -1, lots: 1, strikeLabel: "OTM" },
    ],
  },
  {
    id: "short-strangle",
    name: "Short Strangle",
    shortName: "SSTG",
    outlook: "neutral",
    description: "Wider profit zone than a short straddle for less premium. Undefined risk on both wings.",
    maxProfit: "Total premium received",
    maxLoss: "Unlimited",
    breakeven: "Short strikes ± Total premium",
    legs: [
      { action: "SELL", optionType: "CE", strikeOffset:  1, lots: 1, strikeLabel: "OTM" },
      { action: "SELL", optionType: "PE", strikeOffset: -1, lots: 1, strikeLabel: "OTM" },
    ],
  },
  {
    id: "iron-condor",
    name: "Iron Condor",
    shortName: "IC",
    outlook: "neutral",
    description: "Profits when price stays within a range. Classic range trade.",
    maxProfit: "Net credit",
    maxLoss: "Width − Net credit",
    breakeven: "Short strikes ± Net credit",
    // Ordered by ascending strike offset — the shape both builders already used.
    legs: [
      { action: "BUY",  optionType: "PE", strikeOffset: -2, lots: 1, strikeLabel: "OTM" },
      { action: "SELL", optionType: "PE", strikeOffset: -1, lots: 1, strikeLabel: "OTM" },
      { action: "SELL", optionType: "CE", strikeOffset:  1, lots: 1, strikeLabel: "OTM" },
      { action: "BUY",  optionType: "CE", strikeOffset:  2, lots: 1, strikeLabel: "OTM" },
    ],
  },
  {
    id: "butterfly",
    name: "Butterfly",
    shortName: "BF",
    outlook: "neutral",
    description: "Max profit at the ATM strike at expiry. Tight range strategy.",
    maxProfit: "Width − Net debit",
    maxLoss: "Net debit",
    breakeven: "Wings ± Net debit",
    // 3 legs with a double-lot body — payoff-identical to two separate ATM
    // sells, but it leaves the builder's remaining leg slots free.
    legs: [
      { action: "BUY",  optionType: "CE", strikeOffset: -1, lots: 1, strikeLabel: "ITM" },
      { action: "SELL", optionType: "CE", strikeOffset:  0, lots: 2, strikeLabel: "ATM" },
      { action: "BUY",  optionType: "CE", strikeOffset:  1, lots: 1, strikeLabel: "OTM" },
    ],
  },
  {
    id: "covered-call",
    name: "Covered Call",
    shortName: "CC",
    outlook: "neutral",
    description: "Generates income on held stock. Caps upside above the strike.",
    maxProfit: "Strike − Entry + Premium",
    maxLoss: "Entry − Premium",
    breakeven: "Entry − Premium",
    legs: [
      { action: "BUY",  optionType: "STOCK", lots: 1 },
      { action: "SELL", optionType: "CE", lots: 1, strikeLabel: "OTM" },
    ],
  },
  {
    id: "protective-put",
    name: "Protective Put",
    shortName: "PP",
    outlook: "bullish",
    description: "Insurance for a long stock position. Limits downside loss.",
    maxProfit: "Unlimited",
    maxLoss: "Entry − Strike + Premium",
    breakeven: "Entry + Premium",
    legs: [
      { action: "BUY", optionType: "STOCK", lots: 1 },
      { action: "BUY", optionType: "PE", lots: 1, strikeLabel: "ATM" },
    ],
  },
  {
    id: "collar",
    name: "Collar",
    shortName: "COL",
    outlook: "neutral",
    description: "Protects gains on stock. Sacrifices upside for downside protection.",
    maxProfit: "Call strike − Entry + Net credit",
    maxLoss: "Entry − Put strike − Net credit",
    breakeven: "Entry + Net debit",
    legs: [
      { action: "BUY",  optionType: "STOCK", lots: 1 },
      { action: "BUY",  optionType: "PE", lots: 1, strikeLabel: "OTM" },
      { action: "SELL", optionType: "CE", lots: 1, strikeLabel: "OTM" },
    ],
  },
  {
    id: "calendar-spread",
    name: "Calendar Spread",
    shortName: "CAL",
    outlook: "neutral",
    description: "Exploits the time-decay difference between expiries. Low-directional.",
    maxProfit: "Time decay differential",
    maxLoss: "Net debit",
    breakeven: "Near strike ± Range",
    legs: [
      { action: "SELL", optionType: "CE", strikeOffset: 0, lots: 1, strikeLabel: "ATM", expiry: "near" },
      { action: "BUY",  optionType: "CE", strikeOffset: 0, lots: 1, strikeLabel: "ATM", expiry: "far"  },
    ],
  },
];

// ---------------------------------------------------------------------------
// Custom (build-your-own) pseudo-template
// ---------------------------------------------------------------------------

export const CUSTOM_TEMPLATE_ID = "custom";

/**
 * Not a strategy — the "clear the legs and build your own" affordance. It has
 * no legs, so `builderLegsFor` correctly reports it as not loadable; consumers
 * that offer it special-case the id before looking a template up.
 */
export const CUSTOM_TEMPLATE: StrategyTemplate = {
  id: CUSTOM_TEMPLATE_ID,
  name: "Custom",
  shortName: "CUST",
  outlook: "neutral",
  description: "Build your own from individual legs.",
  maxProfit: "—",
  maxLoss: "—",
  breakeven: "—",
  legs: [],
};

// ---------------------------------------------------------------------------
// Lookups
// ---------------------------------------------------------------------------

/** The 10 entries an options builder can represent, in catalogue order. */
export const LOADABLE_STRATEGY_TEMPLATES: readonly StrategyTemplate[] =
  STRATEGY_TEMPLATES.filter(isLoadable);

const BY_ID: ReadonlyMap<string, StrategyTemplate> = new Map(
  [...STRATEGY_TEMPLATES, CUSTOM_TEMPLATE].map((t) => [t.id, t]),
);

/** Look a template up by id (including `custom`); undefined when unknown. */
export function getStrategyTemplate(id: string): StrategyTemplate | undefined {
  return BY_ID.get(id);
}

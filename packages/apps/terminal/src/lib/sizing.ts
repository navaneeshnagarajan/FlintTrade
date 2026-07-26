/**
 * sizing.ts — the single position-sizing and risk/reward kernel.
 *
 * Every calculator surface in the terminal (Calculator → Sizing and
 * Calculator → Target/R:R, which absorbed the retired PositionSizing and
 * ProfitTarget widgets) sizes positions through these functions so that the
 * same inputs always produce the same recommendation. Before this module
 * there were three independent implementations that disagreed with each
 * other in two user-visible ways; both are resolved here.
 *
 * ## Decision 1 — over-budget positions are reported, never hidden
 *
 * Fixed-fractional sizing computes `floor(riskBudget / riskPerLot)`. When a
 * single lot already risks more than the operator's stated budget that floor
 * lands on zero, and the three legacy implementations disagreed:
 *
 *   - PositionSizing and ProfitTarget clamped with `max(1, …)` and recommended
 *     one lot **silently** — the operator asked to risk 1% and was handed a
 *     position risking 2% with nothing on screen to say so.
 *   - Calculator returned `null` and rendered its "enter a price" placeholder —
 *     a refusal with no explanation, indistinguishable from an empty form.
 *
 * Neither is acceptable, so {@link sizeFixedFractional} does both jobs: it
 * returns the clamped lot count *and* an `exceedsRisk` flag. Callers render
 * the number and, when the flag is set, an explicit warning naming the actual
 * rupee risk. Nothing is silently over-risked and nothing is silently refused.
 *
 * ## Decision 2 — risk/reward is always displayed reward-first
 *
 * Calculator rendered `1 : 2` (risk-first) while ProfitTarget rendered
 * `2.50 : 1` (reward-first) for the same quantity — two dockable panels side
 * by side showing the same number read two opposite ways. {@link formatRR} is
 * the single renderer and commits to reward-first (`2.00 : 1`), the industry
 * norm: the leading figure is always the multiple of risk being won.
 */

/** Which way a trade is facing. */
export type TradeSide = "BUY" | "SELL";

/** Half-Kelly — the default safety fraction applied to the full Kelly stake. */
export const HALF_KELLY = 0.5;

/** True when `n` is a real, usable, strictly positive number. */
function isPositive(n: number): boolean {
  return Number.isFinite(n) && n > 0;
}

/**
 * Rupee risk budget for a single trade.
 *
 * @param capital - Account capital in rupees.
 * @param riskPct - Percentage of capital to risk (2 means 2%, not 0.02).
 * @returns The rupee amount that may be lost, or 0 for unusable inputs.
 */
export function riskBudget(capital: number, riskPct: number): number {
  if (!isPositive(capital) || !isPositive(riskPct)) return 0;
  return (capital * riskPct) / 100;
}

/** Inputs to {@link sizeFixedFractional}. */
export interface FixedFractionalInput {
  /** Account capital in rupees. */
  capital: number;
  /** Percentage of capital to risk on this trade (2 means 2%). */
  riskPct: number;
  /** Distance from entry to stop loss, in price points. */
  stopDistance: number;
  /** Contracts per lot. Pass 1 to size in shares rather than lots. */
  lotSize: number;
}

/** Result of {@link sizeFixedFractional}. */
export interface FixedFractionalResult {
  /** Recommended lot count. Never below 1 — see `exceedsRisk`. */
  lots: number;
  /** `lots × lotSize` — the tradeable quantity. */
  units: number;
  /** Rupees actually at risk if the stop is hit: `stopDistance × units`. */
  rupeeRisk: number;
  /** `rupeeRisk` as a percentage of capital (2 means 2%). */
  capitalAtRiskPct: number;
  /**
   * True when a single lot already risks more than the budget, i.e. the
   * unclamped size was zero and `lots` has been floored up to 1.
   *
   * When this is set the caller MUST surface a warning alongside the lot
   * count: `rupeeRisk` exceeds `riskBudget(capital, riskPct)` and the
   * recommendation therefore breaches the operator's own stated limit.
   */
  exceedsRisk: boolean;
}

/**
 * Size a position by fixed-fractional risk.
 *
 * Risks `riskPct` of `capital`, divided by the rupee risk of one lot. The
 * result is floored to whole lots and then clamped to a minimum of one, with
 * `exceedsRisk` recording whether that clamp fired.
 *
 * @param input - Capital, risk percentage, stop distance and lot size.
 * @returns The sizing result, or `null` if any input is unusable.
 */
export function sizeFixedFractional(
  input: FixedFractionalInput,
): FixedFractionalResult | null {
  const { capital, riskPct, stopDistance, lotSize } = input;
  if (!isPositive(capital) || !isPositive(riskPct)) return null;
  if (!isPositive(stopDistance) || !isPositive(lotSize)) return null;

  const budget = riskBudget(capital, riskPct);
  const riskPerLot = stopDistance * lotSize;
  if (!isPositive(riskPerLot)) return null;

  const affordableLots = Math.floor(budget / riskPerLot);
  const exceedsRisk = affordableLots < 1;
  const lots = Math.max(1, affordableLots);
  const units = lots * lotSize;
  const rupeeRisk = riskPerLot * lots;

  return {
    lots,
    units,
    rupeeRisk,
    capitalAtRiskPct: (rupeeRisk / capital) * 100,
    exceedsRisk,
  };
}

/** Inputs to {@link kellyFraction}. */
export interface KellyInput {
  /** Historical win rate as a percentage (55 means 55%). */
  winRate: number;
  /** Reward-to-risk multiple of the average trade (2 means 2R). */
  rewardRisk: number;
  /**
   * Safety fraction applied to the full Kelly stake. Defaults to
   * {@link HALF_KELLY}, because full Kelly is far too aggressive in practice.
   */
  fraction?: number;
}

/**
 * Kelly criterion stake, scaled by a safety fraction (half-Kelly by default).
 *
 * Full Kelly is `(p × b − q) / b` for win probability `p`, loss probability
 * `q` and reward-to-risk `b`. Negative edges clamp to zero — never stake on a
 * losing system. Win rates above 100% are clamped to 100%, so a mistyped
 * input cannot inflate the recommended stake.
 *
 * @param input - Win rate, reward-to-risk multiple and optional safety fraction.
 * @returns A fraction of capital between 0 and 1. Multiply by 100 for a percentage.
 */
export function kellyFraction({
  winRate,
  rewardRisk,
  fraction = HALF_KELLY,
}: KellyInput): number {
  if (!isPositive(winRate) || !isPositive(rewardRisk)) return 0;
  if (!isPositive(fraction)) return 0;

  const p = Math.min(winRate, 100) / 100;
  const q = 1 - p;
  const full = (p * rewardRisk - q) / rewardRisk;
  return Math.max(0, full) * fraction;
}

/**
 * Reward-to-risk multiple of a trade.
 *
 * @param entry - Entry price.
 * @param stop - Stop-loss price.
 * @param target - Target price.
 * @returns `|target − entry| / |entry − stop|`, or `null` when the stop sits
 *   on the entry (no risk to measure against) or an input is unusable.
 */
export function rrRatio(entry: number, stop: number, target: number): number | null {
  if (!Number.isFinite(entry) || !Number.isFinite(stop) || !Number.isFinite(target)) {
    return null;
  }
  const risk = Math.abs(entry - stop);
  if (!isPositive(risk)) return null;
  return Math.abs(target - entry) / risk;
}

/**
 * Win rate needed to break even at a given reward-to-risk multiple.
 *
 * @param rr - Reward-to-risk multiple (2 means 2R).
 * @returns The breakeven win rate as a percentage. Unusable or non-positive
 *   multiples return 100% — with no reward, every trade must win.
 */
export function breakevenWinRate(rr: number): number {
  if (!isPositive(rr)) return 100;
  return (1 / (1 + rr)) * 100;
}

/**
 * Target price implied by a stop distance and a reward-to-risk multiple.
 *
 * @param entry - Entry price.
 * @param stopDistance - Distance from entry to stop, in price points.
 * @param rr - Reward-to-risk multiple to aim for.
 * @param side - Trade direction; SELL targets sit below the entry.
 * @returns The target price.
 */
export function deriveTarget(
  entry: number,
  stopDistance: number,
  rr: number,
  side: TradeSide,
): number {
  const move = stopDistance * rr;
  return side === "SELL" ? entry - move : entry + move;
}

/**
 * Render a reward-to-risk multiple in the terminal's standard notation.
 *
 * Always reward-first with two decimals: 2.5 renders as `2.50 : 1`, meaning
 * two and a half rupees won for every rupee risked.
 *
 * @param rr - Reward-to-risk multiple.
 * @returns The formatted ratio, or an em dash when there is nothing to show.
 */
export function formatRR(rr: number): string {
  if (!Number.isFinite(rr)) return "—";
  return `${rr.toFixed(2)} : 1`;
}

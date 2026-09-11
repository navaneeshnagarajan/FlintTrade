/**
 * Explore sample-chain option LTP.
 *
 * This is the same deterministic formula `services/api.ts` uses for the
 * Explore `optionchain` fallback (`makeMockOptionChain`). Options Builder
 * seeds Long Call from it so Explore payoff is an illustrative ATM CE, not
 * an invented second premium model.
 */

export type SampleOptionType = "CE" | "PE";

/**
 * Per-unit last price for a sample-chain option at `strike`.
 *
 * Time value decays with distance from the ATM grid; intrinsic is taken
 * from `spot` so ATM calls and puts share the same illustrative premium.
 */
export function sampleChainOptionLtp(
  spot: number,
  strike: number,
  step: number,
  optionType: SampleOptionType,
): number {
  const safeStep = step > 0 && Number.isFinite(step) ? step : 50;
  const safeSpot = Number.isFinite(spot) ? spot : 0;
  const safeStrike = Number.isFinite(strike) ? strike : safeSpot;
  const atm = Math.round(safeSpot / safeStep) * safeStep;
  const offset = Math.round((safeStrike - atm) / safeStep);
  const distance = Math.abs(offset);
  const timeValue = safeStep * 0.9 * Math.exp(-distance / 5);
  const intrinsic = optionType === "CE" ? safeSpot - safeStrike : safeStrike - safeSpot;
  return Math.round((Math.max(intrinsic, 0) + timeValue) * 100) / 100;
}

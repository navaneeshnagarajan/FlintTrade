/**
 * Realistic NIFTY 24000 ATM straddle P&L sample data.
 * ATM straddle = BUY 24000 CE + BUY 24000 PE.
 * Call premium: 185, Put premium: 178 (total debit: 363 points).
 * Break-even: 23637 (low) and 24363 (high).
 * Max loss: -363 × 75 = -27,225 (if NIFTY expires exactly at 24000).
 * P&L curve spans spot from 23000 to 25000, step 50.
 *
 * The curve shape is classic V (long straddle):
 *   - Positive P&L at both extremes
 *   - Maximum loss at ATM (total premium paid)
 */

import type { StraddlePnLData, StraddlePnLPoint, StraddleLeg } from "@/types/api";

const ATM_STRIKE = 24000;
const CALL_PREMIUM = 185;
const PUT_PREMIUM = 178;
const TOTAL_PREMIUM = CALL_PREMIUM + PUT_PREMIUM; // 363
const LOT_SIZE = 75;

// Break-even points
const BE_LOW = ATM_STRIKE - TOTAL_PREMIUM;   // 23637
const BE_HIGH = ATM_STRIKE + TOTAL_PREMIUM;  // 24363

// Spot range for P&L curve
const SPOT_MIN = 23000;
const SPOT_MAX = 25000;
const SPOT_STEP = 50;

function computePnL(spot: number): number {
  // Long call P&L: max(spot - strike, 0) - call_premium
  const callPnL = Math.max(spot - ATM_STRIKE, 0) - CALL_PREMIUM;
  // Long put P&L: max(strike - spot, 0) - put_premium
  const putPnL = Math.max(ATM_STRIKE - spot, 0) - PUT_PREMIUM;
  // Total per share; multiply by lot for real P&L but widget shows per-lot
  return parseFloat(((callPnL + putPnL) * LOT_SIZE).toFixed(2));
}

const curve: StraddlePnLPoint[] = [];
for (let spot = SPOT_MIN; spot <= SPOT_MAX; spot += SPOT_STEP) {
  curve.push({ spot_price: spot, pnl: computePnL(spot) });
}

// Base straddle legs
const legs: StraddleLeg[] = [
  { strike: ATM_STRIKE, type: "CE", action: "BUY", premium: CALL_PREMIUM, lots: 1 },
  { strike: ATM_STRIKE, type: "PE", action: "BUY", premium: PUT_PREMIUM,  lots: 1 },
];

export const SAMPLE_STRADDLE_PNL_DATA: StraddlePnLData = {
  underlying: "NIFTY",
  atm_strike: ATM_STRIKE,
  call_premium: CALL_PREMIUM,
  put_premium: PUT_PREMIUM,
  break_even_low: BE_LOW,
  break_even_high: BE_HIGH,
  max_loss: -(TOTAL_PREMIUM * LOT_SIZE),   // -27225
  curve,
  legs,
};

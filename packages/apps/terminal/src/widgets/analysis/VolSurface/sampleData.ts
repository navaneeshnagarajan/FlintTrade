/**
 * Realistic NIFTY volatility surface sample data.
 * Three expiries: 3 DTE (weekly), 10 DTE (next weekly), 30 DTE (monthly).
 * 11 strikes from 23000 to 25000, step 200.
 * IV shows a classic smile: wings elevated, ATM trough ~12-15%.
 * Near-term IV is higher (term-structure inversion typical in India).
 */

import type { VolSurfaceData } from "@/types/api";

const SPOT = 24050;
const ATM = 24000;

const STRIKES = [23000, 23200, 23400, 23600, 23800, 24000, 24200, 24400, 24600, 24800, 25000];
const EXPIRIES = ["2026-03-27", "2026-04-03", "2026-04-24"];
const DTES = [3, 10, 30];

// ATM base IV per DTE — India term structure is typically inverted near expiry
const ATM_BASE_IV: Record<number, number> = {
  3: 16.5,   // short-dated IV elevated (gamma risk)
  10: 14.2,  // intermediate
  30: 12.8,  // monthly relatively lower
};

// Smile shape: IV(strike) = atm_iv + a × |moneyness|^b + put_skew × (ATM - strike)
// put_skew: OTM puts have higher IV (negative skew)
function smileIV(strike: number, dte: number): number {
  const atmIV = ATM_BASE_IV[dte] ?? 13.0;
  const moneyness = (strike - ATM) / ATM;                // signed
  const smile = 18.0 * moneyness ** 2;                   // symmetric curvature
  const skew = -3.5 * moneyness;                         // put skew: lower strikes → higher IV
  // Near-term smile is steeper
  const dteFactor = dte <= 5 ? 1.4 : dte <= 15 ? 1.1 : 1.0;
  return Math.max(8.0, (atmIV + smile + skew) * dteFactor);
}

// iv_matrix shape: [n_expiries][n_strikes] — outer array indexed by expiry
const ivMatrix: number[][] = DTES.map((dte) =>
  STRIKES.map((strike) => parseFloat(smileIV(strike, dte).toFixed(2))),
);

export const SAMPLE_VOL_SURFACE_DATA: VolSurfaceData = {
  underlying: "NIFTY",
  spot_price: SPOT,
  strikes: STRIKES,
  expiries: EXPIRIES,
  days_to_expiry: DTES,
  iv_matrix: ivMatrix,
  atm_strike: ATM,
};

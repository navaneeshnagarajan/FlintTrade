/**
 * Sample gamma density surface for demo/disconnected mode.
 * Mirrors the backend gamma_density calculate output shape.
 */

import type { GammaDensityData } from "@/types/api";

function buildSampleStrikes(): GammaDensityData["strikes"] {
  const spot = 24000;
  const step = 100;
  const count = 8;
  const strikes: GammaDensityData["strikes"] = [];
  for (let i = -count; i <= count; i++) {
    const k = spot + i * step;
    const dist = Math.abs(i);
    const oi = Math.max(1000, 50000 - dist * 4500);
    // Gamma density peaks at ATM and decays outward; intraday sharper than expiry.
    const expiry = Math.max(0, 900 - dist * dist * 12);
    const intraday = Math.max(0, 1600 - dist * dist * 24);
    strikes.push({
      strike: k,
      ce_oi: oi,
      pe_oi: oi,
      iv: 15 + dist * 0.5,
      density_intraday: intraday,
      density_expiry: expiry,
    });
  }
  return strikes;
}

export const SAMPLE_GAMMA_DENSITY: GammaDensityData = {
  underlying: "NIFTY",
  exchange: "NFO",
  spot_price: 24000,
  atm_strike: 24000,
  atm_iv: 15.25,
  dte_days: 7,
  peak_intraday_strike: 24000,
  peak_expiry_strike: 24000,
  intraday_band: {
    sigma_move: 191.5,
    one_sigma_low: 23808.5,
    one_sigma_high: 24191.5,
    two_sigma_low: 23617,
    two_sigma_high: 24383,
  },
  expiry_band: {
    sigma_move: 506.8,
    one_sigma_low: 23493.2,
    one_sigma_high: 24506.8,
    two_sigma_low: 22986.4,
    two_sigma_high: 25013.6,
  },
  strikes: buildSampleStrikes(),
};

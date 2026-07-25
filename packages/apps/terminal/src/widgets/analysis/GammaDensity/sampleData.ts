/**
 * Sample dealer-gamma payloads for demo/disconnected mode.
 *
 * Two shapes, one instrument: the density surface (`/api/v1/gammadensity`)
 * and the gamma-exposure decomposition (`/api/v1/gex`). The backend builds
 * both from the SAME option-chain snapshot, so the samples are kept centred on
 * the same NIFTY spot rather than drifting apart.
 *
 * Both are fabricated. Every render path that reaches them must carry the
 * "Demo data" affordance — the widget's provenance check is fail-closed.
 */

import type { GEXData, GammaDensityData } from "@/types/api";

const SAMPLE_SPOT = 24000;

function buildSampleStrikes(): GammaDensityData["strikes"] {
  const spot = SAMPLE_SPOT;
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
  spot_price: SAMPLE_SPOT,
  atm_strike: SAMPLE_SPOT,
  atm_iv: 15.25,
  dte_days: 7,
  peak_intraday_strike: SAMPLE_SPOT,
  peak_expiry_strike: SAMPLE_SPOT,
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

// ---------------------------------------------------------------------------
// Gamma exposure (the retired GEX widget's sample, absorbed by merge 2.3)
// ---------------------------------------------------------------------------

/**
 * Realistic NIFTY GEX sample. 21 strikes from 23000 to 25000, step 100.
 * GEX values are in absolute units (delta-adjusted notional):
 * real GEX = gamma × OI × spot² × lot_size / 100, scaled here to plausible
 * magnitudes rather than computed from a Black-Scholes chain.
 * Call GEX: positive (dealers long gamma on calls → stabilising above ATM).
 * Put GEX: negative (dealers short gamma on puts → destabilising below ATM).
 */
const GEX_ATM = 24000;
const GEX_LOT = 75; // NIFTY lot size

function callGEX(strike: number): number {
  const dist = Math.abs(strike - GEX_ATM) / 500;
  // Peaks at ATM, decays outward; calls heavier slightly OTM upside.
  const base = 420 * Math.exp(-0.9 * dist * dist);
  const skew = strike <= GEX_ATM ? 0.65 : 1.0; // call sellers heavier on upside
  return Math.round(base * skew * GEX_LOT);
}

function putGEX(strike: number): number {
  const dist = Math.abs(strike - GEX_ATM) / 500;
  // Puts heavier on the downside — classic put skew.
  const base = 380 * Math.exp(-0.75 * dist * dist);
  const skew = strike >= GEX_ATM ? 0.70 : 1.15;
  return -Math.round(base * skew * GEX_LOT);
}

const RAW_STRIKES = [
  23000, 23100, 23200, 23300, 23400, 23500, 23600, 23700, 23800, 23900,
  24000, 24100, 24200, 24300, 24400, 24500, 24600, 24700, 24800, 24900, 25000,
];

const gexStrikes = RAW_STRIKES.map((strike) => {
  const cg = callGEX(strike);
  const pg = putGEX(strike);
  return {
    strike,
    call_gex: cg,
    put_gex: pg,
    net_gex: cg + pg,
    // Realistic OI in lots (CE heavier above ATM, PE heavier below ATM).
    call_oi: Math.round(
      (strike > GEX_ATM ? 180000 : 80000) * Math.exp(-0.5 * ((strike - GEX_ATM) / 700) ** 2),
    ),
    put_oi: Math.round(
      (strike < GEX_ATM ? 175000 : 75000) * Math.exp(-0.5 * ((strike - GEX_ATM) / 650) ** 2),
    ),
  };
});

const totalCallGEX = gexStrikes.reduce((s, r) => s + r.call_gex, 0);
const totalPutGEX = gexStrikes.reduce((s, r) => s + r.put_gex, 0);

export const SAMPLE_GEX_DATA: GEXData = {
  underlying: "NIFTY",
  spot_price: SAMPLE_SPOT,
  atm_strike: GEX_ATM,
  strikes: gexStrikes,
  // Always null — the server returns `gamma_flip_strike: None` unconditionally
  // (analysis_routes.py: a true flip level needs the whole chain repriced over
  // a spot sweep, which the endpoint does not do). The sample mirrors the real
  // response rather than inventing a level the backend cannot produce.
  gamma_flip_strike: null,
  dealer_zone: "Long Gamma", // positive net GEX → dealers stabilise
  total_call_gex: totalCallGEX,
  total_put_gex: totalPutGEX,
  net_gex: totalCallGEX + totalPutGEX,
};

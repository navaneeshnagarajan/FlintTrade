/**
 * Realistic NIFTY GEX sample data for development and explore mode.
 * NIFTY spot ~24,050. 21 strikes from 23000 to 25000, step 100.
 * GEX values are in absolute units (delta-adjusted notional).
 * Call GEX: positive (dealers long gamma on calls → stabilising above ATM)
 * Put GEX: negative (dealers short gamma on puts → destabilising below ATM)
 * Net GEX flips from positive to negative around 23700 (gamma flip).
 */

import type { GEXData } from "@/types/api";

// Helper: approximate GEX magnitude with a smile shape centred on ATM
// Real GEX = gamma × OI × spot² × lot_size / 100
// Here we produce plausible scaled values (in millions of delta-adjusted ₹).
const SPOT = 24050;
const ATM = 24000;
const LOT = 75; // NIFTY lot size

function callGEX(strike: number): number {
  const dist = Math.abs(strike - ATM) / 500;
  // Peaks at ATM, decays outward; calls heavier slightly OTM upside
  const base = 420 * Math.exp(-0.9 * dist * dist);
  const skew = strike <= ATM ? 0.65 : 1.0; // call sellers heavier on upside
  return Math.round(base * skew * LOT);
}

function putGEX(strike: number): number {
  const dist = Math.abs(strike - ATM) / 500;
  // Puts heavier on the downside — classic put skew
  const base = 380 * Math.exp(-0.75 * dist * dist);
  const skew = strike >= ATM ? 0.70 : 1.15;
  return -Math.round(base * skew * LOT);
}

const RAW_STRIKES = [
  23000, 23100, 23200, 23300, 23400, 23500, 23600, 23700, 23800, 23900,
  24000, 24100, 24200, 24300, 24400, 24500, 24600, 24700, 24800, 24900, 25000,
];

const strikes = RAW_STRIKES.map((strike) => {
  const cg = callGEX(strike);
  const pg = putGEX(strike);
  return {
    strike,
    call_gex: cg,
    put_gex: pg,
    net_gex: cg + pg,
    // Realistic OI in lots (CE heavier above ATM, PE heavier below ATM)
    call_oi: Math.round(
      (strike > ATM ? 180000 : 80000) * Math.exp(-0.5 * ((strike - ATM) / 700) ** 2),
    ),
    put_oi: Math.round(
      (strike < ATM ? 175000 : 75000) * Math.exp(-0.5 * ((strike - ATM) / 650) ** 2),
    ),
  };
});

const totalCallGEX = strikes.reduce((s, r) => s + r.call_gex, 0);
const totalPutGEX = strikes.reduce((s, r) => s + r.put_gex, 0);

// Gamma flip: the strike where net GEX first crosses zero going downward
// Net GEX is positive near ATM and turns negative at 23700
const GAMMA_FLIP = 23700;

export const SAMPLE_GEX_DATA: GEXData = {
  underlying: "NIFTY",
  spot_price: SPOT,
  atm_strike: ATM,
  strikes,
  gamma_flip_strike: GAMMA_FLIP,
  dealer_zone: "Long Gamma",          // positive net GEX → dealers stabilise
  total_call_gex: totalCallGEX,
  total_put_gex: totalPutGEX,
  net_gex: totalCallGEX + totalPutGEX,
};

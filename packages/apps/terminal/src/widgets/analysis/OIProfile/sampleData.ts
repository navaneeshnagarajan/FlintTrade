/**
 * Realistic NIFTY OI Profile sample data for 2026-03-27 expiry.
 * 21 strikes from 23000 to 25000, step 100.
 * CE OI heaviest at 24500 (resistance) and 24000 (ATM).
 * PE OI heaviest at 23500 (support) and 24000 (ATM).
 * Max pain: 24000 (equal pain for CE and PE writers).
 * PCR: 1.18 (slightly bullish, PE OI > CE OI overall).
 */

import type { OIProfileData, OIProfileStrike } from "@/types/api";

const SPOT = 24050;
const ATM = 24000;
const EXPIRY = "2026-03-27";

// CE OI profile: strong at 24500 (big resistance), 24000 (ATM)
// PE OI profile: strong at 23500 (strong support), 24000 (ATM hedge)
// OI in lots (1 lot = 75 shares; multiply by lot size for contracts basis)
const STRIKE_LIST = [
  23000, 23100, 23200, 23300, 23400, 23500, 23600, 23700, 23800, 23900,
  24000, 24100, 24200, 24300, 24400, 24500, 24600, 24700, 24800, 24900, 25000,
];

// CE OI peaks: 24500 (max resistance), 24000 (ATM), 25000 (far OTM)
const CE_OI_BASE: Record<number, number> = {
  23000: 28000,
  23100: 18000,
  23200: 15000,
  23300: 12000,
  23400: 22000,
  23500: 35000,  // notable OTM CE
  23600: 25000,
  23700: 32000,
  23800: 48000,
  23900: 65000,
  24000: 142000, // ATM — large CE OI (writers)
  24100: 88000,
  24200: 72000,
  24300: 95000,
  24400: 105000,
  24500: 198000, // BIGGEST resistance — max CE OI
  24600: 82000,
  24700: 65000,
  24800: 55000,
  24900: 40000,
  25000: 110000, // round number far OTM
};

// PE OI peaks: 23500 (strong support), 24000 (ATM), 23000 (far OTM)
const PE_OI_BASE: Record<number, number> = {
  23000: 95000,  // round number support
  23100: 42000,
  23200: 38000,
  23300: 55000,
  23400: 72000,
  23500: 168000, // BIGGEST support — max PE OI
  23600: 88000,
  23700: 78000,
  23800: 105000,
  23900: 118000,
  24000: 155000, // ATM — large PE OI (hedge buyers)
  24100: 68000,
  24200: 45000,
  24300: 35000,
  24400: 28000,
  24500: 32000,
  24600: 18000,
  24700: 12000,
  24800: 9000,
  24900: 7000,
  25000: 5000,
};

// OI change (vs previous session): generally mixed; big changes at key strikes
const CE_OI_CHANGE: Record<number, number> = {
  23000: -1200,  23100: -500,   23200: 800,    23300: 1200,   23400: -2000,
  23500: 4500,   23600: -1800,  23700: 3200,   23800: 5500,   23900: 8200,
  24000: 12500,  24100: -3200,  24200: 2800,   24300: 6800,   24400: 9500,
  24500: 18000,  24600: -4200,  24700: 2100,   24800: -1800,  24900: -900,
  25000: 3500,
};

const PE_OI_CHANGE: Record<number, number> = {
  23000: 5500,   23100: 1200,   23200: -800,   23300: 2200,   23400: 4800,
  23500: 15200,  23600: 3500,   23700: -2200,  23800: 7200,   23900: 9800,
  24000: 11500,  24100: -1500,  24200: -2800,  24300: -1200,  24400: -3500,
  24500: 1800,   24600: -800,   24700: -500,   24800: -300,   24900: -200,
  25000: -100,
};

const strikes: OIProfileStrike[] = STRIKE_LIST.map((strike) => ({
  strike,
  ce_oi: CE_OI_BASE[strike] ?? 10000,
  pe_oi: PE_OI_BASE[strike] ?? 10000,
  ce_oi_change: CE_OI_CHANGE[strike] ?? 0,
  pe_oi_change: PE_OI_CHANGE[strike] ?? 0,
}));

const totalCeOI = strikes.reduce((s, r) => s + r.ce_oi, 0);
const totalPeOI = strikes.reduce((s, r) => s + r.pe_oi, 0);

export const SAMPLE_OI_PROFILE_DATA: OIProfileData = {
  underlying: "NIFTY",
  expiry: EXPIRY,
  spot_price: SPOT,
  atm_strike: ATM,
  max_pain_strike: 24000,
  strikes,
  total_ce_oi: totalCeOI,
  total_pe_oi: totalPeOI,
  pcr: parseFloat((totalPeOI / totalCeOI).toFixed(2)),
};

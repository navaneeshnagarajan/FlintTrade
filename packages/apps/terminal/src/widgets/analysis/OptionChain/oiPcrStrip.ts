/**
 * OI profile + PCR strip model for the Option Chain (FT-TRADE-012).
 *
 * The strip describes the selected expiry/symbol only. Missing OI stays
 * missing — it is never coerced to zero. An empty expiry is an honest
 * empty (no bars, no PCR), not a row of zeros painted as data.
 */

import type { RawOptionRow, StrikeRow } from "./types";

export type OiPcrStripKind = "empty-expiry" | "empty-oi" | "loading" | "profile";

export interface OiProfileBar {
  strike: number;
  /** Call OI in contracts, or `null` when the chain did not report it. */
  callOi: number | null;
  /** Put OI in contracts, or `null` when the chain did not report it. */
  putOi: number | null;
}

export interface OiPcrStripModel {
  kind: OiPcrStripKind;
  symbol: string;
  expiry: string | null;
  sample: boolean;
  /** PCR only when the strip is a real profile. Never 0.00-as-empty. */
  pcr: number | null;
  bars: OiProfileBar[];
  emptyReason: string | null;
}

export interface OiPcrStripInput {
  symbol: string;
  expiry: string | null;
  expiries: readonly string[];
  strikes: readonly StrikeRow[];
  pcr: number | null;
  isExplore: boolean;
  loading?: boolean;
}

/** Open interest is a non-negative whole number of contracts. Missing is not zero. */
export function optionOpenInterest(row: RawOptionRow | null | undefined): number | null {
  const raw = row?.oi ?? row?.open_interest;
  if (typeof raw !== "number" || !Number.isFinite(raw) || !Number.isInteger(raw) || raw < 0) {
    return null;
  }
  return raw;
}

export function strikeHasPositiveOi(row: StrikeRow): boolean {
  const callOi = optionOpenInterest(row.call);
  const putOi = optionOpenInterest(row.put);
  return (callOi !== null && callOi > 0) || (putOi !== null && putOi > 0);
}

function emptyModel(
  input: OiPcrStripInput,
  kind: Exclude<OiPcrStripKind, "profile">,
  emptyReason: string | null,
): OiPcrStripModel {
  return {
    kind,
    symbol: input.symbol,
    expiry: input.expiry,
    sample: input.isExplore,
    pcr: null,
    bars: [],
    emptyReason,
  };
}

/**
 * Build the Option Chain OI profile + PCR strip from the same chain the
 * table already shows. Explore is always Sample; the model never invents
 * live OI or fills an empty expiry with zeros.
 */
export function buildOiPcrStripModel(input: OiPcrStripInput): OiPcrStripModel {
  const hasExpiries = input.expiries.some((expiry) => expiry.trim().length > 0);
  const expiry = typeof input.expiry === "string" && input.expiry.trim().length > 0
    ? input.expiry
    : null;

  if (!hasExpiries) {
    return emptyModel(input, "empty-expiry", "No expiries for this symbol");
  }
  if (!expiry) {
    return emptyModel(input, "empty-expiry", "Select an expiry to load chain");
  }
  if (input.loading && input.strikes.length === 0) {
    return emptyModel(input, "loading", null);
  }

  const bars: OiProfileBar[] = input.strikes.map((row) => ({
    strike: row.strike,
    callOi: optionOpenInterest(row.call),
    putOi: optionOpenInterest(row.put),
  }));
  const hasPositiveOi = bars.some((bar) => (
    (bar.callOi !== null && bar.callOi > 0) || (bar.putOi !== null && bar.putOi > 0)
  ));
  if (!hasPositiveOi) {
    return emptyModel(input, "empty-oi", "No OI for this expiry");
  }

  return {
    kind: "profile",
    symbol: input.symbol,
    expiry,
    sample: input.isExplore,
    pcr: input.pcr,
    bars,
    emptyReason: null,
  };
}

export function pcrLean(pcr: number): "Bullish" | "Bearish" | "Neutral" {
  if (pcr >= 1.2) return "Bullish";
  if (pcr <= 0.8) return "Bearish";
  return "Neutral";
}

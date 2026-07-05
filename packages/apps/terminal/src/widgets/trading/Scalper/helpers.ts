// ─── Scalper — pure helper functions ──────────────────────────────────────────

import { buildCompactOptionSymbol } from "@/lib/optionSymbols";

export const fmt2 = (n: number | null | undefined): string =>
  n == null || isNaN(n) ? "—" : Number(n).toFixed(2);

export const fmtInt = (n: number | null | undefined): string =>
  n == null || isNaN(n) ? "—" : Math.round(n).toLocaleString("en-IN");

export function roundToStrike(price: number, step: number): number {
  return Math.round(price / step) * step;
}

export function buildOptionSymbol(
  base: string,
  expiry: string,
  strike: number,
  type: "CE" | "PE",
): string | null {
  return buildCompactOptionSymbol(base, expiry, strike, type);
}

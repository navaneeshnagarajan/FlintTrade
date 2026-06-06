/**
 * greeksHeatmapTransform — pure helpers that turn live OpenAlgo option chains
 * into the `ExpiryRow[]` grid the GreeksHeatmap widget renders.
 *
 * Kept separate from the widget so the chain→grid maths (strike alignment, ATM
 * classification, days-to-expiry) is unit-tested without a broker connection.
 *
 * Greeks are taken from the CALL (CE) leg — the widget shows a single greek per
 * (strike, expiry) cell, and call greeks (delta ~0→1) match the existing scale.
 */

import type { ChainEntry, RawOptionChain, RawOptionRow } from "@/widgets/analysis/OptionChain/types";

export type Moneyness = "OTM" | "ATM" | "ITM";

export interface HeatCell {
  strike: number;
  moneyness: Moneyness;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}

export interface ExpiryRow {
  expiry: string;
  label: string;
  dte: number;
  cells: HeatCell[];
}

const MONTHS: Record<string, number> = {
  JAN: 0, FEB: 1, MAR: 2, APR: 3, MAY: 4, JUN: 5,
  JUL: 6, AUG: 7, SEP: 8, OCT: 9, NOV: 10, DEC: 11,
};

/** Parse an expiry string to epoch ms, or null when the format is unknown.
 *  Handles "DD-MON-YY", "DD-MON-YYYY" and ISO "YYYY-MM-DD". */
export function parseExpiry(expiry: string): number | null {
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(expiry);
  if (iso) {
    return Date.UTC(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));
  }
  const dmy = /^(\d{1,2})-([A-Za-z]{3})-(\d{2,4})$/.exec(expiry);
  if (dmy) {
    const month = MONTHS[dmy[2].toUpperCase()];
    if (month === undefined) return null;
    const yearRaw = Number(dmy[3]);
    const year = yearRaw < 100 ? 2000 + yearRaw : yearRaw;
    return Date.UTC(year, month, Number(dmy[1]));
  }
  return null;
}

/** Whole days from `nowMs` to the expiry (>= 0), or 0 when unparseable. */
export function daysToExpiry(expiry: string, nowMs: number): number {
  const target = parseExpiry(expiry);
  if (target == null) return 0;
  return Math.max(0, Math.round((target - nowMs) / 86_400_000));
}

/** Short display label from an expiry, falling back to the raw string. */
export function labelFor(expiry: string): string {
  const ms = parseExpiry(expiry);
  if (ms == null) return expiry.length > 9 ? expiry.slice(0, 9) : expiry;
  const d = new Date(ms);
  const day = d.getUTCDate();
  const mon = Object.keys(MONTHS)[d.getUTCMonth()];
  const monTitle = mon.charAt(0) + mon.slice(1).toLowerCase();
  return `${day} ${monTitle}`;
}

function num(v: number | undefined): number {
  return v != null && Number.isFinite(v) ? v : 0;
}

/** A CE row is usable for the heatmap only if it carries at least one greek. */
function hasGreeks(row: RawOptionRow | null): boolean {
  if (!row) return false;
  return [row.delta, row.gamma, row.theta, row.vega].some(
    (v) => v != null && Number.isFinite(v) && v !== 0,
  );
}

function classifyMoneyness(strike: number, atm: number): Moneyness {
  if (strike === atm) return "ATM";
  // Call convention: a strike below spot/ATM is in-the-money for a call.
  return strike < atm ? "ITM" : "OTM";
}

/** Map a raw chain to (strike → CE greeks) for strikes that carry greeks. */
function ceGreeksByStrike(entries: ChainEntry[]): Map<number, RawOptionRow> {
  const map = new Map<number, RawOptionRow>();
  for (const entry of entries) {
    if (hasGreeks(entry.ce)) map.set(entry.strike, entry.ce as RawOptionRow);
  }
  return map;
}

/**
 * Build the aligned heatmap grid from per-expiry raw chains.
 *
 * Every expiry row is rendered against the SAME strike set (the intersection of
 * strikes that carry CE greeks across all expiries), so the grid columns stay
 * aligned. Returns null when no common greek-bearing strike exists, so the
 * caller can fall back to sample data.
 */
export function buildGreeksHeatmap(
  chains: ReadonlyArray<{ expiry: string; raw: RawOptionChain }>,
  nowMs: number,
): ExpiryRow[] | null {
  if (chains.length === 0) return null;

  const perExpiry = chains.map(({ expiry, raw }) => ({
    expiry,
    raw,
    greeks: ceGreeksByStrike(raw.chain ?? []),
  }));

  // Intersection of strikes carrying greeks across every expiry.
  const [first, ...rest] = perExpiry;
  let common = [...first.greeks.keys()];
  for (const e of rest) {
    common = common.filter((s) => e.greeks.has(s));
  }
  common.sort((a, b) => a - b);
  if (common.length === 0) return null;

  const rows: ExpiryRow[] = perExpiry.map(({ expiry, raw, greeks }) => {
    const atm =
      raw.atm_strike && raw.atm_strike > 0
        ? raw.atm_strike
        : common[Math.floor(common.length / 2)];
    const cells: HeatCell[] = common.map((strike) => {
      const g = greeks.get(strike) as RawOptionRow;
      return {
        strike,
        moneyness: classifyMoneyness(strike, atm),
        delta: num(g.delta),
        gamma: num(g.gamma),
        theta: num(g.theta),
        vega: num(g.vega),
      };
    });
    return { expiry, label: labelFor(expiry), dte: daysToExpiry(expiry, nowMs), cells };
  });

  return rows;
}

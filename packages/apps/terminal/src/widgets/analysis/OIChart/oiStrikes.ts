/**
 * oiStrikes — the one normalisation of a raw option chain into strike cells.
 *
 * OI Analytics renders four views (bars / butterfly / heat / signals) and every
 * chain-derived one is built from the {@link StrikeCell} array this module
 * produces. Before the merge, the bar chart and the heat grid each parsed the
 * same `getOptionChain` payload with their own copy of this logic, their own
 * ATM window (±15 vs ±10) and — worse — their own idea of what ΔOI means: the
 * bar chart diffed its own poll snapshots while the heat grid read the
 * backend's `oi_change` field. Two panels on one screen could therefore
 * disagree about the same strike.
 *
 * ΔOI HAS ONE SOURCE: the backend's `oi_change`. A client-side diff of two poll
 * snapshots is strictly worse — it measures the gap between two arbitrary
 * client fetches rather than the session change the broker reports, it starts
 * out unavailable, it resets on every identity change, and it disagreed with
 * the neighbouring panel. `oi_change` is absent for a row → ΔOI is `null`
 * ("unavailable"), never `0`.
 *
 * MISSING IS NOT ZERO. Every field is validated, and an absent or malformed
 * value becomes `null` rather than a plausible-looking number. A supplied `0`
 * survives as `0`, which is why the totals/marker rules below test
 * completeness separately from positivity.
 */

import type {
  ChainEntry,
  RawOptionChain,
  RawOptionRow,
} from "@/widgets/analysis/OptionChain/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** One strike's normalised CE/PE figures. `null` means "not supplied". */
export interface StrikeCell {
  strike: number;
  ceOi: number | null;
  peOi: number | null;
  ceOiChange: number | null;
  peOiChange: number | null;
  ceVolume: number | null;
  peVolume: number | null;
}

/** ΔOI-direction filter shared by every chain view. */
export type OIFilter = "All" | "OI Increase" | "OI Decrease";

export const OI_FILTERS: readonly OIFilter[] = ["All", "OI Increase", "OI Decrease"];

export interface StrikeWindow {
  cells: StrikeCell[];
  /** Strike nearest the authoritative spot, or `null` when spot is unknown. */
  atmStrike: number | null;
}

export interface StrikeSummary {
  /** Total CE OI, or `null` when any row in the set is missing CE OI. */
  totalCeOi: number | null;
  totalPeOi: number | null;
  /** Put-call ratio over the same rows the totals came from. */
  pcr: number | null;
  /** Colour-intensity denominators — the largest KNOWN value on each side. */
  maxCeOi: number;
  maxPeOi: number;
  /** Resistance: strike carrying the most CE OI. `null` unless the side is complete AND positive. */
  maxCeStrike: number | null;
  /** Support: strike carrying the most PE OI. */
  maxPeStrike: number | null;
}

// ---------------------------------------------------------------------------
// Field validation
// ---------------------------------------------------------------------------

/** Strikes must be strictly positive; a legacy row without one is dropped. */
export function positiveFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/** Open interest is a non-negative whole number of contracts. */
function optionOi(row: RawOptionRow | null | undefined): number | null {
  const raw = row?.oi ?? row?.open_interest;
  return typeof raw === "number"
    && Number.isFinite(raw)
    && Number.isInteger(raw)
    && raw >= 0
    ? raw
    : null;
}

/** ΔOI may be negative and is not required to be integral. */
function optionalFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Traded volume is a non-negative whole number. */
function optionalNonNegativeInteger(value: unknown): number | null {
  return typeof value === "number"
    && Number.isFinite(value)
    && Number.isInteger(value)
    && value >= 0
    ? value
    : null;
}

// ---------------------------------------------------------------------------
// Chain → strike cells
// ---------------------------------------------------------------------------

interface StrikeLegs {
  calls: Record<number, RawOptionRow>;
  puts: Record<number, RawOptionRow>;
}

/** Accepts both the v2 `chain[]` shape and the legacy `calls[]`/`puts[]` one. */
function collectLegs(chain: RawOptionChain): StrikeLegs {
  const calls: Record<number, RawOptionRow> = {};
  const puts: Record<number, RawOptionRow> = {};

  if (chain.chain && chain.chain.length > 0) {
    for (const entry of chain.chain as ChainEntry[]) {
      const strike = positiveFiniteNumber(entry.strike);
      if (strike === null) continue;
      if (entry.ce) calls[strike] = entry.ce;
      if (entry.pe) puts[strike] = entry.pe;
    }
    return { calls, puts };
  }

  for (const call of chain.calls ?? []) {
    const strike = positiveFiniteNumber(call.strike_price ?? call.strike);
    if (strike !== null) calls[strike] = call;
  }
  for (const put of chain.puts ?? []) {
    const strike = positiveFiniteNumber(put.strike_price ?? put.strike);
    if (strike !== null) puts[strike] = put;
  }
  return { calls, puts };
}

/**
 * Normalise a raw chain into the ATM-centred strike window every view renders.
 *
 * @param chain Raw `getOptionChain` payload, or `null` before one arrives.
 * @param spotLtp Authoritative spot — the live quote when available, else the
 *   chain's own `underlying_ltp`. The chain's `atm_strike` is deliberately NOT
 *   used: it is a snapshot field that goes stale within the poll interval.
 * @param strikesEachSide Half-width of the window, in strikes.
 */
export function buildStrikeCells(
  chain: RawOptionChain | null,
  spotLtp: number | null,
  strikesEachSide: number,
): StrikeWindow {
  if (!chain) return { cells: [], atmStrike: null };

  const { calls, puts } = collectLegs(chain);
  const allStrikes = Array.from(
    new Set([...Object.keys(calls), ...Object.keys(puts)].map(Number)),
  ).sort((a, b) => a - b);

  if (allStrikes.length === 0) return { cells: [], atmStrike: null };

  const atmStrike = spotLtp !== null
    ? allStrikes.reduce((nearest, strike) => (
        Math.abs(strike - spotLtp) < Math.abs(nearest - spotLtp) ? strike : nearest
      ))
    : null;

  const atmIdx = allStrikes.indexOf(atmStrike ?? 0);
  const lo = Math.max(0, atmIdx - strikesEachSide);
  const hi = Math.min(allStrikes.length - 1, atmIdx + strikesEachSide);

  const cells: StrikeCell[] = allStrikes.slice(lo, hi + 1).map((strike) => {
    const ce = calls[strike];
    const pe = puts[strike];
    return {
      strike,
      ceOi: optionOi(ce),
      peOi: optionOi(pe),
      // The backend's own session change — never a client-side snapshot diff.
      ceOiChange: optionalFiniteNumber(ce?.oi_change),
      peOiChange: optionalFiniteNumber(pe?.oi_change),
      ceVolume: optionalNonNegativeInteger(ce?.volume),
      peVolume: optionalNonNegativeInteger(pe?.volume),
    };
  });

  return { cells, atmStrike };
}

// ---------------------------------------------------------------------------
// Derived views over the cells
// ---------------------------------------------------------------------------

/**
 * Apply the ΔOI-direction filter.
 *
 * A row whose ΔOI is unavailable on both legs matches NEITHER direction — an
 * unknown change is not evidence of an increase or a decrease.
 */
export function filterStrikeCells(cells: StrikeCell[], filter: OIFilter): StrikeCell[] {
  if (filter === "OI Increase") {
    return cells.filter((cell) => (
      (cell.ceOiChange !== null && cell.ceOiChange > 0)
      || (cell.peOiChange !== null && cell.peOiChange > 0)
    ));
  }
  if (filter === "OI Decrease") {
    return cells.filter((cell) => (
      (cell.ceOiChange !== null && cell.ceOiChange < 0)
      || (cell.peOiChange !== null && cell.peOiChange < 0)
    ));
  }
  return cells;
}

/**
 * Totals, PCR and the support/resistance strikes for a set of cells.
 *
 * Callers pass the FILTERED set, so every headline figure describes exactly the
 * rows on screen. The response's own `pcr` field is never surfaced: it covers
 * the whole chain, which is a different population from the visible window and
 * silently disagrees with it.
 *
 * Totals and max-OI markers are withheld unless the side is COMPLETE. One
 * missing leg makes a sum an understatement and can hand "max OI" to a strike
 * only because its larger neighbour did not report.
 */
export function summariseStrikeCells(cells: StrikeCell[]): StrikeSummary {
  const knownCeOi = cells.flatMap((cell) => (cell.ceOi === null ? [] : [cell.ceOi]));
  const knownPeOi = cells.flatMap((cell) => (cell.peOi === null ? [] : [cell.peOi]));

  const hasCompleteCeOi = cells.length > 0 && knownCeOi.length === cells.length;
  const hasCompletePeOi = cells.length > 0 && knownPeOi.length === cells.length;

  const totalCeOi = hasCompleteCeOi ? knownCeOi.reduce((sum, oi) => sum + oi, 0) : null;
  const totalPeOi = hasCompletePeOi ? knownPeOi.reduce((sum, oi) => sum + oi, 0) : null;
  const pcr = totalCeOi !== null && totalCeOi > 0 && totalPeOi !== null
    ? totalPeOi / totalCeOi
    : null;

  const maxCeCell = hasCompleteCeOi
    ? cells.reduce((best, cell) => (cell.ceOi! > best.ceOi! ? cell : best))
    : null;
  const maxPeCell = hasCompletePeOi
    ? cells.reduce((best, cell) => (cell.peOi! > best.peOi! ? cell : best))
    : null;

  return {
    totalCeOi,
    totalPeOi,
    pcr,
    maxCeOi: Math.max(1, ...knownCeOi),
    maxPeOi: Math.max(1, ...knownPeOi),
    maxCeStrike: maxCeCell !== null && maxCeCell.ceOi! > 0 ? maxCeCell.strike : null,
    maxPeStrike: maxPeCell !== null && maxPeCell.peOi! > 0 ? maxPeCell.strike : null,
  };
}

/** Per-strike PCR — `null` unless both legs reported and CE OI is positive. */
export function strikePcr(cell: StrikeCell): number | null {
  return cell.ceOi !== null && cell.peOi !== null && cell.ceOi > 0
    ? cell.peOi / cell.ceOi
    : null;
}

/** True when any leg in the chain reports positive open interest. */
export function chainHasPositiveOi(cells: StrikeCell[]): boolean {
  return cells.some((cell) => (
    (cell.ceOi !== null && cell.ceOi > 0) || (cell.peOi !== null && cell.peOi > 0)
  ));
}

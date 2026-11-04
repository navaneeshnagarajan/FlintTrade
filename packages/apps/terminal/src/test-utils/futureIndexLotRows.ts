import type { ScripRow } from "@/lib/instrumentLots";

/**
 * Official contract multipliers, checked against the NSE market-lot file
 * (NIFTY 65, BANKNIFTY 30) and the shipped SENSEX future (20).
 * The expiries are generated from the clock so a stale excerpt cannot
 * blank these tests when a listed month passes.
 */
const LOTS: readonly [string, string, string][] = [
  ["NIFTY", "NSE", "65"],
  ["BANKNIFTY", "NSE", "30"],
  ["SENSEX", "BSE", "20"],
];

/**
 * Wall clock plus `FLINTTRADE_CLOCK_OFFSET_MONTHS`.
 * Proof runs set `1` and `6` so a shipped expiry cannot blank the lookup.
 */
export function lotTestClock(from: Date = new Date()): Date {
  const months = Number(process.env.FLINTTRADE_CLOCK_OFFSET_MONTHS ?? "0");
  if (!Number.isFinite(months) || months === 0) return from;
  const shifted = new Date(from.getTime());
  shifted.setUTCMonth(shifted.getUTCMonth() + months);
  return shifted;
}

function isoDaysAhead(days: number, from: Date): string {
  const date = new Date(from.getTime());
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** Near, next and far index futures, each expiry after `from`. */
export function futureIndexLotRows(from: Date = new Date()): ScripRow[] {
  return LOTS.flatMap(([symbol, exchange, lot], index) => {
    const rows: ScripRow[] = [];
    for (let month = 0; month < 3; month += 1) {
      const expiry = isoDaysAhead(28 + index * 3 + month * 32, from);
      rows.push({
        SEM_EXM_EXCH_ID: exchange,
        SEM_SEGMENT: "D",
        SEM_SMST_SECURITY_ID: `${symbol}-${month}`,
        SEM_INSTRUMENT_NAME: "FUTIDX",
        SEM_TRADING_SYMBOL: `${symbol}-FUT`,
        SEM_CUSTOM_SYMBOL: symbol,
        SEM_EXPIRY_DATE: expiry,
        SEM_LOT_UNITS: lot,
      });
    }
    return rows;
  });
}

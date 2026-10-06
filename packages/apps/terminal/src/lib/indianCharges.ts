/**
 * Terminal reader for the shared Indian statutory charges table.
 *
 * The JSON file in ``flinttrade_core`` is the only copy of the rates.
 * Lot size is never read from this table.
 */

import table from "@flinttrade/indian-charges";

export type ChargeSegment =
  | "equity_futures"
  | "equity_options"
  | "sensex_options"
  | "bankex_options"
  | "equity_delivery"
  | "equity_intraday";

interface ChargeRow {
  exchange: string;
  segment: string;
  component: string;
  side: string;
  basis: string;
  rate: string;
  effective_from: string;
  effective_to: string | null;
}

const ROWS = table.rates as ChargeRow[];

function inForce(row: ChargeRow, on: string): boolean {
  if (row.effective_from > on) return false;
  if (row.effective_to !== null && on > row.effective_to) return false;
  return true;
}

/** Fractional rate in force on ``on`` (``YYYY-MM-DD``). Zero when no row matches. */
export function chargeRate(
  exchange: string,
  segment: string,
  component: string,
  side: "buy" | "sell",
  on: string,
): number {
  const wantedExchange = exchange.toUpperCase();
  const pool = ROWS.filter(
    (row) =>
      row.component === component &&
      (row.exchange === wantedExchange || row.exchange === "ANY") &&
      (row.segment === segment || row.segment === "any") &&
      (row.side === side || row.side === "both") &&
      inForce(row, on),
  );
  if (pool.length === 0) return 0;
  const best = pool.reduce((left, right) => {
    const leftScore =
      (left.exchange === wantedExchange ? 4 : 0) +
      (left.segment === segment ? 2 : 0) +
      (left.side === side ? 1 : 0);
    const rightScore =
      (right.exchange === wantedExchange ? 4 : 0) +
      (right.segment === segment ? 2 : 0) +
      (right.side === side ? 1 : 0);
    if (rightScore !== leftScore) return rightScore > leftScore ? right : left;
    return right.effective_from > left.effective_from ? right : left;
  });
  return Number(best.rate);
}

export function exchangeTransactionLabel(exchange: string): string {
  const key = exchange.trim().toUpperCase();
  if (key === "BSE" || key.startsWith("BSE") || key === "BFO") return "BSE transaction";
  return "NSE transaction";
}

function paisa(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

export interface StatutoryLeg {
  stt: number;
  exchangeCharges: number;
  exchangeLabel: string;
  sebiFee: number;
  stampDuty: number;
  gst: number;
  brokerage: number;
  total: number;
}

/** One fill. Brokerage is included only when the caller configured a broker rate. */
export function statutoryLeg(input: {
  exchange: string;
  segment: ChargeSegment;
  turnover: number;
  isBuy: boolean;
  on: string;
  brokerage?: number;
}): StatutoryLeg {
  const side = input.isBuy ? "buy" : "sell";
  const stt = paisa(input.turnover * chargeRate(input.exchange, input.segment, "stt", side, input.on));
  const exchangeCharges = paisa(
    input.turnover * chargeRate(input.exchange, input.segment, "exchange_transaction", side, input.on),
  );
  const sebiFee = paisa(input.turnover * chargeRate(input.exchange, input.segment, "sebi", side, input.on));
  const stampDuty = paisa(
    input.turnover * chargeRate(input.exchange, input.segment, "stamp_duty", side, input.on),
  );
  const brokerage = paisa(input.brokerage ?? 0);
  const gstRate = chargeRate("ANY", "any", "gst", side, input.on);
  const gst = paisa((brokerage + exchangeCharges + sebiFee) * gstRate);
  const total = paisa(brokerage + stt + exchangeCharges + sebiFee + stampDuty + gst);
  return {
    stt,
    exchangeCharges,
    exchangeLabel: exchangeTransactionLabel(input.exchange),
    sebiFee,
    stampDuty,
    gst,
    brokerage,
    total,
  };
}

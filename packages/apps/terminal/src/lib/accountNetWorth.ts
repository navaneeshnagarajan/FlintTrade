/**
 * One net-worth figure for Home and Invest.
 *
 * Cash plus the mark of holdings and open positions. A fill that only moves
 * cash into a position must not change this total when the price is unchanged.
 */

export interface MarkedLine {
  ltp: number;
  quantity: number;
}

/** Same rupee string Home and Invest use for the net-worth headline. */
export function formatAccountNetWorth(value: number): string {
  const safe = Number.isFinite(value) ? value : 0;
  return safe.toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  });
}

/** Mark of a book. Quantity is absolute so a long and a listed holding agree. */
export function markedValue(rows: readonly MarkedLine[]): number {
  return rows.reduce((sum, row) => {
    const ltp = Number.isFinite(row.ltp) ? row.ltp : 0;
    const quantity = Number.isFinite(row.quantity) ? row.quantity : 0;
    return sum + ltp * Math.abs(quantity);
  }, 0);
}

export function accountNetWorth(
  holdings: readonly MarkedLine[],
  availableCash: number,
  positions: readonly MarkedLine[] = [],
): number {
  const cash = Number.isFinite(availableCash) ? availableCash : 0;
  return markedValue(holdings) + markedValue(positions) + cash;
}

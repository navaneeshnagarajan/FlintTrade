/**
 * One net-worth figure for Home and Invest.
 *
 * Market value of the exposed book plus available cash. Both surfaces call
 * this so a Practice balance cannot sit next to a different sample total.
 */

/** Same rupee string Home and Invest use for the net-worth headline. */
export function formatAccountNetWorth(value: number): string {
  const safe = Number.isFinite(value) ? value : 0;
  return safe.toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  });
}

export function accountNetWorth(
  holdings: readonly { ltp: number; quantity: number }[],
  availableCash: number,
): number {
  const book = holdings.reduce((sum, holding) => sum + holding.ltp * Math.abs(holding.quantity), 0);
  const cash = Number.isFinite(availableCash) ? availableCash : 0;
  return book + cash;
}

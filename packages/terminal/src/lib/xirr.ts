/**
 * XIRR calculation using Newton-Raphson method.
 * Takes an array of { date: Date, amount: number } cash flows.
 * Returns the annualized internal rate of return.
 *
 * Convention: outflows (investments) are negative, inflows (redemptions /
 * current value) are positive. The first cash flow anchors time = 0.
 */
export function xirr(
  cashflows: { date: Date; amount: number }[],
): number | null {
  if (cashflows.length < 2) return null;

  // Days from the first cash flow date (in fractional years)
  const days = cashflows.map(
    (cf) =>
      (cf.date.getTime() - cashflows[0].date.getTime()) / (365.25 * 86400000),
  );

  // Newton-Raphson iteration — start at a 10% annual rate guess
  let rate = 0.1;

  for (let i = 0; i < 100; i++) {
    let f = 0;
    let df = 0;

    for (let j = 0; j < cashflows.length; j++) {
      const amount = cashflows[j].amount;
      const t = days[j];
      const factor = Math.pow(1 + rate, t);
      const pv = amount / factor;
      f += pv;
      df -= (t * amount) / (factor * (1 + rate));
    }

    if (Math.abs(f) < 1e-8) return rate;

    if (df === 0) return null;
    const newRate = rate - f / df;
    if (!isFinite(newRate)) return null;

    rate = newRate;
  }

  // Sanity check: reject implausibly large rates (> 1000% or < -99%)
  return Math.abs(rate) < 10 ? rate : null;
}

/** One paisa in INR — matches ``fmtInr``'s two-decimal display basis. */
const RECONCILE_TOLERANCE_INR = 0.01;

const RECONCILES_HELPER = "Reconciles with trade log";
const DIVERGES_HELPER = "Trade log sum ≠ equity change — fees / open marks";

export function sumTradeLogPnl(trades: ReadonlyArray<{ pnl: number }>): number {
  return trades.reduce((sum, trade) => sum + trade.pnl, 0);
}

export function equityCurveDelta(
  equityCurve: ReadonlyArray<{ equity: number }>,
  finalEquity: number,
): number {
  if (equityCurve.length === 0) return 0;
  return finalEquity - equityCurve[0].equity;
}

export function backtestPnlHelper(netTradePnl: number, equityDelta: number): string {
  return Math.abs(netTradePnl - equityDelta) < RECONCILE_TOLERANCE_INR
    ? RECONCILES_HELPER
    : DIVERGES_HELPER;
}

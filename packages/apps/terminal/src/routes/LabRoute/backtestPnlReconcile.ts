/** One paisa in INR — matches ``fmtInr``'s two-decimal display basis. */
const RECONCILE_TOLERANCE_INR = 0.01;

const RECONCILES_HELPER = "Reconciles with trade log";
const DIVERGES_HELPER = "Trade log sum ≠ equity change — fees / open marks";

export type TradePnlBasis = "net" | "gross";

export interface TradeLogPnlSum {
  amount: number;
  basis: TradePnlBasis;
}

export interface TradeLogPnlRow {
  pnl: number;
  net_pnl?: number;
}

function hasNetPnl(trade: TradeLogPnlRow): trade is TradeLogPnlRow & { net_pnl: number } {
  return typeof trade.net_pnl === "number" && Number.isFinite(trade.net_pnl);
}

export function sumTradeLogPnl(trades: ReadonlyArray<TradeLogPnlRow>): TradeLogPnlSum {
  if (trades.length === 0) return { amount: 0, basis: "net" };
  if (trades.every(hasNetPnl)) {
    return {
      amount: trades.reduce((sum, trade) => sum + trade.net_pnl, 0),
      basis: "net",
    };
  }
  return {
    amount: trades.reduce((sum, trade) => sum + trade.pnl, 0),
    basis: "gross",
  };
}

export function tradePnlForBasis(trade: TradeLogPnlRow, basis: TradePnlBasis): number {
  return basis === "net" && hasNetPnl(trade) ? trade.net_pnl : trade.pnl;
}

export function equityCurveDelta(
  equityCurve: ReadonlyArray<{ equity: number }>,
  finalEquity: number,
): number {
  if (equityCurve.length === 0) return 0;
  return finalEquity - equityCurve[0].equity;
}

/**
 * Total Return as a fraction for ``fmtPct``.
 *
 * Prefer ``(finalEquity - startEquity) / startEquity`` — that is initial
 * capital → final equity, including a forced last-bar close. Live
 * ``metrics.total_return`` is percentage points; the Explore demo emits a
 * fraction. Only the no-curve fallback inspects that field.
 */
export function headlineTotalReturnFraction(
  totalReturn: number,
  finalEquity: number,
  startEquity: number | undefined,
): number {
  if (
    typeof startEquity === "number" &&
    Number.isFinite(startEquity) &&
    startEquity !== 0 &&
    Number.isFinite(finalEquity)
  ) {
    return (finalEquity - startEquity) / startEquity;
  }
  if (!Number.isFinite(totalReturn)) return 0;
  return Math.abs(totalReturn) > 1 ? totalReturn / 100 : totalReturn;
}

export function backtestPnlHelper(netTradePnl: number, equityDelta: number): string {
  return Math.abs(netTradePnl - equityDelta) < RECONCILE_TOLERANCE_INR
    ? RECONCILES_HELPER
    : DIVERGES_HELPER;
}

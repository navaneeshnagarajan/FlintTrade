import { positionMtm } from "@/lib/pnl";

/**
 * One net-worth figure for Home and Invest.
 *
 * Net worth is cash, plus the market value of holdings, plus the unrealised
 * P&L of open positions, minus charges. Positions count at unrealised P&L.
 * Gross notional is not equity: it overstates a leveraged book and turns a
 * short into an asset.
 */

/** Invest Dashboard total. Home uses the shorter "Net Worth" label. */
export const NET_WORTH_LABEL = "Net Worth (Cash + Holdings + Positions)";

/** Tooltip and description for how open positions enter the total. */
export const NET_WORTH_POSITIONS_NOTE = "Positions count at unrealised P&L.";

/**
 * Charges on the account book. Practice funds have no charges field today,
 * so this is 0 until a later book exposes a finite `charges` value.
 */
export function accountCharges(source: object | null | undefined): number {
  if (source == null || !("charges" in source)) return 0;
  const charges = source.charges;
  return typeof charges === "number" && Number.isFinite(charges) ? charges : 0;
}

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

/** Mark of a holdings book. Quantity is absolute so a long and a listed holding agree. */
export function markedValue(rows: readonly MarkedLine[]): number {
  return rows.reduce((sum, row) => {
    const ltp = Number.isFinite(row.ltp) ? row.ltp : 0;
    const quantity = Number.isFinite(row.quantity) ? row.quantity : 0;
    return sum + ltp * Math.abs(quantity);
  }, 0);
}

/** One open position, signed quantity. A short is a negative quantity. */
export interface PositionLine {
  quantity: number;
  ltp: number;
  averagePrice?: number;
  pnl?: number;
}

/**
 * Unrealised P&L of one open position.
 *
 * A flat row adds nothing, including when a broker `pnl` field is still set.
 * An open row uses the shared mark-to-market `(ltp − average price) × quantity`.
 */
export function positionUnrealisedPnl(position: PositionLine): number {
  const quantity = Number.isFinite(position.quantity) ? position.quantity : 0;
  if (quantity === 0) return 0;
  const ltp = Number.isFinite(position.ltp) ? position.ltp : 0;
  const averagePrice = Number.isFinite(position.averagePrice) ? Number(position.averagePrice) : 0;
  const pnl = Number.isFinite(position.pnl) ? Number(position.pnl) : 0;
  return positionMtm({
    symbol: "",
    exchange: "",
    product: "",
    quantity,
    averagePrice,
    ltp,
    pnl,
    pnlPercent: 0,
  });
}

/** Sum of open positions' unrealised P&L. This is the position term in net worth. */
export function positionsUnrealisedPnl(positions: readonly PositionLine[]): number {
  return positions.reduce((sum, position) => sum + positionUnrealisedPnl(position), 0);
}

export function accountNetWorth(
  holdings: readonly MarkedLine[],
  availableCash: number,
  positions: readonly PositionLine[] = [],
  charges = 0,
): number {
  const cash = Number.isFinite(availableCash) ? availableCash : 0;
  const deducted = Number.isFinite(charges) ? charges : 0;
  return markedValue(holdings) + positionsUnrealisedPnl(positions) + cash - deducted;
}

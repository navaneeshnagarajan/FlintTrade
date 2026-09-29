/**
 * One net-worth figure for Home and Invest.
 *
 * Net worth is ledger cash, plus the market value of holdings, plus each
 * open position's contribution, minus charges. Ledger cash includes blocked
 * or utilised margin. It is not the available margin.
 *
 * Options (CE/PE) add signed market value: LTP × quantity. A long is
 * positive and a short is negative, because the premium already went
 * through cash. Equity intraday or delivery positions that are not already
 * in the holdings book do the same. Futures add unrealised P&L from the
 * last daily settlement price when the funds source already includes
 * earlier days' MTM, and from the entry price when it does not.
 *
 * Adapters normalise those inputs. Practice never settles futures MTM into
 * capital and has no settlement price, so its futures mark from the fill
 * average. Dhan's start-of-day balance includes earlier MTM, and a future's
 * settlement price is the mark-to-market average (`buyAvg` / `sellAvg`),
 * falling back to `costPrice` when that average is absent. Kotak Neo's
 * ledger is Net + MarginUsed and also includes earlier MTM, but a position
 * has no settlement or previous close: the documented fallback is the
 * open-leg average, which can recount carry-forward MTM already in cash.
 * That fallback is marked `markSource: "fallback"` and the figure is
 * approximate. Carried value divided by quantity, and Neo `upldPrc`, stay
 * unused until a funded overnight position confirms they match settlement.
 */

/** Invest Dashboard total. Home uses the shorter "Net Worth" label. */
export const NET_WORTH_LABEL = "Net Worth (Cash + Holdings + Positions)";

/** Tooltip and description for how open positions enter the total. */
export const NET_WORTH_POSITIONS_NOTE = "Options at market value, futures at unrealised P&L.";

/** How a future's mark base was chosen. Practice does not set this. */
export type FuturesMarkSource = "avg" | "fallback";

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
  symbol?: string;
  exchange?: string;
}

/** Same rupee string Home and Invest use for the net-worth headline. */
export function formatAccountNetWorth(value: number, approximate = false): string {
  const safe = Number.isFinite(value) ? value : 0;
  const formatted = safe.toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  });
  return approximate ? `≈ ${formatted}` : formatted;
}

/** Screen-reader name when the figure uses a fallback futures mark. */
export function accountNetWorthAccessibleName(value: number): string {
  return `Net Worth, approximately ${formatAccountNetWorth(value)}`;
}

/**
 * Tooltip while any open future uses the fallback mark.
 * One position names the symbol. Several name the count.
 */
export function approximateNetWorthTooltip(symbols: readonly string[]): string | null {
  if (symbols.length === 0) return null;
  const subject = symbols.length === 1
    ? symbols[0]
    : `${symbols.length} futures positions`;
  return `Approximate. Your broker didn't send an average price for ${subject}, so profit or loss from earlier days may be counted twice.`;
}

/** Positions note, or the approximate tooltip when a fallback mark is in use. */
export function netWorthFigureTitle(approximate: boolean, symbols: readonly string[]): string {
  if (!approximate) return NET_WORTH_POSITIONS_NOTE;
  return approximateNetWorthTooltip(symbols) ?? NET_WORTH_POSITIONS_NOTE;
}

/** Mark of a holdings book. Quantity is absolute so a long and a listed holding agree. */
export function markedValue(rows: readonly MarkedLine[]): number {
  return rows.reduce((sum, row) => {
    const ltp = Number.isFinite(row.ltp) ? row.ltp : 0;
    const quantity = Number.isFinite(row.quantity) ? row.quantity : 0;
    return sum + ltp * Math.abs(quantity);
  }, 0);
}

/**
 * One open position. Quantity is signed: a short is negative.
 * Live rows may use the adapter's snake_case names.
 */
export interface PositionLine {
  symbol?: string;
  exchange?: string;
  product?: string;
  optionType?: string;
  option_type?: string;
  quantity: number;
  ltp: number;
  averagePrice?: number;
  average_price?: number;
  avg_price?: number;
  settlementPrice?: number;
  settlement_price?: number;
  /**
   * `avg` is the broker mark-to-market average. `fallback` is Dhan `costPrice`
   * or Kotak Neo's open-leg average. Absent on Practice.
   */
  markSource?: FuturesMarkSource;
  mark_source?: FuturesMarkSource;
  pnl?: number;
  /** True when this row's funds source already includes earlier days' futures MTM. */
  futuresMtmInLedger?: boolean;
}

interface FundsLike {
  availableCash?: number;
  available_balance?: number;
  usedMargin?: number;
  used_margin?: number;
  ledgerBalance?: number;
  ledger_balance?: number;
  futuresMtmInLedger?: boolean;
  futures_mtm_in_ledger?: boolean;
}

const DERIVATIVE_EXCHANGES = new Set([
  "NFO",
  "BFO",
  "MCX",
  "CDS",
  "NSE_FNO",
  "BSE_FNO",
  "MCX_COMM",
  "NSE_CURRENCY",
  "BSE_CURRENCY",
]);

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function lineNumber(position: PositionLine, ...keys: (keyof PositionLine)[]): number {
  for (const key of keys) {
    const parsed = finiteNumber(position[key]);
    if (parsed !== null) return parsed;
  }
  return 0;
}

function compactSymbol(position: PositionLine): string {
  return String(position.symbol ?? "").toUpperCase().replace(/\s+/g, "");
}

function isOption(position: PositionLine): boolean {
  const optionType = String(position.optionType ?? position.option_type ?? "").toUpperCase();
  if (optionType === "CE" || optionType === "PE" || optionType === "CALL" || optionType === "PUT") {
    return true;
  }
  const symbol = compactSymbol(position);
  // A digit keeps "RELIANCE" (ends in CE) from reading as a call.
  return /\d/.test(symbol) && (symbol.endsWith("CE") || symbol.endsWith("PE"));
}

function isFuture(position: PositionLine): boolean {
  if (isOption(position)) return false;
  if (compactSymbol(position).endsWith("FUT")) return true;
  return DERIVATIVE_EXCHANGES.has(String(position.exchange ?? "").toUpperCase());
}

function isIntradayEquity(position: PositionLine): boolean {
  const product = String(position.product ?? "").toUpperCase();
  return product === "MIS" || product === "INTRADAY";
}

function alreadyInHoldings(position: PositionLine, holdings: readonly MarkedLine[]): boolean {
  const symbol = String(position.symbol ?? "").trim().toUpperCase();
  if (!symbol) return false;
  const exchange = String(position.exchange ?? "").trim().toUpperCase();
  return holdings.some((holding) => {
    const holdingSymbol = String(holding.symbol ?? "").trim().toUpperCase();
    if (!holdingSymbol || holdingSymbol !== symbol) return false;
    const holdingExchange = String(holding.exchange ?? "").trim().toUpperCase();
    return !exchange || !holdingExchange || holdingExchange === exchange;
  });
}

/**
 * Ledger cash, including blocked margin.
 *
 * An adapter `ledgerBalance` wins: Practice uses it so option premium and
 * equity notional are already in cash, and Dhan/Neo use it for
 * available + utilised. Without that field, available + used margin is the
 * same join and still does not drop an open position by its blocked margin.
 */
export function accountLedgerCash(funds: FundsLike | null | undefined): number {
  if (funds == null) return 0;
  const explicit = finiteNumber(funds.ledgerBalance ?? funds.ledger_balance);
  if (explicit !== null) return explicit;
  const available = finiteNumber(funds.availableCash ?? funds.available_balance) ?? 0;
  const used = finiteNumber(funds.usedMargin ?? funds.used_margin) ?? 0;
  return available + used;
}

/** True when the funds payload says earlier days' futures MTM are in the ledger. */
export function fundsFuturesMtmInLedger(funds: FundsLike | null | undefined): boolean {
  if (funds == null) return false;
  if (typeof funds.futuresMtmInLedger === "boolean") return funds.futuresMtmInLedger;
  return funds.futures_mtm_in_ledger === true;
}

/**
 * How one open position enters net worth.
 *
 * A flat row adds nothing, including when a broker `pnl` field is still set.
 * A future whose ledger already contains earlier MTM marks from
 * `settlementPrice`. Kotak Neo does not send one: the fallback is the entry
 * average (`averagePrice`), and that can recount carry-forward MTM. Practice
 * sets the funds flag false, so a future marks from entry even if a price is
 * present. Options and equity positions that are not already holdings add
 * signed market value.
 */
export function positionNetWorthContribution(
  position: PositionLine,
  holdings: readonly MarkedLine[] = [],
  futuresMtmInLedger = false,
): number {
  const quantity = lineNumber(position, "quantity");
  if (quantity === 0) return 0;
  const ltp = lineNumber(position, "ltp");
  const entry = lineNumber(position, "averagePrice", "average_price", "avg_price");
  if (isFuture(position)) {
    const settled = position.futuresMtmInLedger ?? futuresMtmInLedger;
    const settlement = lineNumber(position, "settlementPrice", "settlement_price");
    // No settlement or previous close: mark from the entry average.
    // See the file comment for which source this fallback belongs to.
    const base = settled && settlement > 0 ? settlement : entry;
    if (!(ltp > 0) || !(base > 0)) return 0;
    return (ltp - base) * quantity;
  }
  if (!isOption(position) && !isIntradayEquity(position) && alreadyInHoldings(position, holdings)) {
    return 0;
  }
  const mark = ltp > 0 ? ltp : entry;
  return mark * quantity;
}

function positionUsesFallbackMark(position: PositionLine, futuresMtmInLedger: boolean): boolean {
  if (lineNumber(position, "quantity") === 0) return false;
  if (!isFuture(position)) return false;
  const source = position.markSource ?? position.mark_source;
  if (source !== "fallback") return false;
  // The fallback can recount MTM only when earlier days are already in cash.
  return (position.futuresMtmInLedger ?? futuresMtmInLedger) === true;
}

export interface NetWorthApproximation {
  approximate: boolean;
  fallbackSymbols: string[];
}

/**
 * Open futures whose mark is the fallback, not a change to the formula.
 * A flat row and a row whose average has arrived drop out immediately.
 */
export function netWorthApproximation(
  positions: readonly PositionLine[],
  futuresMtmInLedger = false,
): NetWorthApproximation {
  const fallbackSymbols: string[] = [];
  for (const position of positions) {
    if (!positionUsesFallbackMark(position, futuresMtmInLedger)) continue;
    fallbackSymbols.push(String(position.symbol ?? "").trim());
  }
  return { approximate: fallbackSymbols.length > 0, fallbackSymbols };
}

/** Sum of open positions' net-worth contributions. */
export function positionsNetWorthContribution(
  positions: readonly PositionLine[],
  holdings: readonly MarkedLine[] = [],
  futuresMtmInLedger = false,
): number {
  return positions.reduce(
    (sum, position) => sum + positionNetWorthContribution(position, holdings, futuresMtmInLedger),
    0,
  );
}

export function accountNetWorth(
  holdings: readonly MarkedLine[],
  ledgerCash: number,
  positions: readonly PositionLine[] = [],
  charges = 0,
  futuresMtmInLedger = false,
): number {
  const cash = Number.isFinite(ledgerCash) ? ledgerCash : 0;
  const deducted = Number.isFinite(charges) ? charges : 0;
  return markedValue(holdings)
    + positionsNetWorthContribution(positions, holdings, futuresMtmInLedger)
    + cash
    - deducted;
}

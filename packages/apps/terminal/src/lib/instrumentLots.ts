/**
 * Lot size from the cached Dhan / Kotak Neo scrip-master excerpt.
 *
 * A lot size belongs to one listed contract. Two expiries of the same
 * underlying may differ. A symbol missing from the master returns null.
 * The same contract with two sizes across the masters is a conflict.
 */

import { useSyncExternalStore } from "react";

/** Same prefix as `ftApi.helpers.getBase`, without importing the API client. */
function lotApiBase(): string {
  if (import.meta.env.DEV) return "/ft-api";
  return "";
}

export interface ScripRow {
  SEM_CUSTOM_SYMBOL?: string;
  UNDERLYING_SYMBOL?: string;
  SEM_SMST_SECURITY_ID?: string;
  SEM_INSTRUMENT_NAME?: string;
  SEM_TRADING_SYMBOL?: string;
  SEM_EXPIRY_DATE?: string;
  SEM_LOT_UNITS?: string;
  pSymbol?: string;
  pSymbolName?: string;
  pTrdSymbol?: string;
  pInstType?: string;
  pExpiryDate?: string;
  lLotSize?: string;
  [key: string]: string | undefined;
}

export interface ContractLot {
  securityIds: string[];
  underlying: string;
  expiry: string | null;
  lotSize: number;
  kind: string;
}

/**
 * Rows the desk is using. Empty until `loadInstrumentLotRows` reads
 * `GET /api/v1/instrument-lots` (disk cache, then the shipped excerpt).
 * Tests seed this directly. The app does not bundle the excerpt.
 */
let lotRows: ScripRow[] = [];
const lotListeners = new Set<() => void>();
let lotLoad: Promise<void> | null = null;

export function instrumentLotRows(): ScripRow[] {
  return lotRows;
}

export function setInstrumentLotRows(next: ScripRow[]): void {
  lotRows = next;
  for (const listener of lotListeners) listener();
}

export function subscribeInstrumentLots(listener: () => void): () => void {
  lotListeners.add(listener);
  return () => {
    lotListeners.delete(listener);
  };
}

/** Current rows. A later `setInstrumentLotRows` re-renders the subscriber. */
export function useInstrumentLotRows(): ScripRow[] {
  return useSyncExternalStore(subscribeInstrumentLots, instrumentLotRows, instrumentLotRows);
}

/**
 * Fetch the shared lookup once. A non-empty store is left alone so a test
 * seed is not overwritten. A failed or empty response does not clear it.
 */
export function loadInstrumentLotRows(): Promise<void> {
  if (lotRows.length > 0) return Promise.resolve();
  if (lotLoad) return lotLoad;
  lotLoad = fetch(`${lotApiBase()}/api/v1/instrument-lots`)
    .then(async (response) => {
      if (!response.ok) return;
      const payload = (await response.json()) as { rows?: ScripRow[] };
      if (lotRows.length > 0) return;
      if (Array.isArray(payload.rows) && payload.rows.length > 0) {
        setInstrumentLotRows(payload.rows);
      }
    })
    .catch(() => {
      // Keep the rows already in memory.
    })
    .finally(() => {
      lotLoad = null;
    });
  return lotLoad;
}

const MONTHS: Record<string, number> = {
  JAN: 1, FEB: 2, MAR: 3, APR: 4, MAY: 5, JUN: 6,
  JUL: 7, AUG: 8, SEP: 9, OCT: 10, NOV: 11, DEC: 12,
};
const MONTH_LABELS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function cell(row: ScripRow, names: string[]): string {
  const folded = new Map<string, string>();
  for (const [key, value] of Object.entries(row)) {
    if (value !== undefined && value !== "") folded.set(key.toLowerCase(), value);
  }
  for (const name of names) {
    const value = folded.get(name.toLowerCase());
    if (value) return value.trim();
  }
  return "";
}

function lotOf(row: ScripRow): number | null {
  const raw = cell(row, ["SEM_LOT_UNITS", "LOT_UNITS", "LOT_SIZE", "lLotSize", "lot_size"]);
  if (!raw) return null;
  const number = Number(raw);
  if (!Number.isInteger(number) || number <= 0) return null;
  return number;
}

function underlyingOf(row: ScripRow): string {
  return cell(row, [
    "SEM_CUSTOM_SYMBOL",
    "UNDERLYING_SYMBOL",
    "SM_SYMBOL_NAME",
    "SYMBOL_NAME",
    "pSymbolName",
  ]).toUpperCase().replace(/\s+/g, "");
}

function parseDate(raw: string): string | null {
  const iso = raw.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;
  const named = raw.match(/(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*[\s-]*(\d{4})/i);
  if (named) {
    const month = MONTHS[named[1].toUpperCase()];
    return `${named[2]}-${String(month).padStart(2, "0")}-01`;
  }
  const short = raw.toUpperCase().match(/(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)/);
  if (short) {
    const month = MONTHS[short[2]];
    return `20${short[1]}-${String(month).padStart(2, "0")}-01`;
  }
  return null;
}

function expiryOf(row: ScripRow): string | null {
  const explicit = parseDate(cell(row, [
    "SEM_EXPIRY_DATE", "SM_EXPIRY_DATE", "pExpiryDate", "lExpiryDate", "expiry",
  ]));
  if (explicit) return explicit;
  return parseDate(cell(row, ["SEM_TRADING_SYMBOL", "TRADING_SYMBOL", "pTrdSymbol", "trading_symbol"]));
}

function kindOf(row: ScripRow): string {
  const instrument = cell(row, ["SEM_INSTRUMENT_NAME", "pInstType", "instrument_type", "instrument"]).toUpperCase();
  const symbol = cell(row, ["SEM_TRADING_SYMBOL", "TRADING_SYMBOL", "pTrdSymbol", "trading_symbol"]).toUpperCase();
  if (instrument.includes("FUT") || symbol.endsWith("FUT")) return "FUT";
  if (instrument.startsWith("OPT") || symbol.endsWith("CE") || symbol.endsWith("PE")) return "OPT";
  return instrument || "INST";
}

function monthLabel(iso: string): string {
  const month = Number(iso.slice(5, 7));
  return MONTH_LABELS[month] ?? "";
}

/** Calendar day in India, `YYYY-MM-DD`. `asOf` freezes the filter in tests. */
function todayIst(asOf?: string): string {
  if (asOf) return asOf.slice(0, 10);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const year = parts.find((part) => part.type === "year")?.value ?? "";
  const month = parts.find((part) => part.type === "month")?.value ?? "";
  const day = parts.find((part) => part.type === "day")?.value ?? "";
  return `${year}-${month}-${day}`;
}

function unexpired(contracts: ContractLot[], asOf?: string): ContractLot[] {
  const today = todayIst(asOf);
  return contracts.filter((contract) => contract.expiry == null || contract.expiry >= today);
}

/** Reconcile master rows. Throws when one contract has two lot sizes. */
export function contractsFromRows(rows: ScripRow[]): ContractLot[] {
  const grouped = new Map<string, { securityId: string; underlying: string; expiry: string | null; lot: number; kind: string }[]>();
  for (const row of rows) {
    const underlying = underlyingOf(row);
    const lot = lotOf(row);
    if (!underlying || lot === null) continue;
    const expiry = expiryOf(row);
    const kind = kindOf(row);
    const when = expiry ? expiry.slice(0, 7) : "undated";
    const key = `${underlying}|${when}|${kind}`;
    const securityId = cell(row, [
      "SEM_SMST_SECURITY_ID", "SECURITY_ID", "instrument_token", "security_id", "pSymbol",
    ]) || key;
    const bucket = grouped.get(key) ?? [];
    bucket.push({ securityId, underlying, expiry, lot, kind });
    grouped.set(key, bucket);
  }

  const contracts: ContractLot[] = [];
  const seen = new Map<string, number>();
  for (const items of grouped.values()) {
    const sizes = new Set(items.map((item) => item.lot));
    const when = items[0].expiry ?? "undated";
    if (sizes.size > 1) {
      throw new Error(`Scrip master disagrees on the lot size for ${items[0].underlying} ${when}`);
    }
    const securityIds: string[] = [];
    for (const item of items) {
      const previous = seen.get(item.securityId);
      if (previous !== undefined && previous !== item.lot) {
        throw new Error(`Scrip master disagrees on the lot size for ${item.underlying} ${when}`);
      }
      seen.set(item.securityId, item.lot);
      if (!securityIds.includes(item.securityId)) securityIds.push(item.securityId);
    }
    contracts.push({
      securityIds,
      underlying: items[0].underlying,
      expiry: items[0].expiry,
      lotSize: items[0].lot,
      kind: items[0].kind,
    });
  }
  return contracts;
}

function seriesFor(underlying: string, contracts: ContractLot[], asOf?: string): ContractLot[] {
  const key = underlying.trim().toUpperCase().replace(/\s+/g, "");
  const mine = unexpired(contracts, asOf).filter((contract) => contract.underlying === key && contract.expiry);
  const futures = mine.filter((contract) => contract.kind === "FUT");
  const chosen = (futures.length > 0 ? futures : mine).slice();
  chosen.sort((left, right) => (left.expiry ?? "").localeCompare(right.expiry ?? ""));
  return chosen;
}

/** Lot size of one contract, addressed by instrument token or security id. */
export function lotSizeForContract(
  securityId: string,
  rows: ScripRow[] = instrumentLotRows(),
  asOf?: string,
): number | null {
  const token = securityId.trim();
  if (!token) return null;
  for (const contract of unexpired(contractsFromRows(rows), asOf)) {
    if (contract.securityIds.includes(token)) return contract.lotSize;
  }
  return null;
}

/** "1 lot", or "2 lots" for any other count. */
export function lotCountLabel(lots: number): string {
  const count = Number.isFinite(lots) ? lots : 0;
  return count === 1 ? "1 lot" : `${count} lots`;
}

/**
 * Near-month lot size, or null when the master has no row.
 * A later expiry can differ; use {@link lotSizeForContract} for one contract.
 */
export function lotSizeFromMaster(
  underlying: string,
  rows: ScripRow[] = instrumentLotRows(),
  asOf?: string,
): number | null {
  const dated = seriesFor(underlying, contractsFromRows(rows), asOf);
  if (dated.length > 0) return dated[0].lotSize;
  const key = underlying.trim().toUpperCase().replace(/\s+/g, "");
  const undated = unexpired(contractsFromRows(rows), asOf).filter(
    (contract) => contract.underlying === key && contract.expiry === null,
  );
  return undated[0]?.lotSize ?? null;
}

/**
 * Near-month size labelled with its expiry, for example `65 · Oct expiry`.
 * When the next month differs, both are named. Null when the master has no row.
 */
export function scalperLotLabel(
  underlying: string,
  rows: ScripRow[] = instrumentLotRows(),
  asOf?: string,
): string | null {
  const chosen = seriesFor(underlying, contractsFromRows(rows), asOf);
  if (chosen.length === 0) return null;
  const shown = [chosen[0]];
  if (chosen.length > 1 && chosen[1].lotSize !== chosen[0].lotSize) shown.push(chosen[1]);
  const parts = shown
    .filter((contract) => contract.expiry)
    .map((contract) => `${contract.lotSize} · ${monthLabel(contract.expiry as string)} expiry`);
  return parts.length > 0 ? parts.join(", ") : null;
}

const INDEX_UNDERLYINGS = ["NIFTY", "BANKNIFTY", "SENSEX"] as const;
const MISSING_LOT = "\u2014";

/**
 * Near-month index lots in the Scalper's form.
 *
 * `NIFTY 65 · BANKNIFTY 30 · SENSEX 20 (Sep/Oct expiry)`. A missing
 * underlying is `—`. When the Scalper names a second month, that
 * underlying keeps the Scalper's wording.
 */
export function indexLotLine(
  rows: ScripRow[] = instrumentLotRows(),
  asOf?: string,
  underlyings: readonly string[] = INDEX_UNDERLYINGS,
): string {
  const parts: string[] = [];
  const months: string[] = [];
  const seen = new Set<string>();
  for (const underlying of underlyings) {
    const label = scalperLotLabel(underlying, rows, asOf);
    if (label == null) {
      parts.push(`${underlying} ${MISSING_LOT}`);
      continue;
    }
    const segments = label.split(",").map((segment) => segment.trim()).filter(Boolean);
    const lots: string[] = [];
    for (const segment of segments) {
      const splitAt = segment.indexOf(" · ");
      const lotText = splitAt === -1 ? segment : segment.slice(0, splitAt);
      const rest = splitAt === -1 ? "" : segment.slice(splitAt + 3);
      const month = rest.replace(/ expiry$/, "").trim();
      if (lotText) lots.push(lotText);
      if (month && !seen.has(month)) {
        seen.add(month);
        months.push(month);
      }
    }
    if (segments.length === 1 && lots.length > 0) parts.push(`${underlying} ${lots[0]}`);
    else parts.push(`${underlying} ${label}`);
  }
  months.sort((left, right) => MONTH_LABELS.indexOf(left) - MONTH_LABELS.indexOf(right));
  const line = parts.join(" · ");
  return months.length > 0 ? `${line} (${months.join("/")} expiry)` : line;
}

export function useIndexLotLine(): string {
  const rows = useInstrumentLotRows();
  return indexLotLine(rows);
}

const DESK_OPTION = /^([A-Z][A-Z0-9&]*)\s+(\d+(?:\.\d+)?)\s+(CE|PE)$/;
const COMPACT_OPTION = /^([A-Z][A-Z0-9&]*?)(\d{1,2})?(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d+(?:\.\d+)?)(CE|PE)$/;

function plainStrike(strike: string): string {
  const number = Number(strike);
  if (!Number.isFinite(number)) return strike;
  if (Number.isInteger(number)) return String(number);
  return String(number);
}

/** Desk label, for example `NIFTY 24500 CE`. Other symbols stay as written. */
export function deskContractName(symbol: string): string {
  const text = symbol.trim().toUpperCase().split(/\s+/).filter(Boolean).join(" ");
  if (!text) return "";
  const spaced = DESK_OPTION.exec(text);
  if (spaced) return `${spaced[1]} ${plainStrike(spaced[2])} ${spaced[3]}`;
  const compact = COMPACT_OPTION.exec(text.replace(/ /g, ""));
  if (compact) return `${compact[1]} ${plainStrike(compact[5])} ${compact[6]}`;
  return text;
}

export function missingLotRefusal(contract: string): string {
  return (
    `Not placed. The lot size for ${contract} isn't in the instrument master, `
    + "so this order can't be sized."
  );
}

/** Underlying of a desk symbol, so a compact option still finds its master row. */
export function underlyingOfDisplayedSymbol(symbol: string): string {
  const desk = deskContractName(symbol);
  const spaced = DESK_OPTION.exec(desk);
  if (spaced) return spaced[1];
  const head = desk.split(/[^A-Z0-9&]/)[0] ?? "";
  return head;
}

/**
 * Near-month lot for the symbol's underlying, or null when that underlying
 * is not in the shared lookup. A stock the excerpt does not list stays null
 * so the caller can keep the symbol-info lot.
 */
export function lotSizeForDisplayedSymbol(
  symbol: string,
  rows: ScripRow[] = instrumentLotRows(),
  asOf?: string,
): number | null {
  const underlying = underlyingOfDisplayedSymbol(symbol);
  if (!underlying) return null;
  return lotSizeFromMaster(underlying, rows, asOf);
}

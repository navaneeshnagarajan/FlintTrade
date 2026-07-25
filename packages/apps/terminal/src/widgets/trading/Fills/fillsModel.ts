/**
 * Fills — the canonical fills row model (terminal dedup merge 2.11).
 *
 * One row model for executed fills, merged from three ancestor surfaces:
 *   - TradeBook: broker tradebook parsing, the qty × price value column and the
 *     honest error/empty states.
 *   - TradeLog: CSV export, symbol search, the stats footer and the badged
 *     Explore sample.
 *   - TradeJournal tool's TradeLogTab: journal enrichment (exchange, entry/exit
 *     prices, realised P&L, fees, strategy) and per-row screenshot annotations.
 *
 * Broker tradebook rows are left-joined with backend auto-journal rows
 * (matched by broker order id, else by exact symbol|side|qty|price), and
 * unmatched journal rows are appended so recorded fills survive a tradebook
 * outage. Where the two stores disagree on a fill fact (qty/price/time), the
 * broker tradebook wins — it is the execution record; the journal is derived
 * from it and only contributes enrichment.
 */

import type { JournalTrade } from "@/services/ftApi";
import type { RawTrade } from "@/types/rawApi";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FillSide = "BUY" | "SELL" | "";

/**
 * Permissive raw tradebook row. ``getTradebook`` types its payload as
 * ``Trade[]`` but passes broker rows through unnormalised, so real rows carry
 * whichever field names the broker uses — the same reason TradeBook parsed
 * via ``RawTrade``. Extended here with the order-id and exchange aliases the
 * join needs.
 */
export interface RawFillSource extends RawTrade {
  exchange?: string;
  orderid?: string | number;
  order_id?: string | number;
  orderId?: string | number;
  tradeid?: string | number;
  trade_id?: string | number;
  tradeId?: string | number;
}

export interface FillRow {
  /** Display/export id — the broker order id when known. */
  id: string;
  /** Broker order id used for the tradebook↔journal join (null when absent). */
  orderId: string | null;
  timeSortMs: number;
  dateDisplay: string;
  timeDisplay: string;
  symbol: string;
  exchange: string | null;
  side: FillSide;
  qty: number;
  price: number;
  /** qty × price — the TradeBook value column. */
  value: number;
  // --- journal enrichment (null when no journal row backs this fill) ---
  entryPrice: number | null;
  exitPrice: number | null;
  /** Realised P&L. The auto-journal records it on the closing leg only. */
  pnl: number | null;
  fees: number | null;
  strategy: string | null;
  /**
   * Stable screenshot key (``timestamp|symbol|orderid-or-na``) — set only for
   * journal-backed rows, computed from the journal row's own fields so
   * screenshots attached through the Trade Journal tool keep matching.
   */
  tradeKey: string | null;
  /** Journal identity kept for the legacy screenshot-key fallback. */
  journalTimestamp: string | null;
  journalSymbol: string | null;
}

export interface FillStats {
  fills: number;
  /** Direct sum of per-row realised P&L — see {@link computeFillStats}. */
  realisedPnl: number;
  /** Sum of known fees; null when no row carried fee data. */
  totalFees: number | null;
}

// ---------------------------------------------------------------------------
// Parsing helpers
// ---------------------------------------------------------------------------

interface ParsedFillTime {
  dateDisplay: string;
  timeDisplay: string;
  ms: number;
}

/** Parse a fill timestamp into IST date + time displays and a sortable ms. */
export function parseFillTime(raw: string): ParsedFillTime {
  if (!raw) return { dateDisplay: "—", timeDisplay: "—", ms: 0 };
  const d = new Date(raw);
  if (!isNaN(d.getTime())) {
    return {
      dateDisplay: d.toLocaleDateString("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "2-digit",
        month: "short",
        year: "2-digit",
      }),
      timeDisplay: d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }),
      ms: d.getTime(),
    };
  }
  // Unparseable broker time strings still show their leading HH:MM:SS.
  return { dateDisplay: "—", timeDisplay: String(raw).slice(0, 8), ms: 0 };
}

function resolveSide(t: RawFillSource): FillSide {
  const side = (t.action ?? t.transaction_type ?? t.side ?? "").toUpperCase();
  return side === "BUY" || side === "SELL" ? side : "";
}

function resolveOrderId(t: RawFillSource): string | null {
  const oid = t.orderid ?? t.order_id ?? t.orderId ?? null;
  if (oid == null) return null;
  const s = String(oid).trim();
  return s.length > 0 ? s : null;
}

/**
 * Stable screenshot key for a journal row — byte-identical to the Trade
 * Journal tool's ``stableTradeKey`` so existing backend screenshot rows keep
 * matching after the merge.
 */
export function stableTradeKey(trade: JournalTrade): string {
  return `${trade.timestamp}|${trade.symbol}|${trade.orderid ?? "na"}`;
}

/**
 * Legacy screenshot key (``timestamp-symbol-idx``, idx = the row's position in
 * the rendered newest-first list) — the pre-backend localStorage shape, kept
 * so imported screenshots keep matching where they matched before.
 */
export function legacyFillKey(row: FillRow, idx: number): string | null {
  if (row.journalTimestamp === null || row.journalSymbol === null) return null;
  return `${row.journalTimestamp}-${row.journalSymbol}-${idx}`;
}

// ---------------------------------------------------------------------------
// Row builders
// ---------------------------------------------------------------------------

/** Map raw broker tradebook rows to un-enriched fill rows. */
export function tradebookToFills(raw: RawFillSource[]): FillRow[] {
  return raw.map((t, i) => {
    const side = resolveSide(t);
    const qty = parseInt(String(t.quantity ?? t.qty ?? t.filled_quantity ?? 0), 10);
    const price = parseFloat(String(t.average_price ?? t.price ?? t.trade_price ?? 0));
    const { dateDisplay, timeDisplay, ms } = parseFillTime(
      t.trade_time ?? t.timestamp ?? t.order_time ?? "",
    );
    const orderId = resolveOrderId(t);
    return {
      id: orderId ?? `T${i}`,
      orderId,
      timeSortMs: ms,
      dateDisplay,
      timeDisplay,
      symbol: ((t.symbol ?? t.tradingsymbol) || "—").toUpperCase(),
      exchange: typeof t.exchange === "string" && t.exchange.length > 0 ? t.exchange : null,
      side,
      qty,
      price,
      value: qty * price,
      entryPrice: null,
      exitPrice: null,
      pnl: null,
      fees: null,
      strategy: null,
      tradeKey: null,
      journalTimestamp: null,
      journalSymbol: null,
    };
  });
}

/**
 * Map backend auto-journal rows to fill rows. The journal is a fills log —
 * every row is an executed fill; nothing is fabricated for missing fields:
 * a zero entry/exit price or fee means "not recorded" and maps to null, and
 * an empty strategy stays null rather than defaulting to "manual" (the
 * retired TradeLog widget invented that label; the Trade Journal tool did
 * not — the tool's honest behaviour wins).
 */
export function journalToFills(rows: JournalTrade[]): FillRow[] {
  return rows.map((r, i) => {
    const { dateDisplay, timeDisplay, ms } = parseFillTime(r.timestamp);
    return {
      id: r.orderid ?? `J${i}-${r.timestamp ?? ""}`,
      orderId: r.orderid ?? null,
      timeSortMs: ms,
      dateDisplay,
      timeDisplay,
      symbol: (r.symbol || "—").toUpperCase(),
      exchange: r.exchange || null,
      side: String(r.action).toUpperCase() === "SELL" ? "SELL" : "BUY",
      qty: r.quantity,
      price: r.price,
      value: r.quantity * r.price,
      entryPrice: r.entry_price > 0 ? r.entry_price : null,
      exitPrice: r.exit_price > 0 ? r.exit_price : null,
      pnl: typeof r.pnl === "number" ? r.pnl : null,
      fees: r.fees > 0 ? r.fees : null,
      strategy: r.strategy || null,
      tradeKey: stableTradeKey(r),
      journalTimestamp: r.timestamp,
      journalSymbol: r.symbol,
    };
  });
}

function compositeKey(symbol: string, side: FillSide, qty: number, price: number): string {
  return `${symbol.toUpperCase()}|${side}|${qty}|${price}`;
}

/**
 * Union of broker tradebook rows and backend auto-journal rows, newest first.
 *
 * Journal rows are matched to tradebook rows by broker order id first, then by
 * exact symbol|side|qty|price (each journal row is consumed at most once). A
 * matched pair keeps the tradebook's fill facts and takes the journal's
 * enrichment; unmatched rows from either side are kept as-is so the table
 * degrades to whichever store is available.
 */
export function buildFillRows(
  bookRaw: RawFillSource[],
  journalRows: JournalTrade[],
): FillRow[] {
  const book = tradebookToFills(bookRaw);
  const journal = journalToFills(journalRows);

  const consumed = new Set<number>();
  const byOrderId = new Map<string, number>();
  const byComposite = new Map<string, number[]>();
  journal.forEach((j, i) => {
    if (j.orderId !== null && !byOrderId.has(j.orderId.toUpperCase())) {
      byOrderId.set(j.orderId.toUpperCase(), i);
    }
    const key = compositeKey(j.symbol, j.side, j.qty, j.price);
    const bucket = byComposite.get(key);
    if (bucket) bucket.push(i);
    else byComposite.set(key, [i]);
  });

  const takeMatch = (b: FillRow): number | undefined => {
    if (b.orderId !== null) {
      const i = byOrderId.get(b.orderId.toUpperCase());
      if (i !== undefined && !consumed.has(i)) return i;
    }
    const bucket = byComposite.get(compositeKey(b.symbol, b.side, b.qty, b.price));
    return bucket?.find((i) => !consumed.has(i));
  };

  const merged: FillRow[] = book.map((b) => {
    const i = takeMatch(b);
    if (i === undefined) return b;
    consumed.add(i);
    const j = journal[i];
    return {
      ...b,
      // The journal often carries the exchange the raw tradebook row omits.
      exchange: b.exchange ?? j.exchange,
      entryPrice: j.entryPrice,
      exitPrice: j.exitPrice,
      pnl: j.pnl,
      fees: j.fees,
      strategy: j.strategy,
      tradeKey: j.tradeKey,
      journalTimestamp: j.journalTimestamp,
      journalSymbol: j.journalSymbol,
    };
  });

  journal.forEach((j, i) => {
    if (!consumed.has(i)) merged.push(j);
  });

  return merged.sort((a, b) => b.timeSortMs - a.timeSortMs);
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

/**
 * Aggregate stats over a set of fills.
 *
 * Realised P&L is a DIRECT SUM: the backend auto-journal records realised P&L
 * on the closing leg only (opening legs carry 0), so no halving is ever
 * applied. The retired TradeLog widget divided by two to compensate for a
 * sample fixture that repeated the round-trip P&L on both legs; that fixture
 * shape is gone — {@link SAMPLE_FILLS} follows the backend convention — and
 * with it the ``pairedPnl`` parameter and the halving path.
 */
export function computeFillStats(rows: FillRow[]): FillStats {
  const realisedPnl = rows.reduce((s, r) => s + (r.pnl ?? 0), 0);
  const feeRows = rows.filter((r) => r.fees !== null);
  const totalFees =
    feeRows.length > 0 ? feeRows.reduce((s, r) => s + (r.fees ?? 0), 0) : null;
  return { fills: rows.length, realisedPnl, totalFees };
}

// ---------------------------------------------------------------------------
// CSV export
// ---------------------------------------------------------------------------

function csvField(value: string | number | null): string {
  if (value === null) return "";
  const s = String(value);
  // Minimal RFC-4180 quoting — the retired TradeLog joined naively, so a
  // strategy name containing a comma silently shifted every later column.
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Serialise fills to CSV — the union of all three ancestors' columns. */
export function fillsToCsv(rows: FillRow[]): string {
  const header = [
    "Date", "Time", "Symbol", "Exchange", "Side", "Qty", "Price", "Value",
    "Entry", "Exit", "P&L", "Fees", "Strategy",
  ];
  const lines = rows.map((r) =>
    [
      r.dateDisplay,
      r.timeDisplay,
      r.symbol,
      r.exchange,
      r.side,
      r.qty,
      r.price,
      r.value,
      r.entryPrice,
      r.exitPrice,
      r.pnl,
      r.fees,
      r.strategy,
    ]
      .map(csvField)
      .join(","),
  );
  return [header.join(","), ...lines].join("\n");
}

/** Trigger a browser download of the given fills as CSV. */
export function downloadFillsCsv(rows: FillRow[]): void {
  const blob = new Blob([fillsToCsv(rows)], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `fills-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Explore sample fixture
// ---------------------------------------------------------------------------

function sampleFill(
  id: string,
  iso: string,
  symbol: string,
  side: FillSide,
  qty: number,
  price: number,
  strategy: string,
  enrichment?: { entry: number; exit: number; pnl: number; fees: number },
): FillRow {
  const { dateDisplay, timeDisplay, ms } = parseFillTime(iso);
  return {
    id,
    orderId: id,
    timeSortMs: ms,
    dateDisplay,
    timeDisplay,
    symbol,
    exchange: "NFO",
    side,
    qty,
    price,
    value: qty * price,
    entryPrice: enrichment?.entry ?? null,
    exitPrice: enrichment?.exit ?? null,
    pnl: enrichment?.pnl ?? null,
    fees: enrichment?.fees ?? null,
    strategy,
    // Sample rows are fabricated — they are never screenshot-annotatable.
    tradeKey: null,
    journalTimestamp: null,
    journalSymbol: null,
  };
}

/**
 * Explore-mode sample fills, shown only behind the visible "Sample data"
 * badge.
 *
 * Fixture semantics (deliberate, pinned by tests):
 *   - Every row is an executed fill — the retired TradeLog's rejected and
 *     cancelled *orders* are gone (a rejected order never filled; order
 *     statuses belong to the Order Book widget).
 *   - Realised P&L, entry/exit prices and fees sit on the CLOSING leg only,
 *     exactly as the backend auto-journal records them (opening legs carry
 *     none), so totals are a direct sum with no halving.
 */
export const SAMPLE_FILLS: readonly FillRow[] = [
  sampleFill("S001", "2026-04-13T09:17:32+05:30", "NIFTY 22200 CE", "BUY", 50, 138.5, "Scalper"),
  sampleFill("S002", "2026-04-13T09:35:14+05:30", "NIFTY 22200 CE", "SELL", 50, 193.5, "Scalper", {
    entry: 138.5, exit: 193.5, pnl: 2750, fees: 42.5,
  }),
  sampleFill("S003", "2026-04-13T10:02:08+05:30", "BANKNIFTY FUT", "BUY", 15, 48150, "Momentum"),
  sampleFill("S004", "2026-04-13T10:48:55+05:30", "BANKNIFTY FUT", "SELL", 15, 48525, "Momentum", {
    entry: 48150, exit: 48525, pnl: 5625, fees: 68,
  }),
  sampleFill("S005", "2026-04-13T11:22:44+05:30", "NIFTY 22100 PE", "BUY", 100, 65.5, "Manual"),
  sampleFill("S006", "2026-04-13T11:48:30+05:30", "NIFTY 22100 PE", "SELL", 100, 56.6, "Manual", {
    entry: 65.5, exit: 56.6, pnl: -890, fees: 35.2,
  }),
  sampleFill("S007", "2026-04-13T13:30:17+05:30", "NIFTY FUT", "BUY", 50, 22380, "Scalper"),
  sampleFill("S008", "2026-04-13T14:55:42+05:30", "NIFTY FUT", "SELL", 50, 22444, "Scalper", {
    entry: 22380, exit: 22444, pnl: 3200, fees: 55,
  }),
].sort((a, b) => b.timeSortMs - a.timeSortMs);

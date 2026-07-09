/**
 * Annotated trade-journal REST client for the FlintTrade backend.
 *
 * Talks to the SQLite + FTS5 annotated journal store exposed under
 * ``/api/v1/journal/*``. Distinct from the auto-journalled broker fills served
 * by :func:`getTradeJournal` (``trades/journal``) in :mod:`ftApi.data` — this
 * store holds the operator's own annotated entries (notes, tags, setup and
 * execution quality, emotions) with full-text search.
 *
 * All calls go through the shared ``/api/v1`` helpers so auth headers and the
 * ``{status, data}`` envelope unwrapping behave exactly like every other
 * FT-API caller.
 */

import { buildHeaders, del, get, getBase, patch, post } from "./ftApi.helpers";

// ---------------------------------------------------------------------------
// Types (mirror the backend contract exactly)
// ---------------------------------------------------------------------------

export type JournalSide = "BUY" | "SELL";

export interface JournalEntry {
  id: string;
  symbol: string;
  exchange: string;
  side: JournalSide;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  entry_time: string | null;
  exit_time: string | null;
  strategy: string | null;
  tags: string[];
  notes: string | null;
  screenshot_path: string | null;
  emotion_before: string | null;
  emotion_after: string | null;
  setup_quality: number | null;
  execution_quality: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  risk_reward_ratio: number | null;
  created_at: string;
  updated_at: string;
}

export interface JournalStats {
  total_entries: number;
  closed_entries: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  avg_pnl: number;
  total_pnl: number;
  best_trade_pnl: number | null;
  worst_trade_pnl: number | null;
  avg_setup_quality: number | null;
  avg_execution_quality: number | null;
  by_strategy: Record<string, number>;
  by_day_of_week: Record<string, number>;
}

export interface JournalListResponse {
  entries: JournalEntry[];
  total: number;
}

export interface JournalListParams {
  start_date?: string;
  end_date?: string;
  symbol?: string;
  strategy?: string;
  side?: JournalSide;
  tags?: string[];
  limit?: number;
  offset?: number;
}

/**
 * Payload accepted on create/update. Only ``symbol``, ``exchange``, ``side``,
 * ``quantity`` and ``entry_price`` are required on create; the backend strips
 * any client-sent ``id``/``created_at``/``updated_at`` and auto-computes
 * ``pnl``/``pnl_pct`` when ``exit_price`` is present.
 */
export interface JournalEntryInput {
  symbol: string;
  exchange: string;
  side: JournalSide;
  quantity: number;
  entry_price: number;
  exit_price?: number | null;
  entry_time?: string | null;
  exit_time?: string | null;
  strategy?: string | null;
  tags?: string[];
  notes?: string | null;
  screenshot_path?: string | null;
  emotion_before?: string | null;
  emotion_after?: string | null;
  setup_quality?: number | null;
  execution_quality?: number | null;
}

export type JournalEntryUpdate = Partial<JournalEntryInput>;

export interface JournalSearchParams {
  q: string;
  limit?: number;
  offset?: number;
}

export interface JournalImportResult {
  created: string[];
  count: number;
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

/** List entries (newest-first) with optional date/symbol/strategy/side/tag filters. */
export const listJournalEntries = (
  params: JournalListParams = {},
): Promise<JournalListResponse> => {
  const qs = new URLSearchParams();
  if (params.start_date) qs.set("start_date", params.start_date);
  if (params.end_date) qs.set("end_date", params.end_date);
  if (params.symbol) qs.set("symbol", params.symbol);
  if (params.strategy) qs.set("strategy", params.strategy);
  if (params.side) qs.set("side", params.side);
  if (params.tags && params.tags.length > 0) qs.set("tags", params.tags.join(","));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return get<JournalListResponse>("journal/entries" + (q ? "?" + q : ""));
};

/** Fetch a single entry by id. */
export const getJournalEntry = (id: string): Promise<JournalEntry> =>
  get<JournalEntry>("journal/entries/" + encodeURIComponent(id));

/** Create a new entry. */
export const createJournalEntry = (body: JournalEntryInput): Promise<JournalEntry> =>
  post<JournalEntry>("journal/entries", body);

/** Partially update an existing entry. */
export const updateJournalEntry = (
  id: string,
  body: JournalEntryUpdate,
): Promise<JournalEntry> =>
  patch<JournalEntry>("journal/entries/" + encodeURIComponent(id), body);

/** Delete an entry; resolves with the deleted id. */
export const deleteJournalEntry = (id: string): Promise<{ deleted: string }> =>
  del<{ deleted: string }>("journal/entries/" + encodeURIComponent(id));

/** Full-text (FTS-ranked) search across entries. */
export const searchJournalEntries = (
  params: JournalSearchParams,
): Promise<JournalListResponse> => {
  const qs = new URLSearchParams({ q: params.q });
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  return get<JournalListResponse>("journal/search?" + qs.toString());
};

/** Aggregate performance statistics over an optional date window. */
export const getJournalStats = (
  startDate?: string,
  endDate?: string,
): Promise<JournalStats> => {
  const qs = new URLSearchParams();
  if (startDate) qs.set("start_date", startDate);
  if (endDate) qs.set("end_date", endDate);
  const q = qs.toString();
  return get<JournalStats>("journal/stats" + (q ? "?" + q : ""));
};

/** Bulk-import entries; resolves with the created ids and count. */
export const importJournalEntries = (
  trades: JournalEntryInput[],
): Promise<JournalImportResult> =>
  post<JournalImportResult>("journal/import", { trades });

/**
 * Absolute URL of the CSV export endpoint (``text/csv`` attachment).
 *
 * Resolves correctly in dev (``/ft-api/api/v1/journal/export``) and prod
 * (``/api/v1/journal/export``). Note that a plain anchor cannot attach the
 * FT-API auth headers, so prefer {@link fetchJournalCsv} for the actual
 * download in an authenticated session.
 */
export const journalExportUrl = (): string => `${getBase()}/api/v1/journal/export`;

/**
 * Fetch the CSV export with the FT-API auth headers attached and resolve the
 * response body as a {@link Blob} ready for a browser download. Browser
 * anchors cannot set headers, so this auth-aware fetch is the safe path.
 */
export async function fetchJournalCsv(): Promise<Blob> {
  const resp = await fetch(journalExportUrl(), { headers: buildHeaders(false) });
  if (!resp.ok) {
    throw new Error(`Journal export failed: HTTP ${resp.status}`);
  }
  return resp.blob();
}

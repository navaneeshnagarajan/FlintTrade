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

import { buildHeaders, del, get, getBase, patch, post, put } from "./ftApi.helpers";

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

/**
 * A single day's free-form trading notes, keyed by the IST trading day
 * (``YYYY-MM-DD``). A missing note is served as ``content: ""`` with a null
 * ``updated_at`` (HTTP 200), so callers never need a 404 branch.
 */
export interface DailyNote {
  date: string;
  content: string;
  updated_at: string | null;
}

/**
 * Metadata for a chart screenshot attached to a trade-log row — the shape the
 * list endpoint returns (no image bytes). ``trade_key`` is the stable row key
 * (``timestamp|symbol|orderid``) for new attaches, or an opaque legacy key
 * imported verbatim from the localStorage era.
 */
export interface JournalScreenshotMeta {
  id: string;
  trade_key: string;
  content_type: string;
  size: number;
  created_at: string;
}

/**
 * A full screenshot row — metadata plus ``data_url``, the re-encoded
 * ``data:image/...;base64,`` payload ready for an ``<img src>``. Served by
 * {@link getJournalScreenshot} (per-id) and by the attach POST response.
 */
export interface JournalScreenshot extends JournalScreenshotMeta {
  data_url: string;
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

// ---------------------------------------------------------------------------
// Daily notes (backend-persisted; replaces the localStorage-only NotesTab)
// ---------------------------------------------------------------------------

/**
 * Fetch the note for one IST trading day (``YYYY-MM-DD``). A day without a
 * note resolves to ``{date, content: "", updated_at: null}`` — never a 404.
 */
export const getDailyNote = (date: string): Promise<DailyNote> =>
  get<DailyNote>("journal/notes/" + encodeURIComponent(date));

/**
 * Upsert the note for one IST trading day; empty ``content`` deletes the
 * stored row (the backend still returns the empty record).
 */
export const putDailyNote = (date: string, content: string): Promise<DailyNote> =>
  put<DailyNote>("journal/notes/" + encodeURIComponent(date), { content });

// ---------------------------------------------------------------------------
// Trade-log screenshots (backend-persisted; replaces the localStorage map)
// ---------------------------------------------------------------------------

/**
 * List every stored screenshot's metadata — NO image bytes. At the 25-image
 * cap the old ``data_url``-embedding listing weighed tens of MB per refetch;
 * fetch bytes lazily per thumbnail via {@link getJournalScreenshot} instead.
 * (The backend still serves the old shape under ``?include_data=1`` for
 * compatibility, deliberately unused here.)
 */
export const listJournalScreenshots = (): Promise<JournalScreenshotMeta[]> =>
  get<JournalScreenshotMeta[]>("journal/screenshots");

/**
 * Fetch one screenshot row WITH its ``data_url``. Screenshot bytes are
 * immutable (rows are only ever created or deleted, never edited), so callers
 * can cache the result indefinitely.
 */
export const getJournalScreenshot = (id: string): Promise<JournalScreenshot> =>
  get<JournalScreenshot>("journal/screenshots/" + encodeURIComponent(id));

/**
 * Attach a screenshot (base64 data URL, ≤ 2 MiB decoded) to a trade-log row.
 * The backend dedupes on ``(trade_key, content_sha256)`` and returns the
 * existing row on a repeat POST, so retries and re-imports are safe.
 */
export const addJournalScreenshot = (
  tradeKey: string,
  dataUrl: string,
): Promise<JournalScreenshot> =>
  post<JournalScreenshot>("journal/screenshots", {
    trade_key: tradeKey,
    data_url: dataUrl,
  });

/** Delete a stored screenshot (row + file); resolves on 200, throws on 404. */
export const deleteJournalScreenshot = (id: string): Promise<{ deleted: string }> =>
  del<{ deleted: string }>("journal/screenshots/" + encodeURIComponent(id));

/**
 * Absolute URL of the CSV export endpoint (``text/csv`` attachment).
 *
 * Resolves correctly in dev (``/ft-api/api/v1/journal/export``) and prod
 * (``/api/v1/journal/export``). Deliberately module-private: a plain anchor
 * cannot attach the FT-API auth headers, so every caller must go through
 * {@link fetchJournalCsv} rather than linking the bare URL.
 */
const journalExportUrl = (): string => `${getBase()}/api/v1/journal/export`;

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

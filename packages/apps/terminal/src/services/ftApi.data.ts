import { get, getBase, buildHeaders } from "./ftApi.helpers";

// ─── Order Flow ───────────────────────────────────────────────────────────────

export interface OrderFlowCell {
  buy_volume: number;
  sell_volume: number;
}

export type OrderFlowQuality = "exact" | "estimated" | "sample" | "unknown";

export type OrderFlowProvenance =
  | "trade_tick"
  | "cumulative_quote_delta"
  | "synthetic"
  | "mixed"
  | "unknown";

export interface OrderFlowBucket {
  time_label: string;
  cells: Record<string, OrderFlowCell>;
  poc_price: number;
  total_volume: number;
  delta: number;
  quality: OrderFlowQuality;
  provenance: OrderFlowProvenance;
}

export interface OrderFlowResponse {
  buckets: OrderFlowBucket[];
  symbol: string;
  exchange: string;
  interval: number;
  /** True only when aggregator buckets are fresh for the current session. */
  is_live: boolean;
  /** Explicit backend provenance; true always overrides a contradictory live flag. */
  is_sample_data?: boolean;
  quality: OrderFlowQuality;
  provenance: OrderFlowProvenance;
  tick_size?: number;
  requested_tick_size?: number;
  source_tick_size?: number;
  /** Freshness classification for live or retained real buckets. */
  live_state?: "live" | "delayed" | "stale" | "warming" | "unavailable";
  freshness?: {
    state: "live" | "delayed" | "stale" | "unavailable";
    is_fresh: boolean;
    last_tick_timestamp: number | null;
    last_tick_session: string | null;
    current_session: string | null;
    age_seconds: number | null;
  };
}

export type OrderFlowDataState = "live" | "delayed" | "stale" | "sample";

export interface OrderFlowQualitySummary {
  quality: OrderFlowQuality;
  provenance: OrderFlowProvenance;
}

export function getOrderFlowDataState(
  data: Pick<OrderFlowResponse, "is_live" | "is_sample_data" | "live_state"> | undefined,
): OrderFlowDataState {
  if (data?.is_sample_data === true) return "sample";
  if (data?.is_live) return "live";
  if (data?.live_state === "delayed" || data?.live_state === "stale") {
    return data.live_state;
  }
  return "sample";
}

/** Conservatively reconcile response and per-bucket source metadata for display. */
export function getOrderFlowQualitySummary(
  data: OrderFlowResponse | undefined,
): OrderFlowQualitySummary {
  if (!data) return { quality: "unknown", provenance: "unknown" };

  const qualities = [data.quality, ...data.buckets.map((bucket) => bucket.quality)]
    .filter((quality): quality is OrderFlowQuality => Boolean(quality));
  let quality: OrderFlowQuality;
  if (data.is_sample_data === true || qualities.includes("sample")) {
    quality = "sample";
  } else if (qualities.length === 0 && getOrderFlowDataState(data) === "sample") {
    // Mixed-version fallback: old synthetic responses only exposed is_live=false.
    quality = "sample";
  } else if (qualities.length === 0 || qualities.includes("unknown")) {
    quality = "unknown";
  } else if (qualities.includes("estimated")) {
    quality = "estimated";
  } else if (qualities.every((candidate) => candidate === "exact")) {
    quality = "exact";
  } else {
    quality = "unknown";
  }

  const provenances = [data.provenance, ...data.buckets.map((bucket) => bucket.provenance)]
    .filter((provenance): provenance is OrderFlowProvenance => Boolean(provenance));
  let provenance: OrderFlowProvenance;
  if (provenances.length === 0 || provenances.includes("unknown")) {
    provenance = "unknown";
  } else if (provenances.includes("mixed") || new Set(provenances).size > 1) {
    provenance = "mixed";
  } else {
    provenance = provenances[0];
  }

  return { quality, provenance };
}

export const getOrderFlow = (
  symbol: string,
  exchange = "NFO",
  bins = 50,
  interval = 300,
  tickSize: number,
) => {
  const params = new URLSearchParams({
    symbol,
    exchange,
    bins: String(bins),
    interval: String(interval),
    tick_size: String(tickSize),
  });
  return get<OrderFlowResponse>(`data/orderflow?${params.toString()}`);
};

// ─── Trade Journal ────────────────────────────────────────────────────────────

export interface JournalTrade {
  timestamp: string;
  /** Broker order id of the fill (present on backend-journalled rows). */
  orderid?: string;
  symbol: string;
  exchange: string;
  action: string;
  quantity: number;
  price: number;
  /** Product code (MIS/NRML/CNC) — present on backend-journalled rows. */
  product?: string;
  pnl: number;
  strategy: string;
  entry_price: number;
  exit_price: number;
  fees: number;
}

export interface NewsArticle {
  title: string;
  link: string;
  pub_date: string;
  source: string;
}

export interface HistoricalOptionRow {
  captured_at: string;
  symbol: string;
  exchange: string;
  expiry_date: string;
  strike: number;
  option_type: "CE" | "PE";
  oi: number;
  volume: number;
  ltp: number;
  iv: number;
}

export interface OHLCVBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export const getTradeJournal = (
  startDate?: string,
  endDate?: string,
  strategy?: string,
  limit?: number,
) => {
  const params = new URLSearchParams();
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  if (strategy) params.set("strategy", strategy);
  if (limit !== undefined) params.set("limit", String(limit));
  const qs = params.toString();
  return get<{ trades: JournalTrade[]; total: number }>(
    "trades/journal" + (qs ? "?" + qs : ""),
  );
};

export const getNews = () => get<{ articles: NewsArticle[] }>("news");

export const getHistoricalExpiries = (symbol: string, exchange?: string) => {
  const params = new URLSearchParams();
  if (exchange) params.set("exchange", exchange);
  const qs = params.toString();
  return get<{ symbol: string; exchange: string; expiries: string[] }>(
    "historical/expiries/" + encodeURIComponent(symbol) + (qs ? "?" + qs : ""),
  );
};

export const getHistoricalChain = (
  symbol: string,
  expiry: string,
  exchange?: string,
) => {
  const params = new URLSearchParams();
  if (exchange) params.set("exchange", exchange);
  const qs = params.toString();
  return get<{
    symbol: string;
    expiry: string;
    exchange: string;
    chain: HistoricalOptionRow[];
  }>(
    "historical/chain/" +
      encodeURIComponent(symbol) +
      "/" +
      encodeURIComponent(expiry) +
      (qs ? "?" + qs : ""),
  );
};

/**
 * Export rows to Excel and trigger a real browser download.
 *
 * Unlike a server-side file export (which writes an `.xlsx` on the host and
 * returns its path — useless to a browser SPA), this hits the streaming
 * `/export/download` endpoint and saves the `.xlsx` straight to the user's
 * machine via a Blob — working in the browser and the desktop shell alike.
 * Returns the number of rows exported.
 *
 * @throws Error when the request fails or there are no rows to export.
 */
export async function downloadExcel(
  data: Record<string, unknown>[],
  sheetName = "Data",
  filename = "export.xlsx",
): Promise<number> {
  if (data.length === 0) throw new Error("Nothing to export — no rows.");
  const name = filename.endsWith(".xlsx") ? filename : `${filename}.xlsx`;

  const resp = await fetch(`${getBase()}/api/v1/integration/excel/export/download`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify({ data, sheet_name: sheetName, filename: name }),
  });
  if (!resp.ok) {
    const msg = await resp.json().then((b) => b?.message).catch(() => null);
    throw new Error(msg ?? `Excel export failed (HTTP ${resp.status})`);
  }

  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
  return data.length;
}

/**
 * Build a multi-sheet portfolio report (Positions / Holdings / Summary) and
 * trigger a browser download. Streams `/portfolio/report/download` — no
 * server-side file. Returns the total row count exported.
 *
 * @throws Error when there is nothing to export or the request fails.
 */
export async function downloadPortfolioReport(
  positions: Record<string, unknown>[],
  holdings: Record<string, unknown>[],
  filename = "portfolio.xlsx",
): Promise<number> {
  if (positions.length === 0 && holdings.length === 0) {
    throw new Error("Nothing to export — no positions or holdings.");
  }
  const name = filename.endsWith(".xlsx") ? filename : `${filename}.xlsx`;

  const resp = await fetch(
    `${getBase()}/api/v1/integration/excel/portfolio/report/download`,
    {
      method: "POST",
      headers: buildHeaders(true),
      body: JSON.stringify({ positions, holdings, filename: name }),
    },
  );
  if (!resp.ok) {
    const msg = await resp.json().then((b) => b?.message).catch(() => null);
    throw new Error(msg ?? `Portfolio report failed (HTTP ${resp.status})`);
  }

  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
  return positions.length + holdings.length;
}

/**
 * Import tabular rows from a user-selected `.xlsx` file.
 *
 * Streams the file to the multipart `/import/upload` endpoint (the server-path
 * `/import` variant is useless to a browser SPA) and returns the parsed rows —
 * the sheet's first row as headers, one object per data row.
 *
 * When `sheetName` is omitted the backend reads the workbook's FIRST sheet,
 * whatever it is called — so exports from FlintTrade (sheet "Data") and most
 * real-world workbooks import without the operator knowing sheet names.
 *
 * No Content-Type header is set: the browser supplies the multipart boundary.
 *
 * @throws Error when the request fails or the workbook cannot be parsed.
 */
export async function uploadExcel(
  file: File,
  sheetName?: string,
): Promise<Record<string, unknown>[]> {
  const form = new FormData();
  form.append("file", file);
  if (sheetName) form.append("sheet_name", sheetName);

  const resp = await fetch(`${getBase()}/api/v1/integration/excel/import/upload`, {
    method: "POST",
    headers: buildHeaders(false),
    body: form,
  });
  if (!resp.ok) {
    const msg = await resp.json().then((b) => b?.message).catch(() => null);
    throw new Error(msg ?? `Excel import failed (HTTP ${resp.status})`);
  }

  const body = (await resp.json()) as { data?: { rows?: Record<string, unknown>[] } };
  return body.data?.rows ?? [];
}

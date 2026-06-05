import { get, post } from "./ftApi.helpers";

// ─── Order Flow ───────────────────────────────────────────────────────────────

export interface OrderFlowCell {
  buy_volume: number;
  sell_volume: number;
}

export interface OrderFlowBucket {
  time_label: string;
  cells: Record<string, OrderFlowCell>;
  poc_price: number;
  total_volume: number;
  delta: number;
}

export interface OrderFlowResponse {
  buckets: OrderFlowBucket[];
  symbol: string;
  exchange: string;
  interval: number;
  /** True when data comes from the live OrderFlowAggregatorV2, false when synthetic. */
  is_live: boolean;
}

export const getOrderFlow = (
  symbol: string,
  exchange = "NFO",
  bins = 50,
  interval = 300,
) => {
  const params = new URLSearchParams({
    symbol,
    exchange,
    bins: String(bins),
    interval: String(interval),
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

export interface PnLTrackerEntry {
  timestamp: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  trade_count: number;
}

export interface PnLSummary {
  realized: number;
  unrealized: number;
  total: number;
  max_total: number;
  min_total: number;
  trade_count: number;
  data_points: number;
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

export interface QuestDBTick {
  symbol: string;
  exchange: string;
  ltp: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  bid?: number;
  ask?: number;
  oi?: number;
  timestamp?: string;
  timestamp_ns?: number;
}

export interface OHLCVBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ExcelExportResult {
  file_path: string;
  rows: number;
}

export interface ExcelPortfolioReportResult {
  file_path: string;
  positions: number;
  holdings: number;
}

export interface ExcelImportResult {
  rows: Record<string, unknown>[];
  count: number;
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

export const getPnLTracker = () => get<PnLTrackerEntry[]>("pnl-tracker");
export const getPnLSummary = () => get<PnLSummary>("pnl-tracker/summary");

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

export const checkQuestDBHealth = () =>
  get<{ running: boolean }>("data/questdb/health");

export const insertQuestDBTicks = (ticks: QuestDBTick[]) =>
  post<{ inserted: number }>("data/questdb/ticks", { ticks });

export const queryQuestDB = (sql: string) =>
  post<{ rows: Record<string, unknown>[]; count: number }>(
    "data/questdb/query",
    { sql },
  );

export const aggregateQuestDBOHLCV = (
  symbol: string,
  interval: string,
  start: string,
  end: string,
) =>
  post<{ bars: OHLCVBar[]; count: number }>("data/questdb/ohlcv", {
    symbol,
    interval,
    start,
    end,
  });

export const getQuestDBLatestTick = (symbol: string) =>
  get<QuestDBTick>(
    "data/questdb/tick/latest/" + encodeURIComponent(symbol),
  );

export const exportToExcel = (
  data: Record<string, unknown>[],
  sheetName = "Data",
  filename = "export.xlsx",
) =>
  post<ExcelExportResult>("integration/excel/export", {
    data,
    sheet_name: sheetName,
    filename,
  });

export const createPortfolioReport = (
  positions: Record<string, unknown>[],
  holdings: Record<string, unknown>[],
  filename = "portfolio.xlsx",
) =>
  post<ExcelPortfolioReportResult>("integration/excel/portfolio/report", {
    positions,
    holdings,
    filename,
  });

export const importFromExcel = (filePath: string, sheetName = "Sheet1") =>
  post<ExcelImportResult>("integration/excel/import", {
    file_path: filePath,
    sheet_name: sheetName,
  });

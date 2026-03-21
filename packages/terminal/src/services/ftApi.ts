/**
 * FlintTrade Python backend REST API client (TypeScript).
 * Targets port 5001, proxied via /ft-api in dev (see vite.config.ts).
 * No API key injection — the FT backend uses its own auth layer.
 * No client-side rate limiting — the backend enforces its own limits.
 * All responses are unwrapped: { data: X, status: "success" } → X
 */

// ---------------------------------------------------------------------------
// Base URL resolution
// ---------------------------------------------------------------------------

function getBase(): string {
  // In dev mode, Vite proxy routes /ft-api/* → http://127.0.0.1:5001/*
  // In production, the FT backend runs on the same host at /ft-api
  if (import.meta.env.DEV) return "/ft-api";
  return "";
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function post<T>(
  endpoint: string,
  body: Record<string, unknown> = {},
): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  const json: unknown = await resp.json();
  if (
    json !== null &&
    typeof json === "object" &&
    "status" in json &&
    (json as { status: unknown }).status === "error"
  ) {
    const msg =
      "message" in json
        ? String((json as { message: unknown }).message)
        : `FT API ${endpoint} error`;
    throw new Error(msg);
  }
  const data =
    json !== null && typeof json === "object" && "data" in json
      ? (json as { data: unknown }).data
      : json;
  return data as T;
}

async function get<T>(endpoint: string): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`);
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  const json: unknown = await resp.json();
  if (
    json !== null &&
    typeof json === "object" &&
    "status" in json &&
    (json as { status: unknown }).status === "error"
  ) {
    const msg =
      "message" in json
        ? String((json as { message: unknown }).message)
        : `FT API ${endpoint} error`;
    throw new Error(msg);
  }
  const data =
    json !== null && typeof json === "object" && "data" in json
      ? (json as { data: unknown }).data
      : json;
  return data as T;
}

async function del<T>(endpoint: string): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  const json: unknown = await resp.json();
  if (
    json !== null &&
    typeof json === "object" &&
    "status" in json &&
    (json as { status: unknown }).status === "error"
  ) {
    const msg =
      "message" in json
        ? String((json as { message: unknown }).message)
        : `FT API ${endpoint} error`;
    throw new Error(msg);
  }
  const data =
    json !== null && typeof json === "object" && "data" in json
      ? (json as { data: unknown }).data
      : json;
  return data as T;
}

// ---------------------------------------------------------------------------
// Backtest
// ---------------------------------------------------------------------------

export interface BacktestConfig {
  symbol: string;
  exchange: string;
  interval: string;
  start_date: string;
  end_date: string;
  strategy: string;
  initial_capital: number;
  position_size_pct: number;
}

export interface BacktestTrade {
  entry_timestamp: string;
  exit_timestamp: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  commission: number;
  bars_held: number;
}

export interface BacktestMetrics {
  total_return: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  expectancy: number;
}

export interface BacktestResult {
  trades: BacktestTrade[];
  equity_curve: Array<{ timestamp: string; equity: number }>;
  metrics: BacktestMetrics;
  final_equity: number;
  total_bars: number;
}

export const runBacktest = (config: BacktestConfig) =>
  post<BacktestResult>("backtest/run", config as unknown as Record<string, unknown>);

// ---------------------------------------------------------------------------
// Strategies
// ---------------------------------------------------------------------------

export interface StrategyParameter {
  name: string;
  type: string;
  default: unknown;
}

export interface StrategyInfo {
  name: string;
  description: string;
  category: string;
  parameters: StrategyParameter[];
}

export interface ForwardTrade {
  entry_timestamp: string;
  exit_timestamp: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  commission: number;
}

export interface RunningStrategy {
  name: string;
  symbol: string;
  exchange: string;
  status: string;
  tick_count: number;
  started_at: string;
  virtual_pnl?: number;
  virtual_trades?: ForwardTrade[];
}

export const getStrategies = () => get<StrategyInfo[]>("strategies");

export const getRunningStrategies = () => get<RunningStrategy[]>("strategies/running");

export const startStrategy = (name: string, config: Record<string, unknown>) =>
  post<{ status: string }>(
    "strategies/" + encodeURIComponent(name) + "/start",
    config,
  );

export const stopStrategy = (name: string) =>
  post<{ status: string }>(
    "strategies/" + encodeURIComponent(name) + "/stop",
  );

export const getForwardTrades = (name: string) =>
  get<ForwardTrade[]>(
    "strategies/" + encodeURIComponent(name) + "/trades",
  );

// ---------------------------------------------------------------------------
// Signals
// ---------------------------------------------------------------------------

export interface Signal {
  symbol: string;
  exchange: string;
  signal_type: "BUY" | "SELL" | "HOLD";
  confidence: number;
  timestamp: string;
  indicators: Record<string, number>;
}

export const getActiveSignals = () => get<{ signals: Signal[] }>("signals/active");

// ---------------------------------------------------------------------------
// Sentiment
// ---------------------------------------------------------------------------

export interface SentimentResult {
  score: number;
  label: "bullish" | "bearish" | "neutral";
  confidence: number;
}

export const analyzeSentiment = (text: string) =>
  post<SentimentResult>("sentiment/analyze", { text });

// ---------------------------------------------------------------------------
// RAG / Knowledge Base
// ---------------------------------------------------------------------------

export interface RAGResult {
  content: string;
  source: string;
  score: number;
}

export const queryKnowledge = (query: string, top_k?: number) =>
  post<{ results: RAGResult[] }>("rag/query", {
    query,
    top_k: top_k ?? 5,
  });

// ---------------------------------------------------------------------------
// Cron Jobs
// ---------------------------------------------------------------------------

export interface CronJob {
  name: string;
  description: string;
  trigger_type: string;
  status: string;
  last_run: string | null;
  run_count: number;
  error_count: number;
}

export const getCronJobs = () => get<{ jobs: CronJob[] }>("cron/jobs");

export const pauseCronJob = (name: string) =>
  post<{ status: string }>(
    "cron/jobs/" + encodeURIComponent(name) + "/pause",
  );

export const resumeCronJob = (name: string) =>
  post<{ status: string }>(
    "cron/jobs/" + encodeURIComponent(name) + "/resume",
  );

// ---------------------------------------------------------------------------
// Audit Logs
// ---------------------------------------------------------------------------

export interface AuditLog {
  timestamp: string;
  event_type: string;
  strategy: string;
  symbol: string;
  exchange: string;
  action: string;
  quantity: number;
  price: number;
  layer: string;
  verdict: string;
  reason: string;
}

export const getAuditLogs = (
  date?: string,
  limit?: number,
  offset?: number,
) => {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  const qs = params.toString();
  return get<{ logs: AuditLog[]; total: number }>(
    "audit/logs" + (qs ? "?" + qs : ""),
  );
};

// ---------------------------------------------------------------------------
// Trade Journal
// ---------------------------------------------------------------------------

export interface JournalTrade {
  timestamp: string;
  symbol: string;
  exchange: string;
  action: string;
  quantity: number;
  price: number;
  pnl: number;
  strategy: string;
  entry_price: number;
  exit_price: number;
  fees: number;
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

// ---------------------------------------------------------------------------
// Safety (5-layer safety system + kill switch)
// ---------------------------------------------------------------------------

export interface SafetyConfig {
  check_market_hours: boolean;
  max_qty_nse: number;
  max_qty_nfo: number;
  max_qty_mcx: number;
  max_positions: number;
  max_margin_pct: number;
  max_net_delta: number;
  max_net_vega: number;
  daily_loss_pause_pct: number;
  daily_loss_kill_pct: number;
  kill_switch_active: boolean;
}

export const getSafetyConfig = () => get<SafetyConfig>("safety/config");

export const updateSafetyConfig = (config: Partial<SafetyConfig>) =>
  post<{ status: string }>(
    "safety/config",
    config as Record<string, unknown>,
  );

export const activateKillSwitch = (reason: string) =>
  post<{ status: string }>("safety/kill-switch", { reason });

export const resetKillSwitch = () => del<{ status: string }>("safety/kill-switch");

// ---------------------------------------------------------------------------
// Webhooks
// ---------------------------------------------------------------------------

export interface WebhookConfig {
  id: string;
  path: string;
  name: string;
  type: "tradingview" | "chartink" | "custom";
  enabled: boolean;
  secret: string;
}

export const getWebhooks = () => get<{ webhooks: WebhookConfig[] }>("webhooks");

export const createWebhook = (config: Omit<WebhookConfig, "id">) =>
  post<WebhookConfig>("webhooks", config as unknown as Record<string, unknown>);

export const deleteWebhook = (id: string) =>
  del<{ status: string }>("webhooks/" + encodeURIComponent(id));

// ---------------------------------------------------------------------------
// Indicators (server-side compute via TA-Lib / Numba)
// ---------------------------------------------------------------------------

export interface IndicatorBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export const computeIndicators = (
  bars: IndicatorBar[],
  indicators: string[],
) =>
  post<Record<string, unknown>>("indicators/compute", {
    bars: bars as unknown as Record<string, unknown>[],
    indicators,
  });

/**
 * FlintTrade Python backend REST API client (TypeScript).
 * Targets port 5100, proxied via /ft-api in dev (see vite.config.ts).
 * No API key injection — the FT backend uses its own auth layer.
 * No client-side rate limiting — the backend enforces its own limits.
 * All responses are unwrapped: { data: X, status: "success" } → X
 */

// ---------------------------------------------------------------------------
// Base URL resolution
// ---------------------------------------------------------------------------

function getBase(): string {
  // In dev mode, Vite proxy routes /ft-api/* → http://127.0.0.1:5100/*
  // In production, the FT backend runs on the same host at /ft-api
  if (import.meta.env.DEV) return "/ft-api";
  return "";
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

/** Shared JSON response parser: checks for error status and unwraps `data`. */
async function parseResponse<T>(res: Response, endpoint: string): Promise<T> {
  const json: unknown = await res.json();
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

async function post<T>(
  endpoint: string,
  body: object = {},
): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

async function get<T>(endpoint: string): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`);
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

async function put<T>(
  endpoint: string,
  body: object = {},
): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

async function del<T>(endpoint: string): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

// ---------------------------------------------------------------------------
// Fundamental Screener (Screener.in data, 24h cache)
// ---------------------------------------------------------------------------

export interface FundamentalSearchResult {
  name: string;
  symbol: string;
  url: string;
}

export interface FundamentalData {
  symbol: string;
  company_name: string;
  current_price: number | null;
  market_cap: number | null;
  pe_ratio: number | null;
  pb_ratio: number | null;
  book_value: number | null;
  dividend_yield: number | null;
  roce: number | null;
  roe: number | null;
  face_value: number | null;
  high_low: { high: number | null; low: number | null } | null;
  sales: number | null;
  net_profit: number | null;
  operating_margin: number | null;
  sales_growth_3yr: number | null;
  profit_growth_3yr: number | null;
  promoter_holding: number | null;
  fii_holding: number | null;
  dii_holding: number | null;
  ev_to_ebitda: number | null;
  price_to_sales: number | null;
  sector: string;
  industry: string;
  bse_code: string;
  nse_symbol: string;
  pros: string[];
  cons: string[];
}

export interface FundamentalScreenFilters {
  pe_min?: number;
  pe_max?: number;
  pb_min?: number;
  pb_max?: number;
  market_cap_min?: number;
  market_cap_max?: number;
  roce_min?: number;
  roe_min?: number;
  dividend_yield_min?: number;
  sector?: string;
  sort_by?: string;
  limit?: number;
}

export interface FundamentalStockRow {
  symbol: string;
  name: string;
  exchange: string;
  market_cap: number;
  pe_ratio: number;
  pb_ratio: number;
  roe: number;
  roce: number;
  dividend_yield: number;
  sector: string;
}

export const searchFundamentals = (query: string) =>
  get<{
    query: string;
    results: FundamentalSearchResult[];
    count: number;
  }>("screener/fundamental/search?q=" + encodeURIComponent(query));

export const getFundamentals = (symbol: string) =>
  get<FundamentalData>(
    "screener/fundamental/" + encodeURIComponent(symbol),
  );

export const screenStocks = (filters: FundamentalScreenFilters) =>
  post<{
    stocks: FundamentalStockRow[];
    count: number;
    filters_applied: Record<string, unknown>;
  }>("screener/fundamental/screen", filters);

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
  post<BacktestResult>("backtest/run", config);

// ---------------------------------------------------------------------------
// Portfolio Backtest
// ---------------------------------------------------------------------------

export type AllocationStrategy =
  | "equal_weight"
  | "inverse_volatility"
  | "momentum"
  | "market_cap";

export type RebalanceFreq =
  | "daily"
  | "weekly"
  | "monthly"
  | "quarterly"
  | "yearly";

export interface PortfolioBacktestConfig {
  symbols: string[];
  start_date: string;
  end_date: string;
  allocation_strategy?: AllocationStrategy;
  rebalance_freq?: RebalanceFreq;
  initial_capital?: number;
  benchmark?: string;
  include_benchmark?: boolean;
  momentum_lookback?: number;
  vol_lookback?: number;
  top_n?: number;
}

export interface RebalanceEntry {
  date: string;
  old_weights: Record<string, number>;
  new_weights: Record<string, number>;
  trades: Array<{ symbol: string; delta_shares: number; price: number }>;
}

export interface PortfolioResultData {
  total_return: number;
  annual_return: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  calmar_ratio: number;
  volatility: number;
  var_95: number;
  final_equity: number;
  equity_curve: number[];
  drawdown_curve: number[];
  rebalance_log: RebalanceEntry[];
}

export interface PortfolioBuyHoldData {
  total_return: number;
  annual_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  equity_curve: number[];
  drawdown_curve: number[];
}

export interface PortfolioBenchmarkComparison {
  alpha: number;
  beta: number;
  information_ratio: number;
  buy_hold: PortfolioBuyHoldData;
}

export interface PortfolioBacktestResult {
  result: PortfolioResultData;
  comparison?: PortfolioBenchmarkComparison;
}

export const runPortfolioBacktest = (config: PortfolioBacktestConfig) =>
  post<PortfolioBacktestResult>("backtest/portfolio", config);

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

export const getStrategies = () =>
  get<{ strategies: StrategyInfo[] }>("strategies").then((r) => r.strategies);

export const getRunningStrategies = () =>
  get<{ strategies: RunningStrategy[] }>("strategies/running").then(
    (r) => r.strategies,
  );

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
  get<{ strategy_id: string; trades: ForwardTrade[] }>(
    "strategies/" + encodeURIComponent(name) + "/trades",
  ).then((r) => r.trades);

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
// Live Signals (v0.5.0 — rule-based pipeline)
// ---------------------------------------------------------------------------

export interface LiveSignal {
  timestamp: string;
  symbol: string;
  signal_type: "BUY" | "SELL" | "ALERT";
  indicator: string;
  value: number;
  threshold: number;
  confidence: number;
  message: string;
}

export interface SignalConfig {
  instruments: string[];
  indicators: Array<{ name: string; params: Record<string, number> }>;
  thresholds: Record<string, number>;
}

export const getRecentSignals = (limit?: number) => {
  const qs = limit !== undefined ? `?limit=${limit}` : "";
  return get<{ signals: LiveSignal[] }>("signals/recent" + qs);
};

export const getSignalConfig = () => get<SignalConfig>("signals/config");

export const updateSignalConfig = (config: Partial<SignalConfig>) =>
  post<SignalConfig>("signals/configure", config);

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
// AI Team (multi-agent analysis)
// ---------------------------------------------------------------------------

export interface AgentRoleConfig {
  name: string;
  role_type:
    | "technical"
    | "fundamental"
    | "sentiment"
    | "risk_manager"
    | "aggregator";
  system_prompt: string;
  enabled: boolean;
  temperature: number | null;
}

export interface AgentAnalysisResult {
  agent_name: string;
  role_type: string;
  report: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: number;
  timestamp: string;
  error: string;
}

export interface TeamAnalysisResult {
  symbol: string;
  exchange: string;
  agent_analyses: AgentAnalysisResult[];
  consensus_signal: "BUY" | "SELL" | "HOLD";
  consensus_confidence: number;
  consensus_reasoning: string;
  timestamp: string;
  errors: string[];
}

export interface TeamRecommendation {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  reasoning: string;
  agent_count: number;
  bullish_count: number;
  bearish_count: number;
  neutral_count: number;
  timestamp: string;
}

export interface TeamAnalyzeResponse {
  analysis: TeamAnalysisResult;
  recommendation: TeamRecommendation;
}

export interface TeamConfig {
  agents: AgentRoleConfig[];
}

export const runTeamAnalysis = (
  symbol: string,
  exchange: string,
  market_data?: Record<string, unknown>,
) =>
  post<TeamAnalyzeResponse>("ai/team/analyze", {
    symbol,
    exchange,
    ...(market_data ? { market_data: market_data } : {}),
  });

export const getTeamConfig = () => get<TeamConfig>("ai/team/config");

export const updateTeamConfig = (config: TeamConfig) =>
  post<TeamConfig>("ai/team/config", config);

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

/** Raw nested safety config as returned by the backend (5-layer system). */
export interface SafetyConfigRaw {
  l1_order: { price_deviation_pct: number; check_market_hours: boolean; qty_limits: Record<string, number> };
  l2_position: { max_positions: number; max_margin_pct: number };
  l3_portfolio: { max_net_delta: number; max_net_vega: number };
  l4_pnl: { pause_pct: number; kill_pct: number; is_paused: boolean; is_killed: boolean };
  l5_kill: { is_active: boolean; reason: string };
}

/** Flattened safety config for UI consumption. */
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

/** Flatten the nested backend response into the UI-friendly shape. */
function flattenSafetyConfig(raw: SafetyConfigRaw): SafetyConfig {
  return {
    check_market_hours: raw.l1_order?.check_market_hours ?? true,
    max_qty_nse: raw.l1_order?.qty_limits?.NSE ?? 1800,
    max_qty_nfo: raw.l1_order?.qty_limits?.NFO ?? 1800,
    max_qty_mcx: raw.l1_order?.qty_limits?.MCX ?? 100,
    max_positions: raw.l2_position?.max_positions ?? 10,
    max_margin_pct: raw.l2_position?.max_margin_pct ?? 80,
    max_net_delta: raw.l3_portfolio?.max_net_delta ?? 1000,
    max_net_vega: raw.l3_portfolio?.max_net_vega ?? 500,
    daily_loss_pause_pct: raw.l4_pnl?.pause_pct ?? 2,
    daily_loss_kill_pct: raw.l4_pnl?.kill_pct ?? 5,
    kill_switch_active: raw.l5_kill?.is_active ?? false,
  };
}

export const getSafetyConfig = async (): Promise<SafetyConfig> => {
  const raw = await get<SafetyConfigRaw>("safety/config");
  return flattenSafetyConfig(raw);
};

export const updateSafetyConfig = (config: Partial<SafetyConfig>) => {
  const body: Record<string, unknown> = {};
  if (config.check_market_hours !== undefined) body.check_market_hours = config.check_market_hours;
  if (config.max_positions !== undefined) body.max_positions = config.max_positions;
  if (config.max_margin_pct !== undefined) body.max_margin_pct = config.max_margin_pct;
  if (config.max_net_delta !== undefined) body.max_net_delta = config.max_net_delta;
  if (config.max_net_vega !== undefined) body.max_net_vega = config.max_net_vega;
  if (config.daily_loss_pause_pct !== undefined) body.pnl_pause_pct = config.daily_loss_pause_pct;
  if (config.daily_loss_kill_pct !== undefined) body.pnl_kill_pct = config.daily_loss_kill_pct;
  return post<{ status: string }>("safety/config", body);
};

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
  post<WebhookConfig>("webhooks", config);

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

// ---------------------------------------------------------------------------
// Pine Script Compilation
// ---------------------------------------------------------------------------

export interface PineCompileResult {
  python_code: string;
  imports: string[];
  warnings: string[];
  unsupported: string[];
  supported_functions: string[];
}

export const compilePineScript = (code: string) =>
  post<PineCompileResult>("indicators/pine/compile", { code });

// ---------------------------------------------------------------------------
// Analysis endpoints (SP2)
// ---------------------------------------------------------------------------

import type {
  GEXData,
  VolSurfaceData,
  IVSmileData,
  StraddlePnLData,
  StraddleLeg,
  OIProfileData,
} from "@/types/api";

export const getGEXData = (
  symbol: string,
  exchange: string,
  expiry_date?: string,
) =>
  post<GEXData>("gex", {
    symbol,
    exchange,
    ...(expiry_date ? { expiry_date } : {}),
  });

export const getVolSurface = (
  symbol: string,
  exchange: string,
  expiry_dates: string[],
  strike_count?: number,
) =>
  post<VolSurfaceData>("volsurface", {
    symbol,
    exchange,
    expiry_dates,
    ...(strike_count !== undefined ? { strike_count } : {}),
  });

export const getFtIVSmile = (
  symbol: string,
  exchange: string,
  expiry_dates?: string[],
) =>
  post<IVSmileData>("iv_smile", {
    symbol,
    exchange,
    ...(expiry_dates ? { expiry_dates } : {}),
  });

export const getStraddlePnL = (
  symbol: string,
  exchange: string,
  expiry_date: string,
  adjustments?: StraddleLeg[],
) =>
  post<StraddlePnLData>("straddlepnl", {
    symbol,
    exchange,
    expiry_date,
    ...(adjustments ? { adjustments: adjustments as unknown as Record<string, unknown>[] } : {}),
  });

export const getFtOIProfile = (
  symbol: string,
  exchange: string,
  expiry_date: string,
  strike_count?: number,
) =>
  post<OIProfileData>("oiprofile", {
    symbol,
    exchange,
    expiry_date,
    ...(strike_count !== undefined ? { strike_count } : {}),
  });

// ---------------------------------------------------------------------------
// FII/DII Institutional Flows (absorbed from MarketCalls/fii-dii-data)
// ---------------------------------------------------------------------------

export interface FiiDiiSnapshot {
  trade_date: string;
  fii_buy: number;
  fii_sell: number;
  fii_net: number;
  dii_buy: number;
  dii_sell: number;
  dii_net: number;
  fii_idx_fut_long: number;
  fii_idx_fut_short: number;
  fii_idx_fut_net: number;
  fii_stk_fut_long: number;
  fii_stk_fut_short: number;
  fii_stk_fut_net: number;
  fii_idx_call_long: number;
  fii_idx_call_short: number;
  fii_idx_call_net: number;
  fii_idx_put_long: number;
  fii_idx_put_short: number;
  fii_idx_put_net: number;
  dii_idx_fut_long: number;
  dii_idx_fut_short: number;
  dii_idx_fut_net: number;
  dii_stk_fut_long: number;
  dii_stk_fut_short: number;
  dii_stk_fut_net: number;
  pcr: number;
  sentiment_score: number;
  updated_at: string;
}

export interface FiiDiiTrend {
  days: number;
  snapshots: FiiDiiSnapshot[];
  fii_net_total: number;
  dii_net_total: number;
  avg_sentiment: number;
}

export interface FiiDiiResponse {
  is_sample_data: boolean;
  latest: FiiDiiSnapshot;
  trend: FiiDiiTrend | null;
}

export const getFiiDiiData = (days?: number, refresh?: boolean) => {
  const params = new URLSearchParams();
  if (days !== undefined) params.set("days", String(days));
  if (refresh) params.set("refresh", "true");
  const qs = params.toString();
  return get<FiiDiiResponse>("screener/fii-dii" + (qs ? "?" + qs : ""));
};

// ---------------------------------------------------------------------------
// RRG — Relative Rotation Graph
// ---------------------------------------------------------------------------

export interface RRGTailPoint {
  date: string;
  rs_ratio: number;
  rs_momentum: number;
}

export type RRGQuadrant = "leading" | "weakening" | "lagging" | "improving" | "neutral";

export interface SectorRRG {
  symbol: string;
  name: string;
  tail: RRGTailPoint[];
  current_quadrant: RRGQuadrant;
}

export interface RRGResponse {
  benchmark: string;
  tail_length: number;
  is_sample_data: boolean;
  sectors: SectorRRG[];
}

export const getRRGData = (tailLength?: number): Promise<RRGResponse> => {
  const params = new URLSearchParams();
  if (tailLength !== undefined) params.set("tail_length", String(tailLength));
  const qs = params.toString();
  return get<RRGResponse>("rrg/sectors" + (qs ? "?" + qs : ""));
};

// ---------------------------------------------------------------------------
// Sandbox / Paper trading
// ---------------------------------------------------------------------------

export interface SandboxConfig {
  enabled: boolean;
  mode: "paper" | "live";
}

export const getSandboxStatus = () => get<SandboxConfig>("sandbox/config");

export const toggleSandbox = (enabled: boolean) =>
  post<SandboxConfig>("sandbox/config", { enabled });

// ---------------------------------------------------------------------------
// Uploaded strategy management (distinct from backtest strategies)
// ---------------------------------------------------------------------------

export interface UploadedStrategy {
  id: string;
  name: string;
  filename: string;
  status: "running" | "stopped" | "crashed" | "uploading";
  uploaded_at: string;
  started_at: string | null;
  error_message: string | null;
}

export interface StrategyLogEntry {
  timestamp: string;
  level: "INFO" | "WARNING" | "ERROR" | "DEBUG";
  message: string;
}

export const getUploadedStrategies = () =>
  get<{ strategies: UploadedStrategy[] }>("strategies/uploaded").then(
    (r) => r.strategies,
  );

export const uploadStrategy = (file: File): Promise<UploadedStrategy> => {
  const base = (import.meta.env.DEV ? "/ft-api" : "") + "/api/v1/strategies/upload";
  const form = new FormData();
  form.append("file", file);
  return fetch(base, { method: "POST", body: form })
    .then((res) => {
      if (!res.ok) throw new Error(`Upload failed: HTTP ${res.status}`);
      return res.json() as Promise<{ data?: UploadedStrategy } | UploadedStrategy>;
    })
    .then((json) => {
      const data =
        json !== null &&
        typeof json === "object" &&
        "data" in json
          ? (json as { data: UploadedStrategy }).data
          : (json as UploadedStrategy);
      return data;
    });
};

export const startUploadedStrategy = (id: string) =>
  post<{ status: string }>(
    "strategies/uploaded/" + encodeURIComponent(id) + "/start",
  );

export const stopUploadedStrategy = (id: string) =>
  post<{ status: string }>(
    "strategies/uploaded/" + encodeURIComponent(id) + "/stop",
  );

export const getStrategyLogs = (id: string) =>
  get<{ strategy_id: string; lines: string[] }>(
    "strategies/uploaded/" + encodeURIComponent(id) + "/logs",
  ).then((r) =>
    r.lines.map((line): StrategyLogEntry => {
      const match = line.match(/^(\\S+ \\S+)\\s+\\[(\\w+)]\\s+(.*)/);
      if (match) {
        return {
          timestamp: match[1],
          level: match[2] as StrategyLogEntry["level"],
          message: match[3],
        };
      }
      return { timestamp: "", level: "INFO", message: line };
    }),
  );

// ---------------------------------------------------------------------------
// Action Center — pending order approvals
// ---------------------------------------------------------------------------

export interface PendingOrder {
  id: string;
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  price: number;
  order_type: string;
  product: string;
  strategy: string;
  created_at: string;
  reason: string;
}

export const getPendingOrders = () =>
  get<{ orders: PendingOrder[] }>("action-center/pending").then(
    (r) => r.orders,
  );

export const approveOrder = (id: string) =>
  post<{ status: string }>(
    "action-center/approve/" + encodeURIComponent(id),
  );

export const rejectOrder = (id: string) =>
  post<{ status: string }>(
    "action-center/reject/" + encodeURIComponent(id),
  );

export const approveAllOrders = () =>
  post<{ status: string; approved_count: number }>("action-center/approve-all");

// ---------------------------------------------------------------------------
// Security
// ---------------------------------------------------------------------------

export interface SecurityStatsOffender {
  ip: string;
  request_count: number;
  failed_auth_count: number;
  not_found_count: number;
  is_banned: boolean;
  last_seen: string;
}

export interface SecurityStats {
  total_ips: number;
  banned_count: number;
  top_offenders: SecurityStatsOffender[];
}

export interface BannedIP {
  ip: string;
  reason: string;
  banned_at: string;
}

export const getSecurityStats = () => get<SecurityStats>("security/stats");
export const getBannedIPs     = () => get<{ bans: BannedIP[] }>("security/bans");
export const banIP            = (ip: string, reason: string) =>
  post<{ status: string }>("security/ban", { ip, reason });
export const unbanIP          = (ip: string) =>
  post<{ status: string }>("security/unban", { ip });

// Auto-ban settings (absorbed from OpenAlgo security dashboard)
export interface SecuritySettings {
  auto_ban_enabled: boolean;
  ban_threshold: number;
  notfound_ban_threshold: number;
  ban_duration: number;
}

export const getSecuritySettings = () => get<SecuritySettings>("security/settings");
export const updateSecuritySettings = (settings: Partial<SecuritySettings>) =>
  post<{ status: string }>("security/settings", settings);

// ---------------------------------------------------------------------------
// P&L Tracker
// ---------------------------------------------------------------------------

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

export const getPnLTracker = () => get<PnLTrackerEntry[]>("pnl-tracker");
export const getPnLSummary = () => get<PnLSummary>("pnl-tracker/summary");

// ---------------------------------------------------------------------------
// Monitoring
// ---------------------------------------------------------------------------

export interface HealthSubsystem {
  status: "ok" | "degraded" | "error";
  note?: string;
  [key: string]: unknown;
}

export interface SystemHealth {
  status: "ok" | "degraded" | "error";
  broker: HealthSubsystem;
  duckdb: HealthSubsystem;
  disk: HealthSubsystem & { free_gb?: number; total_gb?: number; used_pct?: number };
  memory: HealthSubsystem & { used_mb?: number; total_mb?: number; used_pct?: number };
}

export interface PathStat {
  path: string;
  count: number;
}

export interface TrafficStats {
  window_minutes: number;
  total_requests: number;
  requests_per_sec: number;
  error_rate: number;
  avg_latency_ms: number;
  top_paths: PathStat[];
}

export interface BrokerLatency {
  count: number;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
}

export type LatencyStats = Record<string, BrokerLatency>;

export const getHealth       = () => get<SystemHealth>("health");
export const getTrafficStats = () => get<TrafficStats>("traffic/stats");
export const getLatencyStats = () => get<LatencyStats>("latency/stats");

// ---------------------------------------------------------------------------
// News (server-side RSS proxy — GET /ft-api/api/v1/news)
// ---------------------------------------------------------------------------

export interface NewsArticle {
  title: string;
  link: string;
  pub_date: string;
  source: string;
}

export const getNews = () => get<{ articles: NewsArticle[] }>("news");

// ---------------------------------------------------------------------------
// Mutual Fund Explorer
// ---------------------------------------------------------------------------

export interface MutualFundEntry {
  scheme_code: number;
  scheme_name: string;
  amc: string;
  category: string;
  nav: number;
  nav_date: string;
  scheme_type: string;
}

export interface MFSearchResponse {
  query: string;
  count: number;
  funds: MutualFundEntry[];
}

export interface MFNAVResponse {
  fund: MutualFundEntry;
}

export interface MFCategoriesResponse {
  count: number;
  categories: string[];
}

export const searchMutualFunds = (query: string, category?: string, limit?: number) => {
  const params = new URLSearchParams({ q: query });
  if (category) params.set("category", category);
  if (limit !== undefined) params.set("limit", String(limit));
  return get<MFSearchResponse>("mf/search?" + params.toString());
};

export const getMutualFundNAV = (schemeCode: number) =>
  get<MFNAVResponse>("mf/nav/" + String(schemeCode));

export const getMFCategories = () =>
  get<MFCategoriesResponse>("mf/categories");

// ---------------------------------------------------------------------------
// Ditto — Multi-account management & position mirroring
// ---------------------------------------------------------------------------

export interface DittoAccount {
  id: string;
  name: string;
  broker: string;
  capital: number;
  pnl_today: number;
  status: "active" | "disabled";
  positions: number;
  group: string;
  allocation_weight: number;
  is_master: boolean;
}

export interface MirrorStatus {
  active: boolean;
  source_account: string | null;
  target_accounts: string[];
  mode: "proportional" | "fixed" | "equal";
  mirrored_positions: number;
  last_sync: string | null;
  errors: string[];
}

export interface MirrorStartResult {
  active: boolean;
  source_account: string;
  target_accounts: string[];
  mode: string;
  started_at: string;
}

export interface DittoRiskAccount {
  id: string;
  name: string;
  margin_used_pct: number;
  pnl_today: number;
  positions: number;
  risk_status: "OK" | "WARNING" | "CRITICAL" | "PAUSED";
}

export interface DittoRiskData {
  aggregate_pnl: number;
  aggregate_capital: number;
  accounts: DittoRiskAccount[];
}

export const getDittoAccounts = () =>
  get<{ accounts: DittoAccount[] }>("ditto/accounts");

export const getDittoMirrorStatus = () =>
  get<MirrorStatus>("ditto/mirror/status");

export const startDittoMirror = (
  source_account: string,
  target_accounts: string[],
  mode: string,
) =>
  post<MirrorStartResult>("ditto/mirror/start", {
    source_account,
    target_accounts,
    mode,
  });

export const stopDittoMirror = () =>
  post<{ active: boolean; stopped_at: string }>("ditto/mirror/stop");

export const getDittoRisk = () => get<DittoRiskData>("ditto/risk");

export const dittoKillAll = () =>
  post<{ message: string; accounts_affected: number }>("ditto/kill-all");

// ---------------------------------------------------------------------------
// AlgoMirror (submodule bridge)
// ---------------------------------------------------------------------------

export interface AlgoMirrorStatusData {
  connected: boolean;
  active: boolean;
  source: string;
  targets: string[];
  multiplier: number;
  mirrored_positions: number;
  errors: string[];
}

export const getAlgoMirrorStatus = () =>
  get<AlgoMirrorStatusData>("ditto/algomirror/status");

// ---------------------------------------------------------------------------
// OpenClaw (submodule bridge)
// ---------------------------------------------------------------------------

export interface OpenClawStatusData {
  connected: boolean;
}

export interface OpenClawAgentData {
  id: string;
  name: string;
  status: string;
  strategy: string;
  symbols: string[];
  created_at: string;
}

export const getOpenClawStatus = () =>
  get<OpenClawStatusData>("ai/openclaw/status");

export const getOpenClawAgents = () =>
  get<{ agents: OpenClawAgentData[] }>("ai/openclaw/agents");

// ---------------------------------------------------------------------------
// WhatsApp Alerts
// ---------------------------------------------------------------------------

export const testWhatsAppAlert = (message?: string) =>
  post<{ status: string; message: string }>("alerts/whatsapp/test", {
    ...(message ? { message } : {}),
  });

// ---------------------------------------------------------------------------
// Historical Expired Options (ExpiryTrack)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// IPO Tracker
// ---------------------------------------------------------------------------

export interface IpoEntry {
  name: string;
  symbol: string;
  issue_size: string;
  price_band: string;
  lot_size: number;
  open_date: string;
  close_date: string;
  listing_date: string;
  status: string;
  listing_gain?: number;
}

export interface IpoResponse {
  ipos: IpoEntry[];
  last_updated: string;
}

export const getUpcomingIPOs = () => get<IpoResponse>("ipo/upcoming");
export const getRecentIPOs = () => get<IpoResponse>("ipo/recent");

// ---------------------------------------------------------------------------
// User Management (multi-user mode — admin only)
// ---------------------------------------------------------------------------

export interface UserAccount {
  id: number;
  username: string;
  email: string;
  role: "admin" | "trader" | "viewer";
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export const listUsers = () =>
  get<{ users: UserAccount[] }>("users");

export const createUser = (
  username: string,
  password: string,
  email: string,
  role?: "admin" | "trader" | "viewer",
) =>
  post<UserAccount>("users", {
    username,
    password,
    email,
    ...(role ? { role } : {}),
  });

export const updateUser = (
  username: string,
  fields: { email?: string; role?: string; is_active?: boolean },
) =>
  put<UserAccount>(
    "users/" + encodeURIComponent(username),
    fields,
  );

export const deleteUser = (username: string) =>
  del<{ message: string }>(
    "users/" + encodeURIComponent(username),
  );

// ---------------------------------------------------------------------------
// Bracket Orders
// ---------------------------------------------------------------------------

export interface BracketOrder {
  bracket_id: string;
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  entry_price: number;
  stoploss: number;
  target: number;
  trailing_sl?: number;
  status: "PENDING" | "ACTIVE" | "COMPLETED" | "CANCELLED";
  entry_order_id: string | null;
  sl_order_id: string | null;
  target_order_id: string | null;
  created_at: string;
}

export const placeBracketOrder = (
  entry: Record<string, unknown>,
  stoploss: number,
  target: number,
  trailing_sl?: number,
) =>
  post<BracketOrder>("orders/bracket", {
    ...entry,
    stoploss,
    target,
    ...(trailing_sl !== undefined ? { trailing_sl } : {}),
  });

export const getActiveBrackets = () =>
  get<{ brackets: BracketOrder[] }>("orders/brackets");

export const cancelBracketOrder = (bracketId: string) =>
  del<{ status: string }>(
    "orders/bracket/" + encodeURIComponent(bracketId),
  );

// ---------------------------------------------------------------------------
// Activity Log (admin audit trail)
// ---------------------------------------------------------------------------

export interface ActivityEntry {
  id: number;
  timestamp: string;
  action: string;
  user: string;
  details: string;
  ip: string;
}

export const getActivityLog = (params?: {
  action?: string;
  user?: string;
  since?: string;
  limit?: number;
}) => {
  const qs = new URLSearchParams();
  if (params?.action) qs.set("action", params.action);
  if (params?.user) qs.set("user", params.user);
  if (params?.since) qs.set("since", params.since);
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  const query = qs.toString();
  return get<{ entries: ActivityEntry[]; total: number }>(
    "admin/activity" + (query ? "?" + query : ""),
  );
};

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
  body: Record<string, unknown> = {},
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

async function del<T>(endpoint: string): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
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

export const getIVSmile = (
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

export const getOIProfile = (
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
  get<UploadedStrategy[]>("strategies/uploaded");

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
  get<StrategyLogEntry[]>(
    "strategies/uploaded/" + encodeURIComponent(id) + "/logs",
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
  get<PendingOrder[]>("action-center/pending");

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

export interface SecurityStats {
  total_requests: number;
  failed_auths: number;
  not_found_count: number;
  banned_count: number;
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
  threshold_404: number;
  ban_duration_404: number;
  threshold_api: number;
  ban_duration_api: number;
  repeat_offender_limit: number;
}

export const getSecuritySettings = () => get<SecuritySettings>("security/settings");
export const updateSecuritySettings = (settings: Partial<SecuritySettings>) =>
  post<{ status: string }>("security/settings", settings);

// ---------------------------------------------------------------------------
// P&L Tracker
// ---------------------------------------------------------------------------

export interface PnLTrackerEntry {
  timestamp: string;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
}

export interface PnLSummary {
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  max_drawdown: number;
  peak_pnl: number;
  entries: PnLTrackerEntry[];
}

export const getPnLTracker = () => get<{ entries: PnLTrackerEntry[] }>("pnl-tracker");
export const getPnLSummary = () => get<PnLSummary>("pnl-tracker/summary");

// ---------------------------------------------------------------------------
// Monitoring
// ---------------------------------------------------------------------------

export interface BrokerConnectionHealth {
  account: string;
  broker: string;
  connected: boolean;
  latency_ms: number | null;
}

export interface SystemHealth {
  broker_connections: BrokerConnectionHealth[];
  duckdb_status: "ok" | "error";
  disk_free_gb: number;
  disk_total_gb: number;
  memory_used_mb: number;
  memory_total_mb: number;
}

export interface EndpointStat {
  endpoint: string;
  count: number;
}

export interface TrafficStats {
  requests_per_sec: number;
  error_rate: number;
  top_endpoints: EndpointStat[];
}

export interface BrokerLatency {
  broker: string;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
}

export interface LatencyStats {
  brokers: BrokerLatency[];
}

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

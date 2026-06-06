import { get, getBase, isDemoAuthSession, post, postV1 } from "./ftApi.helpers";

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

export interface RefinementSuggestion {
  strategy_name: string;
  analysis: string;
  suggested_params: Record<string, unknown>;
  reasoning: string;
  confidence: number;
  timestamp: string;
}

export interface RefineStrategyRequest {
  strategy_name: string;
  backtest_results: {
    sharpe_ratio?: number;
    max_drawdown?: number;
    win_rate?: number;
    total_trades?: number;
    total_return?: number;
    profit_factor?: number;
    sortino_ratio?: number;
    [key: string]: unknown;
  };
  current_params: Record<string, unknown>;
}

function parseDemoStartDate(startDate: string): Date {
  const parsed = new Date(`${startDate}T09:15:00.000Z`);
  return Number.isNaN(parsed.getTime()) ? new Date("2024-01-01T09:15:00.000Z") : parsed;
}

function demoIsoDay(startDate: string, offsetDays: number): string {
  const date = parseDemoStartDate(startDate);
  date.setUTCDate(date.getUTCDate() + offsetDays);
  return date.toISOString();
}

function createDemoBacktestResult(config: BacktestConfig): BacktestResult {
  const initialCapital = config.initial_capital || 100000;
  const tradePnls = [1800, 1400, -700, 2700];
  const cumulativeEquity = tradePnls.reduce<number[]>(
    (points, pnl) => [...points, points[points.length - 1] + pnl],
    [initialCapital],
  );

  const equity_curve = cumulativeEquity.map((equity, index) => ({
    timestamp: demoIsoDay(config.start_date, index * 14),
    equity,
  }));

  const basePrice = config.exchange.includes("NFO") ? 22480 : 2480;
  const trades: BacktestTrade[] = tradePnls.map((pnl, index) => {
    const isLong = index !== 1;
    const entryPrice = basePrice + index * 85;
    const exitPrice = entryPrice + (isLong ? pnl / 20 : -pnl / 20);
    return {
      entry_timestamp: demoIsoDay(config.start_date, index * 14 + 1),
      exit_timestamp: demoIsoDay(config.start_date, index * 14 + 5),
      symbol: config.symbol,
      side: isLong ? "BUY" : "SELL",
      quantity: 20,
      entry_price: Number(entryPrice.toFixed(2)),
      exit_price: Number(exitPrice.toFixed(2)),
      pnl,
      commission: 40,
      bars_held: 75 + index * 8,
    };
  });

  const final_equity = cumulativeEquity[cumulativeEquity.length - 1];
  const grossProfit = tradePnls.filter((pnl) => pnl > 0).reduce((sum, pnl) => sum + pnl, 0);
  const grossLoss = Math.abs(tradePnls.filter((pnl) => pnl < 0).reduce((sum, pnl) => sum + pnl, 0));
  const totalReturn = (final_equity - initialCapital) / initialCapital;
  const peakDrawdown = cumulativeEquity.reduce(
    (state, equity) => {
      const peak = Math.max(state.peak, equity);
      const drawdown = peak > 0 ? (equity - peak) / peak : 0;
      return { peak, maxDrawdown: Math.min(state.maxDrawdown, drawdown) };
    },
    { peak: initialCapital, maxDrawdown: 0 },
  ).maxDrawdown;

  return {
    trades,
    equity_curve,
    final_equity,
    total_bars: 320,
    metrics: {
      total_return: totalReturn,
      sharpe_ratio: 1.84,
      sortino_ratio: 2.31,
      max_drawdown: peakDrawdown,
      win_rate: trades.filter((trade) => trade.pnl > 0).length / trades.length,
      profit_factor: grossLoss > 0 ? grossProfit / grossLoss : grossProfit,
      total_trades: trades.length,
      expectancy: tradePnls.reduce((sum, pnl) => sum + pnl, 0) / trades.length,
    },
  };
}

export const runBacktest = (config: BacktestConfig) =>
  isDemoAuthSession()
    ? Promise.resolve(createDemoBacktestResult(config))
    : post<BacktestResult>("backtest/run", config);

export const runPortfolioBacktest = (config: PortfolioBacktestConfig) =>
  post<PortfolioBacktestResult>("backtest/portfolio", config);

// Backtest built-in strategy catalogue lives under /backtest/strategies* so
// it doesn't collide with the engine's strategy_bp (which owns
// /api/v1/strategies for live strategy lifecycle). Pre-2026-05-19 these
// shared the same URL path and Flask first-match-wins silently shadowed
// the backtest list with the live runner list.

const DEMO_STRATEGIES: StrategyInfo[] = [
  {
    name: "sma_crossover",
    description: "Simple moving average crossover starter strategy",
    category: "Trend",
    parameters: [
      { name: "fast_window", type: "number", default: 20 },
      { name: "slow_window", type: "number", default: 50 },
    ],
  },
  {
    name: "rsi_mean_reversion",
    description: "RSI oversold and overbought reversion template",
    category: "Mean Reversion",
    parameters: [
      { name: "period", type: "number", default: 14 },
      { name: "entry_threshold", type: "number", default: 30 },
    ],
  },
];

export const getStrategies = () =>
  isDemoAuthSession()
    ? Promise.resolve(DEMO_STRATEGIES)
    : get<{ strategies: StrategyInfo[] }>("backtest/strategies").then((r) => r.strategies);

export const getRunningStrategies = () =>
  isDemoAuthSession()
    ? Promise.resolve([])
    : get<{ strategies: RunningStrategy[] }>("backtest/strategies/running").then(
      (r) => r.strategies,
    );

export const startStrategy = (name: string, config: Record<string, unknown>) =>
  post<{ status: string }>(
    "backtest/strategies/" + encodeURIComponent(name) + "/start",
    config,
  );

export const stopStrategy = (name: string) =>
  post<{ status: string }>(
    "backtest/strategies/" + encodeURIComponent(name) + "/stop",
  );

export const getForwardTrades = (name: string) =>
  get<{ strategy_id: string; trades: ForwardTrade[] }>(
    "strategies/" + encodeURIComponent(name) + "/trades",
  ).then((r) => r.trades);

export const getUploadedStrategies = () =>
  isDemoAuthSession()
    ? Promise.resolve([])
    : get<{ strategies: UploadedStrategy[] }>("backtest/strategies/uploaded").then(
      (r) => r.strategies,
    );

export const uploadStrategy = (file: File): Promise<UploadedStrategy> => {
  const base = getBase() + "/api/v1/strategies/upload";
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

// Uploaded-strategy lifecycle is owned by the engine's strategy_bp at
// /api/v1/strategies/<id>/{start,stop,logs} — the previous
// /api/v1/strategies/uploaded/<id>/* URLs were unmatched on the backend
// (no blueprint registered them) and silently 404'd in production.

export const startUploadedStrategy = (id: string) =>
  post<{ status: string }>(
    "strategies/" + encodeURIComponent(id) + "/start",
  );

export const stopUploadedStrategy = (id: string) =>
  post<{ status: string }>(
    "strategies/" + encodeURIComponent(id) + "/stop",
  );

export const getStrategyLogs = (id: string) =>
  get<{ strategy_id: string; lines: string[] }>(
    "strategies/" + encodeURIComponent(id) + "/logs",
  ).then((r) =>
    r.lines.map((line): StrategyLogEntry => {
      const match = line.match(/^(\S+ \S+)\s+\[(\w+)]\s+(.*)/);
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

export const refineStrategy = (req: RefineStrategyRequest) =>
  post<RefinementSuggestion>("ai/refine-strategy", req);

// ---------------------------------------------------------------------------
// Permutation (Monte-Carlo) significance test — /v1/backtest/permutation.
// Distinguishes a strategy's skill from luck by shuffling its return series and
// measuring how often a random ordering beats the observed metric. Reachable
// only via postV1 (the endpoint registers at /v1, not /api/v1).
// ---------------------------------------------------------------------------

export interface PermutationConfig {
  n_permutations?: number;
  confidence_level?: number;
  metric?: string;
  random_seed?: number;
}

export interface PermutationResult {
  original_metric: number;
  permutation_mean: number;
  permutation_std: number;
  p_value: number;
  is_significant: boolean;
  confidence_level: number;
  n_permutations: number;
  percentile_rank: number;
}

export const runPermutationTest = (returns: number[], config?: PermutationConfig) =>
  postV1<PermutationResult>("backtest/permutation", {
    mode: "returns",
    returns,
    ...(config ? { config } : {}),
  });

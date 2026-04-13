import { get, getBase, post } from "./ftApi.helpers";

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

export const runBacktest = (config: BacktestConfig) =>
  post<BacktestResult>("backtest/run", config);

export const runPortfolioBacktest = (config: PortfolioBacktestConfig) =>
  post<PortfolioBacktestResult>("backtest/portfolio", config);

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

export const getUploadedStrategies = () =>
  get<{ strategies: UploadedStrategy[] }>("strategies/uploaded").then(
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

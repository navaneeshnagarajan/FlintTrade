import { useState, useMemo } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Zap,
  FlaskConical,
  PlayCircle,
  Settings2,
  TrendingUp,
  BarChart3,
  ChevronRight,
  Loader2,
  AlertCircle,
  RefreshCw,
  Play,
  Square,
  Activity,
  Clock,
} from "lucide-react";
import { AreaChart, BarChart } from "@tremor/react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  runBacktest,
  getStrategies,
  getRunningStrategies,
  getForwardTrades,
  startStrategy,
  stopStrategy,
  type BacktestConfig,
  type BacktestResult,
  type StrategyInfo,
  type RunningStrategy,
  type ForwardTrade,
} from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Section registry
// ---------------------------------------------------------------------------

type SectionId = "backtest" | "forward-test" | "optimize" | "results" | "settings";

interface SectionDef {
  id: SectionId;
  label: string;
  icon: typeof FlaskConical;
  desc: string;
}

const SECTIONS: SectionDef[] = [
  { id: "backtest", label: "Backtest", icon: FlaskConical, desc: "Test strategies on historical data" },
  { id: "forward-test", label: "Forward Test", icon: PlayCircle, desc: "Paper trade strategies in live market" },
  { id: "optimize", label: "Optimize", icon: TrendingUp, desc: "Walk-forward optimization" },
  { id: "results", label: "Results", icon: BarChart3, desc: "Performance metrics & comparison" },
  { id: "settings", label: "Lab Settings", icon: Settings2, desc: "Module-specific configuration" },
];

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function fmtInr(value: number): string {
  return value.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
}

function fmtPct(value: number): string {
  return (value * 100).toFixed(2) + "%";
}

function fmtNum(value: number, decimals = 2): string {
  return value.toFixed(decimals);
}

// ---------------------------------------------------------------------------
// Metrics card grid
// ---------------------------------------------------------------------------

interface MetricCardProps {
  label: string;
  value: string;
  positive?: boolean | null;
}

function MetricCard({ label, value, positive }: MetricCardProps) {
  const valueColor =
    positive === true
      ? "text-profit"
      : positive === false
        ? "text-loss"
        : "text-text-primary";
  return (
    <div className="bg-surface-base border border-border-default rounded-lg p-4 text-center">
      <p className="text-xs text-text-muted mb-1 uppercase tracking-wider">{label}</p>
      <p className={`text-sm font-mono font-semibold ${valueColor}`}>{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Equity curve — Tremor AreaChart
// ---------------------------------------------------------------------------

interface EquityCurveProps {
  curve: Array<{ timestamp: string; equity: number }>;
  initialEquity: number;
}

function EquityCurve({ curve, initialEquity }: EquityCurveProps) {
  if (curve.length === 0) return null;

  // Sample down to at most 120 points for performance
  const step = Math.max(1, Math.floor(curve.length / 120));
  const sampled = curve
    .filter((_, i) => i % step === 0)
    .map((p) => ({
      date: p.timestamp.slice(0, 10),
      Equity: p.equity,
    }));

  const lastEquity = sampled[sampled.length - 1]?.Equity ?? initialEquity;
  const isPositive = lastEquity >= initialEquity;

  return (
    <AreaChart
      data={sampled}
      index="date"
      categories={["Equity"]}
      colors={[isPositive ? "emerald" : "red"]}
      valueFormatter={(v: number) => fmtInr(v)}
      showLegend={false}
      showYAxis={true}
      showXAxis={true}
      showGridLines={false}
      className="h-36 text-xs"
      curveType="monotone"
    />
  );
}

// ---------------------------------------------------------------------------
// Backtest result display
// ---------------------------------------------------------------------------

interface BacktestResultDisplayProps {
  result: BacktestResult;
}

function BacktestResultDisplay({ result }: BacktestResultDisplayProps) {
  const { metrics, trades, equity_curve, final_equity } = result;
  const totalReturnPositive = metrics.total_return >= 0;
  const initialEquity = equity_curve.length > 0 ? equity_curve[0].equity : final_equity;

  // Group closed trades by month for monthly P&L bar chart
  const monthlyPnl = useMemo(() => {
    const grouped: Record<string, number> = {};
    trades.forEach((t) => {
      const month = t.exit_timestamp.slice(0, 7); // YYYY-MM
      grouped[month] = (grouped[month] ?? 0) + t.pnl;
    });
    return Object.entries(grouped)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, pnl]) => ({ month, "P&L": pnl }));
  }, [trades]);

  return (
    <div className="space-y-4">
      {/* Metrics */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <h4 className="font-heading font-semibold text-sm text-text-primary mb-3">Performance Metrics</h4>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricCard
            label="Total Return"
            value={fmtPct(metrics.total_return)}
            positive={totalReturnPositive}
          />
          <MetricCard label="Final Equity" value={fmtInr(final_equity)} positive={null} />
          <MetricCard
            label="Sharpe Ratio"
            value={fmtNum(metrics.sharpe_ratio)}
            positive={metrics.sharpe_ratio > 1}
          />
          <MetricCard
            label="Sortino Ratio"
            value={fmtNum(metrics.sortino_ratio)}
            positive={metrics.sortino_ratio > 1}
          />
          <MetricCard
            label="Max Drawdown"
            value={fmtPct(Math.abs(metrics.max_drawdown))}
            positive={false}
          />
          <MetricCard
            label="Win Rate"
            value={fmtPct(metrics.win_rate)}
            positive={metrics.win_rate >= 0.5}
          />
          <MetricCard
            label="Profit Factor"
            value={fmtNum(metrics.profit_factor)}
            positive={metrics.profit_factor > 1}
          />
          <MetricCard label="Total Trades" value={String(metrics.total_trades)} positive={null} />
          <MetricCard
            label="Expectancy"
            value={fmtInr(metrics.expectancy)}
            positive={metrics.expectancy >= 0}
          />
        </div>
      </Card>

      {/* Equity curve — Tremor AreaChart */}
      {equity_curve.length > 0 && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-5">
          <h4 className="font-heading font-semibold text-sm text-text-primary mb-3">Equity Curve</h4>
          <EquityCurve curve={equity_curve} initialEquity={initialEquity} />
        </Card>
      )}

      {/* Monthly P&L breakdown — Tremor BarChart */}
      {monthlyPnl.length > 0 && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-5">
          <h4 className="font-heading font-semibold text-sm text-text-primary mb-3">Monthly P&L</h4>
          <BarChart
            data={monthlyPnl}
            index="month"
            categories={["P&L"]}
            colors={["emerald"]}
            valueFormatter={(v: number) => fmtInr(v)}
            showLegend={false}
            showYAxis={true}
            showXAxis={true}
            showGridLines={false}
            className="h-36 text-xs"
          />
        </Card>
      )}

      {/* Trade list */}
      {trades.length > 0 && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-5">
          <h4 className="font-heading font-semibold text-sm text-text-primary mb-3">
            Trade Log
            <span className="ml-2 text-xs text-text-muted font-normal">({trades.length} trades)</span>
          </h4>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default">
                  <TableHead className="text-text-muted text-xs">Entry</TableHead>
                  <TableHead className="text-text-muted text-xs">Exit</TableHead>
                  <TableHead className="text-text-muted text-xs">Symbol</TableHead>
                  <TableHead className="text-text-muted text-xs">Side</TableHead>
                  <TableHead className="text-text-muted text-xs text-right">Entry ₹</TableHead>
                  <TableHead className="text-text-muted text-xs text-right">Exit ₹</TableHead>
                  <TableHead className="text-text-muted text-xs text-right">P&L</TableHead>
                  <TableHead className="text-text-muted text-xs text-right">Bars</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((trade, i) => (
                  <TableRow key={i} className="border-border-default">
                    <TableCell className="text-xxs text-text-secondary font-mono">
                      {trade.entry_timestamp.slice(0, 16).replace("T", " ")}
                    </TableCell>
                    <TableCell className="text-xxs text-text-secondary font-mono">
                      {trade.exit_timestamp.slice(0, 16).replace("T", " ")}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-text-primary">{trade.symbol}</TableCell>
                    <TableCell>
                      <Badge
                        className={`text-xxs ${
                          trade.side === "BUY"
                            ? "bg-bullish-bg text-profit"
                            : "bg-bearish-bg text-loss"
                        }`}
                      >
                        {trade.side}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xxs font-mono text-text-secondary text-right">
                      {trade.entry_price.toLocaleString("en-IN")}
                    </TableCell>
                    <TableCell className="text-xxs font-mono text-text-secondary text-right">
                      {trade.exit_price.toLocaleString("en-IN")}
                    </TableCell>
                    <TableCell
                      className={`text-xs font-mono font-semibold text-right ${
                        trade.pnl >= 0 ? "text-profit" : "text-loss"
                      }`}
                    >
                      {fmtInr(trade.pnl)}
                    </TableCell>
                    <TableCell className="text-xxs font-mono text-text-muted text-right">
                      {trade.bars_held}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Backtest section
// ---------------------------------------------------------------------------

interface BacktestSectionProps {
  onResult: (result: BacktestResult) => void;
  lastResult: BacktestResult | null;
}

function BacktestSection({ onResult, lastResult }: BacktestSectionProps) {
  const [symbol, setSymbol] = useState("NIFTY");
  const [exchange, setExchange] = useState("NFO");
  const [interval, setInterval] = useState("5m");
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [initialCapital, setInitialCapital] = useState(100000);
  const [positionSizePct, setPositionSizePct] = useState(10);
  const [selectedStrategy, setSelectedStrategy] = useState("");

  const strategiesQuery = useQuery<StrategyInfo[], Error>({
    queryKey: ["strategies"],
    queryFn: getStrategies,
  });

  const backtestMutation = useMutation<BacktestResult, Error, BacktestConfig>({
    mutationFn: runBacktest,
    onSuccess: (data) => {
      onResult(data);
    },
  });

  // Group strategies by category
  const strategiesByCategory = (strategiesQuery.data ?? []).reduce<
    Record<string, StrategyInfo[]>
  >((acc, s) => {
    const cat = s.category || "Other";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(s);
    return acc;
  }, {});

  function handleRun() {
    if (!selectedStrategy) return;
    backtestMutation.mutate({
      symbol,
      exchange,
      interval,
      start_date: startDate,
      end_date: endDate,
      strategy: selectedStrategy,
      initial_capital: initialCapital,
      position_size_pct: positionSizePct,
    });
  }

  const isRunning = backtestMutation.isPending;
  const runError = backtestMutation.error;

  return (
    <div className="space-y-4">
      {/* Config form */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-4">
          Backtest Configuration
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Strategy selector */}
          <div className="sm:col-span-2 space-y-1.5">
            <Label className="text-xs text-text-secondary">Strategy</Label>
            {strategiesQuery.isLoading ? (
              <div className="flex items-center gap-2 text-xs text-text-muted h-9">
                <Loader2 className="w-3 h-3 animate-spin" />
                Loading strategies…
              </div>
            ) : strategiesQuery.isError ? (
              <div className="flex items-center gap-2 text-xs text-loss h-9">
                <AlertCircle className="w-3 h-3" />
                Failed to load strategies
                <button
                  onClick={() => strategiesQuery.refetch()}
                  className="underline hover:no-underline"
                >
                  Retry
                </button>
              </div>
            ) : (
              <Select value={selectedStrategy} onValueChange={setSelectedStrategy}>
                <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                  <SelectValue placeholder="Select a strategy…" />
                </SelectTrigger>
                <SelectContent className="bg-surface-card border-border-default">
                  {Object.entries(strategiesByCategory).map(([category, strategies]) => (
                    <div key={category}>
                      <div className="px-2 py-1 text-xxs text-text-muted font-semibold uppercase tracking-wider">
                        {category}
                      </div>
                      {strategies.map((s) => (
                        <SelectItem
                          key={s.name}
                          value={s.name}
                          className="text-text-primary text-sm"
                        >
                          <span className="font-mono">{s.name}</span>
                          {s.description && (
                            <span className="ml-2 text-text-muted text-xs">— {s.description}</span>
                          )}
                        </SelectItem>
                      ))}
                    </div>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          {/* Symbol */}
          <div className="space-y-1.5">
            <Label className="text-xs text-text-secondary">Symbol</Label>
            <Input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="NIFTY"
              className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
            />
          </div>

          {/* Exchange */}
          <div className="space-y-1.5">
            <Label className="text-xs text-text-secondary">Exchange</Label>
            <Select value={exchange} onValueChange={setExchange}>
              <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-surface-card border-border-default">
                {["NFO", "NSE", "BSE", "MCX", "CDS"].map((ex) => (
                  <SelectItem key={ex} value={ex} className="text-text-primary text-sm font-mono">
                    {ex}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Interval */}
          <div className="space-y-1.5">
            <Label className="text-xs text-text-secondary">Interval</Label>
            <Select value={interval} onValueChange={setInterval}>
              <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-surface-card border-border-default">
                {["1m", "3m", "5m", "10m", "15m", "30m", "1h", "D", "W"].map((iv) => (
                  <SelectItem key={iv} value={iv} className="text-text-primary text-sm font-mono">
                    {iv}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Initial capital */}
          <div className="space-y-1.5">
            <Label className="text-xs text-text-secondary">Initial Capital (₹)</Label>
            <Input
              type="number"
              min={1000}
              step={10000}
              value={initialCapital}
              onChange={(e) => setInitialCapital(Number(e.target.value))}
              className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
            />
          </div>

          {/* Start date */}
          <div className="space-y-1.5">
            <Label className="text-xs text-text-secondary">Start Date</Label>
            <Input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
            />
          </div>

          {/* End date */}
          <div className="space-y-1.5">
            <Label className="text-xs text-text-secondary">End Date</Label>
            <Input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
            />
          </div>

          {/* Position size */}
          <div className="space-y-1.5">
            <Label className="text-xs text-text-secondary">Position Size (%)</Label>
            <Input
              type="number"
              min={1}
              max={100}
              step={1}
              value={positionSizePct}
              onChange={(e) => setPositionSizePct(Number(e.target.value))}
              className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
            />
          </div>
        </div>

        {/* Run button + error */}
        <div className="mt-5 flex items-center gap-3">
          <Button
            onClick={handleRun}
            disabled={isRunning || !selectedStrategy}
            className="bg-accent text-white hover:bg-accent/90 font-sans text-sm px-5"
          >
            {isRunning ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Running…
              </>
            ) : (
              <>
                <Play className="w-4 h-4 mr-2" />
                Run Backtest
              </>
            )}
          </Button>

          {backtestMutation.isSuccess && (
            <span className="text-xs text-profit">Backtest complete.</span>
          )}

          {runError && (
            <div className="flex items-center gap-2 text-xs text-loss">
              <AlertCircle className="w-3.5 h-3.5 shrink-0" />
              <span>{runError.message}</span>
              <button
                onClick={handleRun}
                className="flex items-center gap-1 underline hover:no-underline"
              >
                <RefreshCw className="w-3 h-3" />
                Retry
              </button>
            </div>
          )}
        </div>
      </Card>

      {/* Results (inline — shown as soon as mutation succeeds) */}
      {isRunning && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-6 flex items-center gap-3">
          <Loader2 className="w-5 h-5 text-accent animate-spin" />
          <p className="text-sm text-text-secondary">
            Running backtest… this may take a few seconds.
          </p>
        </Card>
      )}

      {!isRunning && lastResult && <BacktestResultDisplay result={lastResult} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Forward test — duration display helper
// ---------------------------------------------------------------------------

function useDuration(startedAt: string | null): string {
  const [now, setNow] = useState(() => Date.now());

  // tick every second while a start time is present
  useState(() => {
    if (!startedAt) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  });

  if (!startedAt) return "—";

  const diffMs = now - new Date(startedAt).getTime();
  if (diffMs < 0) return "—";

  const secs = Math.floor(diffMs / 1000);
  const mins = Math.floor(secs / 60);
  const hrs = Math.floor(mins / 60);

  if (hrs > 0) return `${hrs}h ${mins % 60}m ${secs % 60}s`;
  if (mins > 0) return `${mins}m ${secs % 60}s`;
  return `${secs}s`;
}

// ---------------------------------------------------------------------------
// Forward trades table
// ---------------------------------------------------------------------------

interface ForwardTradesTableProps {
  trades: ForwardTrade[];
}

function ForwardTradesTable({ trades }: ForwardTradesTableProps) {
  if (trades.length === 0) {
    return (
      <p className="text-xs text-text-muted text-center py-6">
        No virtual trades yet. Signals will generate trades as ticks arrive.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="border-border-default">
            <TableHead className="text-text-muted text-xs">Entry</TableHead>
            <TableHead className="text-text-muted text-xs">Exit</TableHead>
            <TableHead className="text-text-muted text-xs">Symbol</TableHead>
            <TableHead className="text-text-muted text-xs">Side</TableHead>
            <TableHead className="text-text-muted text-xs text-right">Qty</TableHead>
            <TableHead className="text-text-muted text-xs text-right">Entry ₹</TableHead>
            <TableHead className="text-text-muted text-xs text-right">Exit ₹</TableHead>
            <TableHead className="text-text-muted text-xs text-right">P&L</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((trade, i) => (
            <TableRow key={i} className="border-border-default">
              <TableCell className="text-xxs text-text-secondary font-mono">
                {trade.entry_timestamp.slice(0, 16).replace("T", " ")}
              </TableCell>
              <TableCell className="text-xxs text-text-secondary font-mono">
                {trade.exit_timestamp
                  ? trade.exit_timestamp.slice(0, 16).replace("T", " ")
                  : <span className="text-warning">Open</span>}
              </TableCell>
              <TableCell className="text-xs font-mono text-text-primary">{trade.symbol}</TableCell>
              <TableCell>
                <Badge
                  className={`text-xxs ${
                    trade.side === "BUY"
                      ? "bg-bullish-bg text-profit"
                      : "bg-bearish-bg text-loss"
                  }`}
                >
                  {trade.side}
                </Badge>
              </TableCell>
              <TableCell className="text-xxs font-mono text-text-secondary text-right">
                {trade.quantity}
              </TableCell>
              <TableCell className="text-xxs font-mono text-text-secondary text-right">
                {trade.entry_price.toLocaleString("en-IN")}
              </TableCell>
              <TableCell className="text-xxs font-mono text-text-secondary text-right">
                {trade.exit_price > 0
                  ? trade.exit_price.toLocaleString("en-IN")
                  : "—"}
              </TableCell>
              <TableCell
                className={`text-xs font-mono font-semibold text-right ${
                  trade.pnl >= 0 ? "text-profit" : "text-loss"
                }`}
              >
                {trade.exit_price > 0 ? fmtInr(trade.pnl) : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Forward test — live monitor panel (shown while strategy is running)
// ---------------------------------------------------------------------------

interface ForwardMonitorProps {
  running: RunningStrategy;
  onStop: () => void;
  isStopping: boolean;
}

function ForwardMonitor({ running, onStop, isStopping }: ForwardMonitorProps) {
  const duration = useDuration(running.started_at);

  const tradesQuery = useQuery<ForwardTrade[], Error>({
    queryKey: ["forwardTrades", running.name],
    queryFn: () => getForwardTrades(running.name),
    refetchInterval: 5000,
  });

  const trades = tradesQuery.data ?? [];
  const closedTrades = trades.filter((t) => t.exit_price > 0);

  // Derive live metrics from accumulated trades
  const totalPnl = running.virtual_pnl ?? closedTrades.reduce((sum, t) => sum + t.pnl, 0);
  const wins = closedTrades.filter((t) => t.pnl > 0).length;
  const winRate = closedTrades.length > 0 ? wins / closedTrades.length : 0;
  const grossWin = closedTrades.filter((t) => t.pnl > 0).reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(
    closedTrades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0),
  );
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0;

  return (
    <div className="space-y-4">
      {/* Status bar */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-profit" />
              <span className="text-sm font-semibold text-text-primary font-mono">
                {running.name}
              </span>
            </div>
            <Badge className="bg-bullish-bg text-profit text-xs border-0">
              {running.status}
            </Badge>
            <span className="text-xs text-text-muted font-mono">{running.symbol} / {running.exchange}</span>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5 text-xs text-text-muted">
              <Clock className="w-3 h-3" />
              <span className="font-mono">{duration}</span>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={onStop}
              disabled={isStopping}
              className="text-xs h-7 px-3"
            >
              {isStopping ? (
                <>
                  <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />
                  Stopping…
                </>
              ) : (
                <>
                  <Square className="w-3 h-3 mr-1.5" />
                  Stop
                </>
              )}
            </Button>
          </div>
        </div>
      </Card>

      {/* Live metrics */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <h4 className="font-heading font-semibold text-sm text-text-primary mb-3">
          Live Performance
          {tradesQuery.isFetching && (
            <Loader2 className="inline-block w-3 h-3 ml-2 animate-spin text-text-muted" />
          )}
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricCard
            label="Virtual P&L"
            value={fmtInr(totalPnl)}
            positive={totalPnl >= 0}
          />
          <MetricCard
            label="Ticks Processed"
            value={String(running.tick_count)}
            positive={null}
          />
          <MetricCard
            label="Closed Trades"
            value={String(closedTrades.length)}
            positive={null}
          />
          <MetricCard
            label="Win Rate"
            value={closedTrades.length > 0 ? fmtPct(winRate) : "—"}
            positive={winRate >= 0.5}
          />
          <MetricCard
            label="Gross Win"
            value={grossWin > 0 ? fmtInr(grossWin) : "—"}
            positive={grossWin > 0 ? true : null}
          />
          <MetricCard
            label="Gross Loss"
            value={grossLoss > 0 ? fmtInr(grossLoss) : "—"}
            positive={false}
          />
          <MetricCard
            label="Profit Factor"
            value={
              profitFactor === Infinity
                ? "∞"
                : closedTrades.length > 0
                  ? fmtNum(profitFactor)
                  : "—"
            }
            positive={profitFactor > 1 ? true : profitFactor === 0 ? null : false}
          />
          <MetricCard
            label="Open Trades"
            value={String(trades.length - closedTrades.length)}
            positive={null}
          />
        </div>
      </Card>

      {/* Virtual trades table */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <h4 className="font-heading font-semibold text-sm text-text-primary mb-3">
          Virtual Trade Log
          <span className="ml-2 text-xs text-text-muted font-normal">
            ({trades.length} trade{trades.length !== 1 ? "s" : ""})
          </span>
        </h4>
        <ForwardTradesTable trades={trades} />
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Forward test section
// ---------------------------------------------------------------------------

type ForwardTestState = "idle" | "running" | "stopped";

function ForwardTestSection() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [exchange, setExchange] = useState("NFO");
  const [virtualCapital, setVirtualCapital] = useState(100000);
  const [positionSizePct, setPositionSizePct] = useState(10);
  const [selectedStrategy, setSelectedStrategy] = useState("");
  const [ftState, setFtState] = useState<ForwardTestState>("idle");
  const [activeStrategyName, setActiveStrategyName] = useState<string | null>(null);
  const [stoppedSummary, setStoppedSummary] = useState<{
    trades: ForwardTrade[];
    pnl: number;
  } | null>(null);

  // Strategy list (shared query key with BacktestSection)
  const strategiesQuery = useQuery<StrategyInfo[], Error>({
    queryKey: ["strategies"],
    queryFn: getStrategies,
  });

  // Poll running strategies to find ours
  const runningQuery = useQuery<RunningStrategy[], Error>({
    queryKey: ["runningStrategies"],
    queryFn: getRunningStrategies,
    refetchInterval: ftState === "running" ? 5000 : false,
    enabled: ftState === "running",
  });

  const activeRunning = runningQuery.data?.find(
    (s) => s.name === activeStrategyName,
  ) ?? null;

  // Sync ftState if the backend reports the strategy stopped externally
  useState(() => {
    if (ftState === "running" && activeStrategyName && runningQuery.data) {
      const found = runningQuery.data.find((s) => s.name === activeStrategyName);
      if (!found) {
        setFtState("stopped");
      }
    }
  });

  const strategiesByCategory = (strategiesQuery.data ?? []).reduce<
    Record<string, StrategyInfo[]>
  >((acc, s) => {
    const cat = s.category || "Other";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(s);
    return acc;
  }, {});

  const startMutation = useMutation<{ status: string }, Error, void>({
    mutationFn: () =>
      startStrategy(selectedStrategy, {
        symbol,
        exchange,
        initial_capital: virtualCapital,
        position_size_pct: positionSizePct,
        paper_mode: true,
      }),
    onSuccess: () => {
      setActiveStrategyName(selectedStrategy);
      setFtState("running");
      setStoppedSummary(null);
    },
  });

  const stopMutation = useMutation<{ status: string }, Error, void>({
    mutationFn: () => stopStrategy(activeStrategyName!),
    onSuccess: async () => {
      // Snapshot the last known trades + pnl before clearing
      const pnl = activeRunning?.virtual_pnl ?? 0;
      let lastTrades: ForwardTrade[] = [];
      try {
        lastTrades = await getForwardTrades(activeStrategyName!);
      } catch {
        // ignore — summary will show partial data
      }
      setStoppedSummary({ trades: lastTrades, pnl });
      setFtState("stopped");
      setActiveStrategyName(null);
    },
  });

  // ---------- Render: config form ----------
  if (ftState === "idle" || ftState === "stopped") {
    const closedTrades = stoppedSummary?.trades.filter((t) => t.exit_price > 0) ?? [];
    const wins = closedTrades.filter((t) => t.pnl > 0).length;
    const winRate = closedTrades.length > 0 ? wins / closedTrades.length : 0;
    const grossWin = closedTrades.filter((t) => t.pnl > 0).reduce((s, t) => s + t.pnl, 0);
    const grossLoss = Math.abs(
      closedTrades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0),
    );
    const profitFactor = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0;

    return (
      <div className="space-y-4">
        {/* Stopped summary */}
        {ftState === "stopped" && stoppedSummary && (
          <Card className="bg-surface-card border border-border-default rounded-lg p-5">
            <div className="flex items-center justify-between mb-3">
              <h4 className="font-heading font-semibold text-sm text-text-primary">
                Session Summary
              </h4>
              <Badge className="bg-text-muted/10 text-text-muted text-xs border-0">Stopped</Badge>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
              <MetricCard
                label="Final P&L"
                value={fmtInr(stoppedSummary.pnl)}
                positive={stoppedSummary.pnl >= 0}
              />
              <MetricCard
                label="Closed Trades"
                value={String(closedTrades.length)}
                positive={null}
              />
              <MetricCard
                label="Win Rate"
                value={closedTrades.length > 0 ? fmtPct(winRate) : "—"}
                positive={winRate >= 0.5}
              />
              <MetricCard
                label="Profit Factor"
                value={
                  profitFactor === Infinity
                    ? "∞"
                    : closedTrades.length > 0
                      ? fmtNum(profitFactor)
                      : "—"
                }
                positive={profitFactor > 1 ? true : profitFactor === 0 ? null : false}
              />
            </div>
            {stoppedSummary.trades.length > 0 && (
              <>
                <h5 className="text-xs font-semibold text-text-secondary mb-2">
                  Trade Log
                  <span className="ml-2 text-text-muted font-normal">
                    ({stoppedSummary.trades.length} trade{stoppedSummary.trades.length !== 1 ? "s" : ""})
                  </span>
                </h5>
                <ForwardTradesTable trades={stoppedSummary.trades} />
              </>
            )}
          </Card>
        )}

        {/* Config form */}
        <Card className="bg-surface-card border border-border-default rounded-lg p-6">
          <h3 className="font-heading font-semibold text-lg text-text-primary mb-4">
            Forward Test Configuration
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Strategy selector */}
            <div className="sm:col-span-2 space-y-1.5">
              <Label className="text-xs text-text-secondary">Strategy</Label>
              {strategiesQuery.isLoading ? (
                <div className="flex items-center gap-2 text-xs text-text-muted h-9">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Loading strategies…
                </div>
              ) : strategiesQuery.isError ? (
                <div className="flex items-center gap-2 text-xs text-loss h-9">
                  <AlertCircle className="w-3 h-3" />
                  Failed to load strategies
                  <button
                    onClick={() => strategiesQuery.refetch()}
                    className="underline hover:no-underline"
                  >
                    Retry
                  </button>
                </div>
              ) : (
                <Select value={selectedStrategy} onValueChange={setSelectedStrategy}>
                  <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                    <SelectValue placeholder="Select a strategy…" />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default">
                    {Object.entries(strategiesByCategory).map(([category, strategies]) => (
                      <div key={category}>
                        <div className="px-2 py-1 text-xxs text-text-muted font-semibold uppercase tracking-wider">
                          {category}
                        </div>
                        {strategies.map((s) => (
                          <SelectItem
                            key={s.name}
                            value={s.name}
                            className="text-text-primary text-sm"
                          >
                            <span className="font-mono">{s.name}</span>
                            {s.description && (
                              <span className="ml-2 text-text-muted text-xs">— {s.description}</span>
                            )}
                          </SelectItem>
                        ))}
                      </div>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>

            {/* Symbol */}
            <div className="space-y-1.5">
              <Label className="text-xs text-text-secondary">Symbol</Label>
              <Input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="NIFTY"
                className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
              />
            </div>

            {/* Exchange */}
            <div className="space-y-1.5">
              <Label className="text-xs text-text-secondary">Exchange</Label>
              <Select value={exchange} onValueChange={setExchange}>
                <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-surface-card border-border-default">
                  {["NFO", "NSE", "BSE", "MCX", "CDS"].map((ex) => (
                    <SelectItem key={ex} value={ex} className="text-text-primary text-sm font-mono">
                      {ex}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Virtual capital */}
            <div className="space-y-1.5">
              <Label className="text-xs text-text-secondary">Virtual Capital (₹)</Label>
              <Input
                type="number"
                min={1000}
                step={10000}
                value={virtualCapital}
                onChange={(e) => setVirtualCapital(Number(e.target.value))}
                className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
              />
            </div>

            {/* Position size */}
            <div className="space-y-1.5">
              <Label className="text-xs text-text-secondary">Position Size (%)</Label>
              <Input
                type="number"
                min={1}
                max={100}
                step={1}
                value={positionSizePct}
                onChange={(e) => setPositionSizePct(Number(e.target.value))}
                className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
              />
            </div>
          </div>

          {/* Start button */}
          <div className="mt-5 flex items-center gap-3">
            <Button
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending || !selectedStrategy}
              className="bg-accent text-white hover:bg-accent/90 font-sans text-sm px-5"
            >
              {startMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Starting…
                </>
              ) : (
                <>
                  <PlayCircle className="w-4 h-4 mr-2" />
                  Start Forward Test
                </>
              )}
            </Button>

            {startMutation.isError && (
              <div className="flex items-center gap-2 text-xs text-loss">
                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                <span>{startMutation.error.message}</span>
                <button
                  onClick={() => startMutation.mutate()}
                  className="flex items-center gap-1 underline hover:no-underline"
                >
                  <RefreshCw className="w-3 h-3" />
                  Retry
                </button>
              </div>
            )}
          </div>
        </Card>
      </div>
    );
  }

  // ---------- Render: running monitor ----------
  if (ftState === "running" && activeRunning) {
    return (
      <ForwardMonitor
        running={activeRunning}
        onStop={() => stopMutation.mutate()}
        isStopping={stopMutation.isPending}
      />
    );
  }

  // Waiting for backend to confirm running (transitional state)
  return (
    <Card className="bg-surface-card border border-border-default rounded-lg p-6 flex items-center gap-3">
      <Loader2 className="w-5 h-5 text-accent animate-spin" />
      <p className="text-sm text-text-secondary">
        Starting forward test… waiting for strategy engine.
      </p>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Optimize section
// ---------------------------------------------------------------------------

function OptimizeSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Walk-Forward Optimization
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Optimize strategy parameters using walk-forward analysis to avoid overfitting.
          The optimizer splits historical data into in-sample (training) and out-of-sample
          (validation) windows, finding parameters that generalize across market regimes.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Methods</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Grid Search</li>
              <li>Random Search</li>
              <li>Walk-Forward Windows</li>
              <li>Monte Carlo Validation</li>
            </ul>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Objective Functions</h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Maximize Sharpe Ratio</li>
              <li>Maximize Sortino Ratio</li>
              <li>Minimize Max Drawdown</li>
              <li>Maximize Profit Factor</li>
            </ul>
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-atm-bg text-warning text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Parameter optimization UI will be available in the next release. The Python
          backtest-engine package already supports walk-forward optimization via{" "}
          <code className="text-xxs bg-surface-base px-1 py-0.5 rounded font-mono">
            Optimizer.optimize()
          </code>
          .
        </p>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Results section
// ---------------------------------------------------------------------------

interface ResultsSectionProps {
  lastResult: BacktestResult | null;
}

function ResultsSection({ lastResult }: ResultsSectionProps) {
  if (lastResult) {
    return (
      <div className="space-y-4">
        <Card className="bg-surface-card border border-border-default rounded-lg p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-heading font-semibold text-lg text-text-primary">
              Last Backtest Results
            </h3>
            <Badge className="bg-bullish-bg text-profit text-xs">Run complete</Badge>
          </div>
          <p className="text-xs text-text-muted mb-4">
            Showing results from the most recent backtest run. Run a new backtest from the
            Backtest tab to refresh.
          </p>
        </Card>
        <BacktestResultDisplay result={lastResult} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Performance Results
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Compare backtest runs side by side, view equity curves, drawdown analysis, and
          detailed trade logs. Export results to CSV or share with your team.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            "Sharpe Ratio",
            "Sortino Ratio",
            "Max Drawdown",
            "Win Rate",
            "Profit Factor",
            "Avg Trade",
            "Total Trades",
            "Expectancy",
          ].map((metric) => (
            <div
              key={metric}
              className="bg-surface-base border border-border-default rounded-lg p-3 text-center"
            >
              <p className="text-xs text-text-muted">{metric}</p>
              <p className="text-sm font-mono text-text-secondary mt-1">--</p>
            </div>
          ))}
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-atm-bg text-warning text-xs">No data yet</Badge>
        <p className="text-sm text-text-muted mt-2">
          Run a backtest from the Backtest section to populate results here. Multi-run
          comparison and CSV export will be available in v0.2.0.
        </p>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lab Settings section
// ---------------------------------------------------------------------------

function LabSettingsSection() {
  return (
    <div className="space-y-4">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">
          Lab Settings
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Configure module-specific settings for backtesting, forward testing, and optimization.
        </p>
        <div className="space-y-4">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Default Instruments</h4>
            <p className="text-xs text-text-muted">
              Set default symbols for quick backtesting (e.g., NIFTY, BANKNIFTY, RELIANCE)
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Data Range</h4>
            <p className="text-xs text-text-muted">
              Default lookback period for historical data (1M, 3M, 6M, 1Y, 3Y, 5Y)
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Optimization Parameters</h4>
            <p className="text-xs text-text-muted">
              Default walk-forward window size, in-sample/out-of-sample split ratio, max iterations
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">Forward Test Defaults</h4>
            <p className="text-xs text-text-muted">
              Virtual capital, slippage model, commission assumptions
            </p>
          </div>
        </div>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <Badge className="bg-atm-bg text-warning text-xs">Coming in v0.2.0</Badge>
        <p className="text-sm text-text-muted mt-2">
          Settings will be persisted to workspace.json and configurable via form controls.
        </p>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export default function LabRoute() {
  const [activeSection, setActiveSection] = useState<SectionId>("backtest");
  const [lastResult, setLastResult] = useState<BacktestResult | null>(null);

  function renderSection(id: SectionId) {
    switch (id) {
      case "backtest":
        return <BacktestSection onResult={setLastResult} lastResult={lastResult} />;
      case "forward-test":
        return <ForwardTestSection />;
      case "optimize":
        return <OptimizeSection />;
      case "results":
        return <ResultsSection lastResult={lastResult} />;
      case "settings":
        return <LabSettingsSection />;
    }
  }

  return (
    <div className="h-full bg-surface-base flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card px-6 py-4">
        <div className="flex items-center gap-3">
          <Zap className="w-6 h-6 text-accent" />
          <div>
            <h1 className="font-heading font-bold text-lg text-text-primary">Strategy Lab</h1>
            <p className="text-xxs text-text-muted">
              Backtest, forward test, and optimize strategies — no broker has this built-in
            </p>
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <nav aria-label="Section navigation" className="w-56 border-r border-border-default bg-surface-card shrink-0 py-2">
          {SECTIONS.map((section) => {
            const Icon = section.icon;
            const isActive = activeSection === section.id;
            return (
              <button
                key={section.id}
                onClick={() => setActiveSection(section.id)}
                aria-current={isActive ? "true" : undefined}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm font-sans transition-colors ${
                  isActive
                    ? "text-accent bg-accent/10 border-l-2 border-accent"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-base"
                }`}
              >
                <Icon className="w-4 h-4" />
                {section.label}
                <ChevronRight className={`w-3 h-3 ml-auto ${isActive ? "opacity-100" : "opacity-0"}`} />
              </button>
            );
          })}
        </nav>

        {/* Content */}
        <ScrollArea className="flex-1">
          <div className="p-6 max-w-4xl">{renderSection(activeSection)}</div>
        </ScrollArea>
      </div>
    </div>
  );
}

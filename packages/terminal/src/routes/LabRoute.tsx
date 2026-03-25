import { useState, useMemo, useEffect } from "react";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useSkillStore } from "@/stores/skillStore";
import { SpotlightTour } from "@/components/help/SpotlightTour";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";
import { useQuery, useMutation } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Zap,
  FlaskConical,
  PlayCircle,
  TrendingUp,
  BarChart3,
  Loader2,
  AlertCircle,
  RefreshCw,
  Play,
  Square,
  Activity,
  Clock,
  ChevronDown,
  ChevronUp,
  Settings2,
} from "lucide-react";
import { AreaChart, BarChart } from "@tremor/react";
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
import { GlassCard } from "@/components/ui/GlassCard";
import TabTransition from "@/components/motion/TabTransition";
import { AnimatedCounter } from "@/components/magicui/animated-counter";
import { motionConfig } from "@/lib/motion";
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
// Tab registry — 4 primary horizontal tabs
// ---------------------------------------------------------------------------

type TabId = "backtest" | "forward-test" | "optimize" | "results";

interface TabDef {
  id: TabId;
  label: string;
  icon: typeof FlaskConical;
}

const TABS: TabDef[] = [
  { id: "backtest", label: "Backtest", icon: FlaskConical },
  { id: "forward-test", label: "Forward Test", icon: PlayCircle },
  { id: "optimize", label: "Optimize", icon: TrendingUp },
  { id: "results", label: "Results", icon: BarChart3 },
];

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function fmtInr(value: number): string {
  return value.toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  });
}

function fmtPct(value: number): string {
  return (value * 100).toFixed(2) + "%";
}

function fmtNum(value: number, decimals = 2): string {
  return value.toFixed(decimals);
}

// ---------------------------------------------------------------------------
// AnimatedMetricCard — uses AnimatedCounter for numeric values on change
// ---------------------------------------------------------------------------

interface AnimatedMetricCardProps {
  label: string;
  /** Raw numeric value — drives the AnimatedCounter */
  numericValue: number;
  /** Formatted display string (used when not animatable, e.g. "∞", "—") */
  displayValue: string;
  /** Whether to animate (only for finite numbers) */
  animate?: boolean;
  positive?: boolean | null;
  formatter?: (v: number) => string;
}

function AnimatedMetricCard({
  label,
  numericValue,
  displayValue,
  animate = true,
  positive,
  formatter,
}: AnimatedMetricCardProps) {
  const valueColor =
    positive === true
      ? "text-profit"
      : positive === false
        ? "text-loss"
        : "text-text-primary";

  const isFiniteNumber =
    animate && isFinite(numericValue) && displayValue !== "—";

  return (
    <GlassCard className="p-4 text-center gap-1">
      <p className="text-xs text-text-muted mb-1 uppercase tracking-wider">
        {label}
      </p>
      <p className={`text-sm font-mono font-semibold ${valueColor}`}>
        {isFiniteNumber ? (
          <AnimatedCounter
            value={numericValue}
            formatter={formatter}
            duration={1.2}
            className={valueColor}
          />
        ) : (
          displayValue
        )}
      </p>
    </GlassCard>
  );
}

// ---------------------------------------------------------------------------
// Standard MetricCard (non-animated) — kept for inline use
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
    <GlassCard className="p-4 text-center gap-1">
      <p className="text-xs text-text-muted mb-1 uppercase tracking-wider">
        {label}
      </p>
      <p className={`text-sm font-mono font-semibold ${valueColor}`}>
        {value}
      </p>
    </GlassCard>
  );
}

// ---------------------------------------------------------------------------
// Equity curve — Tremor AreaChart wrapped in fade-in motion.div
// ---------------------------------------------------------------------------

interface EquityCurveProps {
  curve: Array<{ timestamp: string; equity: number }>;
  initialEquity: number;
}

function EquityCurve({ curve, initialEquity }: EquityCurveProps) {
  if (curve.length === 0) return null;

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
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={motionConfig.transitions.fade}
    >
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
    </motion.div>
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
  const initialEquity =
    equity_curve.length > 0 ? equity_curve[0].equity : final_equity;

  const monthlyPnl = useMemo(() => {
    const grouped: Record<string, number> = {};
    trades.forEach((t) => {
      const month = t.exit_timestamp.slice(0, 7);
      grouped[month] = (grouped[month] ?? 0) + t.pnl;
    });
    return Object.entries(grouped)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, pnl]) => ({ month, "P&L": pnl }));
  }, [trades]);

  return (
    <div className="space-y-4">
      {/* Key metrics with AnimatedCounter */}
      <GlassCard className="p-5 gap-3">
        <h4 className="font-heading font-semibold text-sm text-text-primary">
          Performance Metrics
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {/* Animated key metrics */}
          <AnimatedMetricCard
            label="Sharpe Ratio"
            numericValue={metrics.sharpe_ratio}
            displayValue={fmtNum(metrics.sharpe_ratio)}
            positive={metrics.sharpe_ratio > 1}
            formatter={(v) => v.toFixed(2)}
          />
          <AnimatedMetricCard
            label="Max Drawdown"
            numericValue={Math.abs(metrics.max_drawdown) * 100}
            displayValue={fmtPct(Math.abs(metrics.max_drawdown))}
            positive={false}
            formatter={(v) => v.toFixed(2) + "%"}
          />
          <AnimatedMetricCard
            label="Win Rate"
            numericValue={metrics.win_rate * 100}
            displayValue={fmtPct(metrics.win_rate)}
            positive={metrics.win_rate >= 0.5}
            formatter={(v) => v.toFixed(2) + "%"}
          />
          <AnimatedMetricCard
            label="Profit Factor"
            numericValue={metrics.profit_factor}
            displayValue={fmtNum(metrics.profit_factor)}
            positive={metrics.profit_factor > 1}
            formatter={(v) => v.toFixed(2)}
          />
          {/* Non-animated supplemental metrics */}
          <MetricCard
            label="Total Return"
            value={fmtPct(metrics.total_return)}
            positive={totalReturnPositive}
          />
          <MetricCard
            label="Final Equity"
            value={fmtInr(final_equity)}
            positive={null}
          />
          <MetricCard
            label="Sortino Ratio"
            value={fmtNum(metrics.sortino_ratio)}
            positive={metrics.sortino_ratio > 1}
          />
          <MetricCard
            label="Total Trades"
            value={String(metrics.total_trades)}
            positive={null}
          />
          <MetricCard
            label="Expectancy"
            value={fmtInr(metrics.expectancy)}
            positive={metrics.expectancy >= 0}
          />
        </div>
      </GlassCard>

      {/* Equity curve */}
      {equity_curve.length > 0 && (
        <GlassCard className="p-5 gap-3">
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            Equity Curve
          </h4>
          <EquityCurve curve={equity_curve} initialEquity={initialEquity} />
        </GlassCard>
      )}

      {/* Monthly P&L breakdown */}
      {monthlyPnl.length > 0 && (
        <GlassCard className="p-5 gap-3">
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            Monthly P&L
          </h4>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={motionConfig.transitions.fade}
          >
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
          </motion.div>
        </GlassCard>
      )}

      {/* Trade list */}
      {trades.length > 0 && (
        <GlassCard className="p-5 gap-3">
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            Trade Log
            <span className="ml-2 text-xs text-text-muted font-normal">
              ({trades.length} trades)
            </span>
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
                    <TableCell className="text-xs font-mono text-text-primary">
                      {trade.symbol}
                    </TableCell>
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
        </GlassCard>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Backtest config panel — collapsible left panel
// ---------------------------------------------------------------------------

interface BacktestConfigPanelProps {
  symbol: string;
  onSymbol: (v: string) => void;
  exchange: string;
  onExchange: (v: string) => void;
  interval: string;
  onInterval: (v: string) => void;
  startDate: string;
  onStartDate: (v: string) => void;
  endDate: string;
  onEndDate: (v: string) => void;
  initialCapital: number;
  onInitialCapital: (v: number) => void;
  positionSizePct: number;
  onPositionSizePct: (v: number) => void;
  selectedStrategy: string;
  onStrategy: (v: string) => void;
  strategiesQuery: ReturnType<typeof useQuery<StrategyInfo[], Error>>;
  isRunning: boolean;
  runError: Error | null;
  onRun: () => void;
  isSuccess: boolean;
  onRetry: () => void;
}

function BacktestConfigPanel({
  symbol,
  onSymbol,
  exchange,
  onExchange,
  interval,
  onInterval,
  startDate,
  onStartDate,
  endDate,
  onEndDate,
  initialCapital,
  onInitialCapital,
  positionSizePct,
  onPositionSizePct,
  selectedStrategy,
  onStrategy,
  strategiesQuery,
  isRunning,
  runError,
  onRun,
  isSuccess,
  onRetry,
}: BacktestConfigPanelProps) {
  const [collapsed, setCollapsed] = useState(false);

  const strategiesByCategory = (strategiesQuery.data ?? []).reduce<
    Record<string, StrategyInfo[]>
  >((acc, s) => {
    const cat = s.category || "Other";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(s);
    return acc;
  }, {});

  return (
    <GlassCard className="flex flex-col gap-0 p-0 overflow-hidden">
      {/* Panel header — always visible, click to collapse */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex items-center justify-between px-4 py-3 border-b border-border-default hover:bg-surface-base/50 transition-colors w-full text-left"
        aria-expanded={!collapsed}
        aria-controls="backtest-config-body"
      >
        <div className="flex items-center gap-2">
          <Settings2 className="w-3.5 h-3.5 text-text-muted" />
          <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            Configuration
          </span>
        </div>
        {collapsed ? (
          <ChevronDown className="w-3.5 h-3.5 text-text-muted" />
        ) : (
          <ChevronUp className="w-3.5 h-3.5 text-text-muted" />
        )}
      </button>

      {/* Collapsible body */}
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            id="backtest-config-body"
            key="config-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{
              height: { duration: motionConfig.duration.slow, ease: motionConfig.ease.enter },
              opacity: { duration: motionConfig.duration.normal },
            }}
            style={{ overflow: "hidden" }}
          >
            <div className="p-4 space-y-3">
              {/* Strategy selector */}
              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">Strategy</Label>
                {strategiesQuery.isLoading ? (
                  <div className="flex items-center gap-2 text-xs text-text-muted h-9">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Loading…
                  </div>
                ) : strategiesQuery.isError ? (
                  <div className="flex items-center gap-2 text-xs text-loss h-9">
                    <AlertCircle className="w-3 h-3" />
                    Failed
                    <button
                      onClick={() => strategiesQuery.refetch()}
                      className="underline hover:no-underline"
                    >
                      Retry
                    </button>
                  </div>
                ) : (
                  <Select value={selectedStrategy} onValueChange={onStrategy}>
                    <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                      <SelectValue placeholder="Select a strategy…" />
                    </SelectTrigger>
                    <SelectContent className="bg-surface-card border-border-default">
                      {Object.entries(strategiesByCategory).map(
                        ([category, strategies]) => (
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
                                  <span className="ml-2 text-text-muted text-xs">
                                    — {s.description}
                                  </span>
                                )}
                              </SelectItem>
                            ))}
                          </div>
                        ),
                      )}
                    </SelectContent>
                  </Select>
                )}
              </div>

              {/* Symbol */}
              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">Symbol</Label>
                <Input
                  value={symbol}
                  onChange={(e) => onSymbol(e.target.value.toUpperCase())}
                  placeholder="NIFTY"
                  className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
                />
              </div>

              {/* Exchange */}
              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">Exchange</Label>
                <Select value={exchange} onValueChange={onExchange}>
                  <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default">
                    {["NFO", "NSE", "BSE", "MCX", "CDS"].map((ex) => (
                      <SelectItem
                        key={ex}
                        value={ex}
                        className="text-text-primary text-sm font-mono"
                      >
                        {ex}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Interval */}
              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">Interval</Label>
                <Select value={interval} onValueChange={onInterval}>
                  <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default">
                    {["1m", "3m", "5m", "10m", "15m", "30m", "1h", "D", "W"].map(
                      (iv) => (
                        <SelectItem
                          key={iv}
                          value={iv}
                          className="text-text-primary text-sm font-mono"
                        >
                          {iv}
                        </SelectItem>
                      ),
                    )}
                  </SelectContent>
                </Select>
              </div>

              {/* Start date */}
              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">Start Date</Label>
                <Input
                  type="date"
                  value={startDate}
                  onChange={(e) => onStartDate(e.target.value)}
                  className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
                />
              </div>

              {/* End date */}
              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">End Date</Label>
                <Input
                  type="date"
                  value={endDate}
                  onChange={(e) => onEndDate(e.target.value)}
                  className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
                />
              </div>

              {/* Initial capital */}
              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">
                  Capital (₹)
                </Label>
                <Input
                  type="number"
                  min={1000}
                  step={10000}
                  value={initialCapital}
                  onChange={(e) => onInitialCapital(Number(e.target.value))}
                  className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
                />
              </div>

              {/* Position size */}
              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">
                  Position Size (%)
                </Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={positionSizePct}
                  onChange={(e) => onPositionSizePct(Number(e.target.value))}
                  className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
                />
              </div>

              {/* Run button */}
              <Button
                onClick={onRun}
                disabled={isRunning || !selectedStrategy}
                className="w-full bg-accent text-white hover:bg-accent/90 font-sans text-sm"
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

              {isSuccess && (
                <p className="text-xs text-profit text-center">
                  Backtest complete.
                </p>
              )}

              {runError && (
                <div className="flex items-center gap-2 text-xs text-loss">
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                  <span className="flex-1 truncate">{runError.message}</span>
                  <button
                    onClick={onRetry}
                    className="flex items-center gap-1 underline hover:no-underline shrink-0"
                  >
                    <RefreshCw className="w-3 h-3" />
                    Retry
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </GlassCard>
  );
}

// ---------------------------------------------------------------------------
// Backtest section — split layout: config left, results right
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
    <div className="flex flex-col md:flex-row gap-4 items-start">
      {/* Left: collapsible config panel — fixed width on md+, full width on mobile */}
      <div className="w-full md:w-64 md:shrink-0">
        <BacktestConfigPanel
          symbol={symbol}
          onSymbol={setSymbol}
          exchange={exchange}
          onExchange={setExchange}
          interval={interval}
          onInterval={setInterval}
          startDate={startDate}
          onStartDate={setStartDate}
          endDate={endDate}
          onEndDate={setEndDate}
          initialCapital={initialCapital}
          onInitialCapital={setInitialCapital}
          positionSizePct={positionSizePct}
          onPositionSizePct={setPositionSizePct}
          selectedStrategy={selectedStrategy}
          onStrategy={setSelectedStrategy}
          strategiesQuery={strategiesQuery}
          isRunning={isRunning}
          runError={runError}
          onRun={handleRun}
          isSuccess={backtestMutation.isSuccess}
          onRetry={handleRun}
        />
      </div>

      {/* Right: results panel */}
      <div className="flex-1 min-w-0">
        {isRunning ? (
          <GlassCard className="p-6 flex items-center gap-3">
            <Loader2 className="w-5 h-5 text-accent animate-spin" />
            <p className="text-sm text-text-secondary">
              Running backtest… this may take a few seconds.
            </p>
          </GlassCard>
        ) : lastResult ? (
          <BacktestResultDisplay result={lastResult} />
        ) : (
          <GlassCard className="p-8 text-center gap-2">
            <FlaskConical className="w-8 h-8 text-text-muted mx-auto mb-2" />
            <p className="text-sm font-semibold text-text-secondary">
              No results yet
            </p>
            <p className="text-xs text-text-muted">
              Configure and run a backtest to see performance metrics, equity
              curve, and trade log.
            </p>
          </GlassCard>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Forward test — duration display helper
// ---------------------------------------------------------------------------

function useDuration(startedAt: string | null): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAt) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  if (!startedAt) return "00:00";
  const diff = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const m = String(Math.floor(diff / 60)).padStart(2, "0");
  const s = String(diff % 60).padStart(2, "0");
  return `${m}:${s}`;
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
                {trade.exit_timestamp ? (
                  trade.exit_timestamp.slice(0, 16).replace("T", " ")
                ) : (
                  <span className="text-warning">Open</span>
                )}
              </TableCell>
              <TableCell className="text-xs font-mono text-text-primary">
                {trade.symbol}
              </TableCell>
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
// Forward monitor panel (shown while running)
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

  const totalPnl =
    running.virtual_pnl ?? closedTrades.reduce((sum, t) => sum + t.pnl, 0);
  const wins = closedTrades.filter((t) => t.pnl > 0).length;
  const winRate = closedTrades.length > 0 ? wins / closedTrades.length : 0;
  const grossWin = closedTrades
    .filter((t) => t.pnl > 0)
    .reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(
    closedTrades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0),
  );
  const profitFactor =
    grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0;

  return (
    <div className="space-y-4">
      {/* Status bar */}
      <GlassCard className="p-4 gap-0">
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
            <span className="text-xs text-text-muted font-mono">
              {running.symbol} / {running.exchange}
            </span>
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
      </GlassCard>

      {/* Live metrics — animated counters */}
      <GlassCard className="p-5 gap-3">
        <h4 className="font-heading font-semibold text-sm text-text-primary">
          Live Performance
          {tradesQuery.isFetching && (
            <Loader2 className="inline-block w-3 h-3 ml-2 animate-spin text-text-muted" />
          )}
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <AnimatedMetricCard
            label="Win Rate"
            numericValue={winRate * 100}
            displayValue={
              closedTrades.length > 0 ? fmtPct(winRate) : "—"
            }
            animate={closedTrades.length > 0}
            positive={winRate >= 0.5}
            formatter={(v) => v.toFixed(2) + "%"}
          />
          <AnimatedMetricCard
            label="Profit Factor"
            numericValue={isFinite(profitFactor) ? profitFactor : 0}
            displayValue={
              profitFactor === Infinity
                ? "∞"
                : closedTrades.length > 0
                  ? fmtNum(profitFactor)
                  : "—"
            }
            animate={closedTrades.length > 0 && isFinite(profitFactor)}
            positive={
              profitFactor > 1 ? true : profitFactor === 0 ? null : false
            }
            formatter={(v) => v.toFixed(2)}
          />
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
            label="Open Trades"
            value={String(trades.length - closedTrades.length)}
            positive={null}
          />
        </div>
      </GlassCard>

      {/* Virtual trades table */}
      <GlassCard className="p-5 gap-3">
        <h4 className="font-heading font-semibold text-sm text-text-primary">
          Virtual Trade Log
          <span className="ml-2 text-xs text-text-muted font-normal">
            ({trades.length} trade{trades.length !== 1 ? "s" : ""})
          </span>
        </h4>
        <ForwardTradesTable trades={trades} />
      </GlassCard>
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
  const [activeStrategyName, setActiveStrategyName] = useState<string | null>(
    null,
  );
  const [stoppedSummary, setStoppedSummary] = useState<{
    trades: ForwardTrade[];
    pnl: number;
  } | null>(null);

  const strategiesQuery = useQuery<StrategyInfo[], Error>({
    queryKey: ["strategies"],
    queryFn: getStrategies,
  });

  const runningQuery = useQuery<RunningStrategy[], Error>({
    queryKey: ["runningStrategies"],
    queryFn: getRunningStrategies,
    refetchInterval: ftState === "running" ? 5000 : false,
    enabled: ftState === "running",
  });

  const activeRunning =
    runningQuery.data?.find((s) => s.name === activeStrategyName) ?? null;

  useEffect(() => {
    if (ftState === "running" && activeStrategyName && runningQuery.data) {
      const found = runningQuery.data.find(
        (s) => s.name === activeStrategyName,
      );
      if (!found) {
        setFtState("stopped");
      }
    }
  }, [ftState, activeStrategyName, runningQuery.data]);

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

  if (ftState === "idle" || ftState === "stopped") {
    const closedTrades =
      stoppedSummary?.trades.filter((t) => t.exit_price > 0) ?? [];
    const wins = closedTrades.filter((t) => t.pnl > 0).length;
    const winRate =
      closedTrades.length > 0 ? wins / closedTrades.length : 0;
    const grossWin = closedTrades
      .filter((t) => t.pnl > 0)
      .reduce((s, t) => s + t.pnl, 0);
    const grossLoss = Math.abs(
      closedTrades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0),
    );
    const profitFactor =
      grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0;

    return (
      <div className="space-y-4">
        {/* Stopped summary */}
        {ftState === "stopped" && stoppedSummary && (
          <GlassCard className="p-5 gap-3">
            <div className="flex items-center justify-between">
              <h4 className="font-heading font-semibold text-sm text-text-primary">
                Session Summary
              </h4>
              <Badge className="bg-text-muted/10 text-text-muted text-xs border-0">
                Stopped
              </Badge>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
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
                positive={
                  profitFactor > 1 ? true : profitFactor === 0 ? null : false
                }
              />
            </div>
            {stoppedSummary.trades.length > 0 && (
              <>
                <h5 className="text-xs font-semibold text-text-secondary">
                  Trade Log
                  <span className="ml-2 text-text-muted font-normal">
                    (
                    {stoppedSummary.trades.length} trade
                    {stoppedSummary.trades.length !== 1 ? "s" : ""})
                  </span>
                </h5>
                <ForwardTradesTable trades={stoppedSummary.trades} />
              </>
            )}
          </GlassCard>
        )}

        {/* Config form */}
        <GlassCard className="p-6 gap-4">
          <h3 className="font-heading font-semibold text-lg text-text-primary">
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
                <Select
                  value={selectedStrategy}
                  onValueChange={setSelectedStrategy}
                >
                  <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                    <SelectValue placeholder="Select a strategy…" />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default">
                    {Object.entries(strategiesByCategory).map(
                      ([category, strategies]) => (
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
                                <span className="ml-2 text-text-muted text-xs">
                                  — {s.description}
                                </span>
                              )}
                            </SelectItem>
                          ))}
                        </div>
                      ),
                    )}
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
                    <SelectItem
                      key={ex}
                      value={ex}
                      className="text-text-primary text-sm font-mono"
                    >
                      {ex}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Virtual capital */}
            <div className="space-y-1.5">
              <Label className="text-xs text-text-secondary">
                Virtual Capital (₹)
              </Label>
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
              <Label className="text-xs text-text-secondary">
                Position Size (%)
              </Label>
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
          <div className="flex items-center gap-3">
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
        </GlassCard>
      </div>
    );
  }

  if (ftState === "running" && activeRunning) {
    return (
      <ForwardMonitor
        running={activeRunning}
        onStop={() => stopMutation.mutate()}
        isStopping={stopMutation.isPending}
      />
    );
  }

  return (
    <GlassCard className="p-6 flex items-center gap-3">
      <Loader2 className="w-5 h-5 text-accent animate-spin" />
      <p className="text-sm text-text-secondary">
        Starting forward test… waiting for strategy engine.
      </p>
    </GlassCard>
  );
}

// ---------------------------------------------------------------------------
// Optimize section
// ---------------------------------------------------------------------------

function OptimizeSection() {
  return (
    <div className="space-y-4">
      <GlassCard className="p-6 gap-4">
        <h3 className="font-heading font-semibold text-lg text-text-primary">
          Walk-Forward Optimization
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed">
          Optimize strategy parameters using walk-forward analysis to avoid
          overfitting. The optimizer splits historical data into in-sample
          (training) and out-of-sample (validation) windows, finding parameters
          that generalize across market regimes.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">
              Methods
            </h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Grid Search</li>
              <li>Random Search</li>
              <li>Walk-Forward Windows</li>
              <li>Monte Carlo Validation</li>
            </ul>
          </div>
          <div className="bg-surface-base border border-border-default rounded-lg p-4">
            <h4 className="text-sm font-semibold text-text-primary mb-1">
              Objective Functions
            </h4>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>Maximize Sharpe Ratio</li>
              <li>Maximize Sortino Ratio</li>
              <li>Minimize Max Drawdown</li>
              <li>Maximize Profit Factor</li>
            </ul>
          </div>
        </div>
      </GlassCard>
      <GlassCard className="p-4 gap-2">
        <Badge className="bg-atm-bg text-warning text-xs">
          Coming in v0.2.0
        </Badge>
        <p className="text-sm text-text-muted">
          Parameter optimization UI will be available in the next release. The
          Python backtest-engine package already supports walk-forward
          optimization via{" "}
          <code className="text-xxs bg-surface-base px-1 py-0.5 rounded font-mono">
            Optimizer.optimize()
          </code>
          .
        </p>
      </GlassCard>
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
        <GlassCard className="p-5 gap-3">
          <div className="flex items-center justify-between">
            <h3 className="font-heading font-semibold text-lg text-text-primary">
              Last Backtest Results
            </h3>
            <Badge className="bg-bullish-bg text-profit text-xs">
              Run complete
            </Badge>
          </div>
          <p className="text-xs text-text-muted">
            Showing results from the most recent backtest run. Run a new
            backtest from the Backtest tab to refresh.
          </p>
        </GlassCard>
        <BacktestResultDisplay result={lastResult} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <GlassCard className="p-6 gap-4">
        <h3 className="font-heading font-semibold text-lg text-text-primary">
          Performance Results
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed">
          Compare backtest runs side by side, view equity curves, drawdown
          analysis, and detailed trade logs. Export results to CSV or share
          with your team.
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
      </GlassCard>
      <GlassCard className="p-4 gap-2">
        <Badge className="bg-atm-bg text-warning text-xs">No data yet</Badge>
        <p className="text-sm text-text-muted">
          Run a backtest from the Backtest section to populate results here.
          Multi-run comparison and CSV export will be available in v0.2.0.
        </p>
      </GlassCard>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Horizontal tab bar
// ---------------------------------------------------------------------------

interface LabTabBarProps {
  active: TabId;
  onChange: (id: TabId) => void;
  /** Filtered tab list based on skill level. Defaults to all TABS. */
  tabs?: TabDef[];
}

function LabTabBar({ active, onChange, tabs = TABS }: LabTabBarProps) {
  return (
    <div
      role="tablist"
      aria-label="Strategy Lab sections"
      className="flex items-center gap-1 border-b border-border-default bg-surface-card px-6"
    >
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = active === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            className={[
              "relative flex items-center gap-2 px-4 py-3 text-sm font-sans transition-colors select-none",
              isActive
                ? "text-accent"
                : "text-text-secondary hover:text-text-primary",
            ].join(" ")}
          >
            <Icon className="w-3.5 h-3.5" />
            {tab.label}
            {/* Active underline */}
            {isActive && (
              <motion.div
                layoutId="lab-tab-indicator"
                className="absolute bottom-0 left-0 right-0 h-0.5 bg-accent rounded-t"
                transition={motionConfig.transitions.tab}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main LabRoute
// ---------------------------------------------------------------------------

export default function LabRoute() {
  useEffect(() => { useSkillStore.getState().trackAction("lab", "daysActive"); }, []);

  const [activeTab, setActiveTab] = useState<TabId>("backtest");
  const [lastResult, setLastResult] = useState<BacktestResult | null>(null);
  const level = useSkillLevel("lab");

  // Density adaptation:
  // Beginner: Show only Backtest tab (simplified "Try a Strategy" entry point) + Results
  // Intermediate: Full form + Results (all except Optimize)
  // Advanced: All tabs including Optimize (Monte Carlo / walk-forward)
  const visibleTabIds: TabId[] = (() => {
    if (level === "beginner") return ["backtest", "results"];
    if (level === "intermediate") return ["backtest", "forward-test", "results"];
    return ["backtest", "forward-test", "optimize", "results"];
  })();

  const visibleTabs = TABS.filter((t) => visibleTabIds.includes(t.id));

  function renderTab(id: TabId) {
    switch (id) {
      case "backtest":
        return (
          <BacktestSection onResult={setLastResult} lastResult={lastResult} />
        );
      case "forward-test":
        return <ForwardTestSection />;
      case "optimize":
        return <OptimizeSection />;
      case "results":
        return <ResultsSection lastResult={lastResult} />;
    }
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card px-6 pt-4 pb-0">
        <div className="flex items-center gap-3 pb-3" data-tour-target="strategy-picker">
          <Zap className="w-6 h-6 text-accent" />
          <div>
            <h1 className="font-heading font-bold text-lg text-text-primary">
              {level === "beginner" ? "Try a Strategy" : "Strategy Lab"}
            </h1>
            <p className="text-xxs text-text-muted">
              {level === "beginner"
                ? "Pick a built-in strategy and run a backtest — no code needed"
                : "Backtest, forward test, and optimize strategies — no broker has this built-in"}
            </p>
          </div>
        </div>
        {/* Horizontal tab bar — filtered by skill level */}
        <LabTabBar active={activeTab} onChange={setActiveTab} tabs={visibleTabs} />
      </div>

      {/* Tab content */}
      <ScrollArea className="flex-1">
        <div className="p-6 max-w-5xl mx-auto" data-tour-target="backtest-results">
          <TabTransition tabKey={activeTab}>
            {renderTab(activeTab)}
          </TabTransition>
        </div>
      </ScrollArea>

      {/* Guided tour — beginner only, first visit */}
      {level === "beginner" && (
        <SpotlightTour
          tourId="lab-beginner"
          steps={TOUR_DEFINITIONS["lab-beginner"] ?? []}
        />
      )}
    </div>
  );
}

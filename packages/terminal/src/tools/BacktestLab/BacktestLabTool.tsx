/**
 * BacktestLabTool — Backtest configuration and results UI
 * Absorbed patterns from:
 *   - trading-strategies-openalgo: metric categories (Sharpe, drawdown, win rate, tax)
 *   - VectorBT-Tearsheets: EMA crossover, equity curve structure, QuantStats metrics
 */

import { useState, useEffect, useRef } from "react";
import { createChart, LineSeries } from "lightweight-charts";
import type { IChartApi } from "lightweight-charts";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  X,
  FlaskConical,
  Play,
  AlertCircle,
  TrendingUp,
  TrendingDown,
  BarChart2,
  Clock,
  ArrowUpDown,
  CheckCircle2,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
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
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";

// ---------------------------------------------------------------------------
// Schema (react-hook-form + zod)
// ---------------------------------------------------------------------------

const backtestSchema = z.object({
  strategy: z.string().min(1, "Select a strategy"),
  symbol: z.string().min(1, "Symbol required").toUpperCase(),
  exchange: z.string().min(1, "Select exchange"),
  fromDate: z.string().min(1, "From date required"),
  toDate: z.string().min(1, "To date required"),
  timeframe: z.string().min(1, "Select timeframe"),
  capital: z
    .string()
    .min(1, "Capital required")
    .refine((v) => !isNaN(Number(v)) && Number(v) > 0, "Must be positive"),
  // Strategy-specific params (serialized as JSON string for flexibility)
  fastPeriod: z.string().optional(),
  slowPeriod: z.string().optional(),
  atrMultiplier: z.string().optional(),
  gridLevels: z.string().optional(),
});

type BacktestFormValues = z.infer<typeof backtestSchema>;

// ---------------------------------------------------------------------------
// Constants — absorbed from trading-strategies-openalgo and VectorBT-Tearsheets
// ---------------------------------------------------------------------------

interface StrategyDef {
  id: string;
  name: string;
  description: string;
  category: string;
  params: string[];
}

const STRATEGIES: StrategyDef[] = [
  {
    id: "ema_crossover",
    name: "EMA Crossover",
    description: "Fast/slow EMA crossover — entry on bullish cross, exit on bearish",
    category: "Trend",
    params: ["fastPeriod", "slowPeriod"],
  },
  {
    id: "supertrend",
    name: "Supertrend",
    description: "ATR-based dynamic support/resistance trend follower",
    category: "Trend",
    params: ["atrMultiplier"],
  },
  {
    id: "grid_trading",
    name: "Grid Trading",
    description: "Arithmetic grid with configurable levels and risk boundaries",
    category: "Mean Reversion",
    params: ["gridLevels"],
  },
  {
    id: "rsi_mean_reversion",
    name: "RSI Mean Reversion",
    description: "Buy oversold, sell overbought using RSI oscillator",
    category: "Mean Reversion",
    params: [],
  },
  {
    id: "vwap_deviation",
    name: "VWAP Deviation",
    description: "Trade deviations from Volume Weighted Average Price",
    category: "Statistical",
    params: [],
  },
];

const EXCHANGES = ["NSE", "BSE", "NFO", "BFO", "MCX", "CDS"] as const;
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "1d"] as const;

// ---------------------------------------------------------------------------
// Equity curve data type — shared between mock data and API response shape
// ---------------------------------------------------------------------------

interface EquityPoint {
  time: number; // Unix timestamp (seconds)
  value: number; // Portfolio value (₹)
}

// ---------------------------------------------------------------------------
// Mock results structure — ready for API integration
// ---------------------------------------------------------------------------

// Mock equity curve derived from MOCK_TRADES cumulative P&L on ₹10,00,000 capital.
// Each point represents a trade exit date. Replace with real API data when backend connects.
const MOCK_EQUITY_CURVE: EquityPoint[] = [
  { time: 1705276800, value: 1000000 }, // 2024-01-15 — start
  { time: 1705881600, value: 1005050 }, // 2024-01-22 — trade 1 exit
  { time: 1707350400, value: 1008400 }, // 2024-02-12 — trade 2 exit
  { time: 1709596800, value: 1005080 }, // 2024-03-04 — trade 3 exit
  { time: 1711324800, value: 1013955 }, // 2024-03-25 — trade 4 exit
  { time: 1713398400, value: 1011745 }, // 2024-04-17 — trade 5 exit
];

interface BacktestMetric {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean | null;
}

interface MockTrade {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  entryDate: string;
  exitDate: string;
  entryPrice: number;
  exitPrice: number;
  qty: number;
  pnl: number;
  pnlPct: number;
  holdingPeriod: string;
}

// Absorbed metric categories from trading-strategies-openalgo README
const MOCK_RETURN_METRICS: BacktestMetric[] = [
  { label: "Total Return", value: "+24.7%", sub: "₹2,47,000 on ₹10,00,000", positive: true },
  { label: "Annualised Return", value: "+18.3%", sub: "CAGR", positive: true },
  { label: "Benchmark Return", value: "+12.1%", sub: "Nifty 50", positive: true },
  { label: "Alpha", value: "+6.2%", sub: "vs benchmark", positive: true },
];

const MOCK_RISK_METRICS: BacktestMetric[] = [
  { label: "Sharpe Ratio", value: "1.84", sub: "Risk-adjusted return", positive: true },
  { label: "Sortino Ratio", value: "2.31", sub: "Downside deviation", positive: true },
  { label: "Max Drawdown", value: "-11.4%", sub: "Peak to trough", positive: false },
  { label: "Calmar Ratio", value: "1.61", sub: "Return / Max DD", positive: true },
];

const MOCK_TRADE_METRICS: BacktestMetric[] = [
  { label: "Total Trades", value: "147", sub: "Signals executed", positive: null },
  { label: "Win Rate", value: "58.5%", sub: "86 wins / 61 losses", positive: true },
  { label: "Profit Factor", value: "1.72", sub: "Gross profit / loss", positive: true },
  { label: "Avg Trade P&L", value: "+₹1,680", sub: "Per trade", positive: true },
  { label: "Avg Winner", value: "+₹4,210", positive: true },
  { label: "Avg Loser", value: "-₹2,450", positive: false },
  { label: "Max Consec. Wins", value: "9", positive: null },
  { label: "Max Consec. Losses", value: "5", positive: null },
];

const MOCK_TRADES: MockTrade[] = [
  { id: 1, symbol: "RELIANCE", side: "BUY", entryDate: "2024-01-15", exitDate: "2024-01-22", entryPrice: 2480.5, exitPrice: 2531.0, qty: 10, pnl: 505, pnlPct: 2.04, holdingPeriod: "7d" },
  { id: 2, symbol: "RELIANCE", side: "SELL", entryDate: "2024-02-05", exitDate: "2024-02-12", entryPrice: 2610.0, exitPrice: 2575.5, qty: 10, pnl: 345, pnlPct: 1.32, holdingPeriod: "7d" },
  { id: 3, symbol: "RELIANCE", side: "BUY", entryDate: "2024-02-28", exitDate: "2024-03-04", entryPrice: 2520.0, exitPrice: 2488.0, qty: 10, pnl: -320, pnlPct: -1.27, holdingPeriod: "5d" },
  { id: 4, symbol: "RELIANCE", side: "BUY", entryDate: "2024-03-18", exitDate: "2024-03-25", entryPrice: 2555.0, exitPrice: 2642.5, qty: 10, pnl: 875, pnlPct: 3.43, holdingPeriod: "7d" },
  { id: 5, symbol: "RELIANCE", side: "SELL", entryDate: "2024-04-10", exitDate: "2024-04-17", entryPrice: 2680.0, exitPrice: 2701.0, qty: 10, pnl: -210, pnlPct: -0.78, holdingPeriod: "7d" },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetricCard({ metric }: { metric: BacktestMetric }) {
  return (
    <Card className="bg-surface-card border-border-default">
      <CardContent className="pt-4 pb-3 px-4">
        <div className="text-xs text-text-muted mb-1">{metric.label}</div>
        <div
          className={[
            "font-mono tabular-nums text-lg font-semibold leading-none",
            metric.positive === true
              ? "text-emerald-400"
              : metric.positive === false
              ? "text-red-400"
              : "text-text-primary",
          ].join(" ")}
        >
          {metric.value}
        </div>
        {metric.sub && (
          <div className="text-xs text-text-muted mt-1">{metric.sub}</div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// EquityCurveChart — real Lightweight Charts line chart for equity curve data.
// Falls back to SVG placeholder when no data points are provided.
// ---------------------------------------------------------------------------

function EquityCurvePlaceholder() {
  const points = [0, 2, 5, 3, 8, 6, 12, 10, 15, 13, 18, 22, 20, 25, 24];
  const w = 600;
  const h = 120;
  const maxV = Math.max(...points);
  const coords = points
    .map((v, i) => `${(i / (points.length - 1)) * w},${h - (v / maxV) * (h - 10)}`)
    .join(" ");

  return (
    <div className="relative w-full h-35 bg-surface-base rounded-md border border-border-default flex items-center justify-center overflow-hidden">
      <svg
        className="absolute inset-0 w-full h-full opacity-40"
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#34d399" stopOpacity="0" />
          </linearGradient>
        </defs>
        <polyline points={coords} fill="none" stroke="#34d399" strokeWidth="2" />
        <polygon points={`0,${h} ${coords} ${w},${h}`} fill="url(#eqGrad)" />
      </svg>
      <div className="relative text-xs text-text-muted text-center">
        <BarChart2 size={20} className="mx-auto mb-1 opacity-40" />
        Equity curve renders here when backtest-engine API is connected
      </div>
    </div>
  );
}

function EquityCurveChart({ data }: { data: EquityPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    const bg = getComputedStyle(document.documentElement).getPropertyValue("--color-base").trim() || "#0a0a0f";
    const gridColor = getComputedStyle(document.documentElement).getPropertyValue("--color-border").trim() || "#2a2a3a";
    const textColor = getComputedStyle(document.documentElement).getPropertyValue("--color-text-muted").trim() || "#6b7280";

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 140,
      layout: { background: { color: bg }, textColor },
      grid: { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      crosshair: { vertLine: { visible: true }, horzLine: { visible: true } },
      rightPriceScale: { borderColor: gridColor },
      timeScale: { borderColor: gridColor, timeVisible: true },
      handleScroll: false,
      handleScale: false,
    });

    const series = chart.addSeries(LineSeries, {
      color: "#34d399",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });

    // Lightweight Charts v5 expects UTCTimestamp (seconds) for time
    series.setData(
      data.map((p) => ({
        time: p.time as unknown as import("lightweight-charts").Time,
        value: p.value,
      }))
    );

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [data]);

  if (data.length === 0) return <EquityCurvePlaceholder />;

  return (
    <div
      ref={containerRef}
      className="w-full rounded-md border border-border-default overflow-hidden"
      style={{ height: 140 }}
    />
  );
}

// ---------------------------------------------------------------------------
// Configure Tab
// ---------------------------------------------------------------------------

function ConfigureTab({
  onRunRequest,
}: {
  onRunRequest: () => void;
}) {
  const { register, handleSubmit, control, watch, formState: { errors } } =
    useForm<BacktestFormValues>({
      resolver: zodResolver(backtestSchema),
      defaultValues: {
        strategy: "",
        symbol: "",
        exchange: "NSE",
        fromDate: "2024-01-01",
        toDate: "2024-12-31",
        timeframe: "1d",
        capital: "1000000",
        fastPeriod: "9",
        slowPeriod: "21",
        atrMultiplier: "3",
        gridLevels: "10",
      },
    });

  const selectedStrategy = watch("strategy");
  const stratDef = STRATEGIES.find((s) => s.id === selectedStrategy);

  const onSubmit = (_data: BacktestFormValues) => {
    onRunRequest();
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 p-4">
      {/* Strategy selector */}
      <div className="space-y-1.5">
        <Label className="text-xs text-text-secondary">Strategy</Label>
        <Controller
          name="strategy"
          control={control}
          render={({ field }) => (
            <Select onValueChange={field.onChange} value={field.value}>
              <SelectTrigger className="bg-surface-card border-border-default text-sm h-9">
                <SelectValue placeholder="Select strategy..." />
              </SelectTrigger>
              <SelectContent className="bg-surface-card border-border-default">
                {STRATEGIES.map((s) => (
                  <SelectItem key={s.id} value={s.id} className="text-sm">
                    <span className="flex items-center gap-2">
                      {s.name}
                      <Badge
                        variant="secondary"
                        className="text-xs h-4 px-1 bg-surface-elevated text-text-secondary"
                      >
                        {s.category}
                      </Badge>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        />
        {stratDef && (
          <p className="text-xs text-text-muted">{stratDef.description}</p>
        )}
        {errors.strategy && (
          <p className="text-xs text-red-400">{errors.strategy.message}</p>
        )}
      </div>

      {/* Symbol + Exchange row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-2 space-y-1.5">
          <Label className="text-xs text-text-secondary">Symbol</Label>
          <Input
            {...register("symbol")}
            placeholder="RELIANCE"
            className="bg-surface-card border-border-default font-mono text-sm h-9 uppercase"
          />
          {errors.symbol && (
            <p className="text-xs text-red-400">{errors.symbol.message}</p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-text-secondary">Exchange</Label>
          <Controller
            name="exchange"
            control={control}
            render={({ field }) => (
              <Select onValueChange={field.onChange} value={field.value}>
                <SelectTrigger className="bg-surface-card border-border-default text-sm h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-surface-card border-border-default">
                  {EXCHANGES.map((ex) => (
                    <SelectItem key={ex} value={ex} className="text-sm">
                      {ex}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>
      </div>

      {/* Date range + Timeframe */}
      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs text-text-secondary">From</Label>
          <Input
            {...register("fromDate")}
            type="date"
            className="bg-surface-card border-border-default text-sm h-9"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-text-secondary">To</Label>
          <Input
            {...register("toDate")}
            type="date"
            className="bg-surface-card border-border-default text-sm h-9"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-text-secondary">Timeframe</Label>
          <Controller
            name="timeframe"
            control={control}
            render={({ field }) => (
              <Select onValueChange={field.onChange} value={field.value}>
                <SelectTrigger className="bg-surface-card border-border-default text-sm h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-surface-card border-border-default">
                  {TIMEFRAMES.map((tf) => (
                    <SelectItem key={tf} value={tf} className="text-sm">
                      {tf}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>
      </div>

      {/* Capital */}
      <div className="space-y-1.5">
        <Label className="text-xs text-text-secondary">Initial Capital (₹)</Label>
        <Input
          {...register("capital")}
          placeholder="1000000"
          className="bg-surface-card border-border-default font-mono text-sm h-9"
        />
        {errors.capital && (
          <p className="text-xs text-red-400">{errors.capital.message}</p>
        )}
      </div>

      {/* Strategy-specific params */}
      {stratDef && stratDef.params.includes("fastPeriod") && (
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label className="text-xs text-text-secondary">Fast EMA Period</Label>
            <Input
              {...register("fastPeriod")}
              className="bg-surface-card border-border-default font-mono text-sm h-9"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-text-secondary">Slow EMA Period</Label>
            <Input
              {...register("slowPeriod")}
              className="bg-surface-card border-border-default font-mono text-sm h-9"
            />
          </div>
        </div>
      )}
      {stratDef && stratDef.params.includes("atrMultiplier") && (
        <div className="space-y-1.5">
          <Label className="text-xs text-text-secondary">ATR Multiplier</Label>
          <Input
            {...register("atrMultiplier")}
            className="bg-surface-card border-border-default font-mono text-sm h-9"
          />
        </div>
      )}
      {stratDef && stratDef.params.includes("gridLevels") && (
        <div className="space-y-1.5">
          <Label className="text-xs text-text-secondary">Grid Levels</Label>
          <Input
            {...register("gridLevels")}
            className="bg-surface-card border-border-default font-mono text-sm h-9"
          />
        </div>
      )}

      {/* Run button */}
      <Button
        type="submit"
        className="w-full h-9 bg-primary hover:bg-primary/90 text-white text-sm font-medium mt-2"
      >
        <Play size={14} className="mr-2" />
        Run Backtest
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Results Tab
// ---------------------------------------------------------------------------

function ResultsTab({ hasRun, equityCurve }: { hasRun: boolean; equityCurve: EquityPoint[] }) {
  if (!hasRun) {
    return (
      <div className="flex flex-col items-center justify-center h-40 text-center px-4 gap-2 mt-6">
        <FlaskConical size={28} className="text-text-disabled opacity-40" />
        <p className="text-xs text-text-muted">
          Configure and run a backtest to see results here.
        </p>
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-5">
        {/* Backend notice */}
        <div className="flex items-start gap-2 rounded-md bg-surface-elevated border border-border-default p-3">
          <AlertCircle size={14} className="text-amber-400 mt-0.5 shrink-0" />
          <p className="text-xs text-text-secondary">
            Backend not connected. Configure the backtest engine in{" "}
            <span className="text-primary">Settings</span>.
            Showing mock results structure for when the API is ready.
          </p>
        </div>

        {/* Equity curve — real Lightweight Charts line chart, falls back to SVG if empty */}
        <div>
          <div className="text-xs text-text-muted mb-2 flex items-center gap-1">
            <TrendingUp size={12} />
            Equity Curve
          </div>
          <EquityCurveChart data={equityCurve} />
        </div>

        {/* Return metrics */}
        <div>
          <div className="font-heading font-semibold text-sm text-text-muted mb-2">Return Metrics</div>
          <div className="grid grid-cols-2 gap-2">
            {MOCK_RETURN_METRICS.map((m) => (
              <MetricCard key={m.label} metric={m} />
            ))}
          </div>
        </div>

        {/* Risk metrics */}
        <div>
          <div className="font-heading font-semibold text-sm text-text-muted mb-2">Risk Metrics</div>
          <div className="grid grid-cols-2 gap-2">
            {MOCK_RISK_METRICS.map((m) => (
              <MetricCard key={m.label} metric={m} />
            ))}
          </div>
        </div>

        {/* Trade metrics */}
        <div>
          <div className="font-heading font-semibold text-sm text-text-muted mb-2">Trade Metrics</div>
          <div className="grid grid-cols-2 gap-2">
            {MOCK_TRADE_METRICS.map((m) => (
              <MetricCard key={m.label} metric={m} />
            ))}
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Trades Tab
// ---------------------------------------------------------------------------

function TradesTab({ hasRun }: { hasRun: boolean }) {
  const [sortField, setSortField] = useState<keyof MockTrade>("id");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  if (!hasRun) {
    return (
      <div className="flex flex-col items-center justify-center h-40 text-center px-4 gap-2 mt-6">
        <ArrowUpDown size={24} className="text-text-disabled opacity-40" />
        <p className="text-xs text-text-muted">
          Run a backtest to view the trade log.
        </p>
      </div>
    );
  }

  const sorted = [...MOCK_TRADES].sort((a, b) => {
    const av = a[sortField];
    const bv = b[sortField];
    if (typeof av === "number" && typeof bv === "number") {
      return sortDir === "asc" ? av - bv : bv - av;
    }
    return sortDir === "asc"
      ? String(av).localeCompare(String(bv))
      : String(bv).localeCompare(String(av));
  });

  const handleSort = (field: keyof MockTrade) => {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  };

  const SortIcon = ({ field }: { field: keyof MockTrade }) =>
    sortField === field ? (
      <ArrowUpDown size={10} className="text-primary ml-1 inline" />
    ) : (
      <ArrowUpDown size={10} className="text-text-disabled ml-1 inline opacity-40" />
    );

  return (
    <div className="p-4">
      {/* Summary badges */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <Badge className="bg-bullish-bg text-emerald-400 border-bullish-border text-xs">
          <CheckCircle2 size={10} className="mr-1" />
          {MOCK_TRADES.filter((t) => t.pnl > 0).length} Winners
        </Badge>
        <Badge className="bg-bearish-bg text-red-400 border-bearish-border text-xs">
          <TrendingDown size={10} className="mr-1" />
          {MOCK_TRADES.filter((t) => t.pnl < 0).length} Losers
        </Badge>
        <Badge className="bg-surface-card text-text-secondary border-border-default text-xs">
          <Clock size={10} className="mr-1" />
          {MOCK_TRADES.length} Total Trades
        </Badge>
      </div>

      <div className="rounded-md border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              {(
                [
                  ["#", "id"],
                  ["Symbol", "symbol"],
                  ["Side", "side"],
                  ["Entry Date", "entryDate"],
                  ["Exit Date", "exitDate"],
                  ["Entry", "entryPrice"],
                  ["Exit", "exitPrice"],
                  ["Qty", "qty"],
                  ["P&L", "pnl"],
                  ["P&L %", "pnlPct"],
                  ["Period", "holdingPeriod"],
                ] as [string, keyof MockTrade][]
              ).map(([label, field]) => (
                <TableHead
                  key={field}
                  className="text-xs text-text-muted cursor-pointer select-none h-8 px-2"
                  onClick={() => handleSort(field)}
                >
                  {label}
                  <SortIcon field={field} />
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((trade) => (
              <TableRow
                key={trade.id}
                className="border-border-default hover:bg-surface-card text-xs"
              >
                <TableCell className="px-2 py-1.5 text-text-muted font-mono">
                  {trade.id}
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono font-medium text-text-primary">
                  {trade.symbol}
                </TableCell>
                <TableCell className="px-2 py-1.5">
                  <Badge
                    className={[
                      "text-xs px-1.5 py-0",
                      trade.side === "BUY"
                        ? "bg-bullish-bg text-emerald-400 border-bullish-border"
                        : "bg-bearish-bg text-red-400 border-bearish-border",
                    ].join(" ")}
                  >
                    {trade.side}
                  </Badge>
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">
                  {trade.entryDate}
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">
                  {trade.exitDate}
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">
                  {trade.entryPrice.toLocaleString("en-IN")}
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">
                  {trade.exitPrice.toLocaleString("en-IN")}
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">
                  {trade.qty}
                </TableCell>
                <TableCell
                  className={[
                    "px-2 py-1.5 font-mono font-semibold",
                    trade.pnl >= 0 ? "text-emerald-400" : "text-red-400",
                  ].join(" ")}
                >
                  {trade.pnl >= 0 ? "+" : ""}
                  {trade.pnl.toLocaleString("en-IN")}
                </TableCell>
                <TableCell
                  className={[
                    "px-2 py-1.5 font-mono",
                    trade.pnlPct >= 0 ? "text-emerald-400" : "text-red-400",
                  ].join(" ")}
                >
                  {trade.pnlPct >= 0 ? "+" : ""}
                  {trade.pnlPct.toFixed(2)}%
                </TableCell>
                <TableCell className="px-2 py-1.5 text-text-muted">
                  {trade.holdingPeriod}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  onClose?: () => void;
}

export default function BacktestLabTool({ onClose }: Props) {
  const [hasRun, setHasRun] = useState(false);
  const [activeTab, setActiveTab] = useState("configure");
  // equityCurve is populated from API response when backend connects.
  // For now, after "Run Backtest" we show the mock curve so the chart renders.
  const [equityCurve, setEquityCurve] = useState<EquityPoint[]>([]);

  const handleRunRequest = () => {
    // TODO: POST /ft-api/v1/backtest/run with BacktestFormValues body.
    // Expected response shape:
    //   { equity_curve: EquityPoint[], trades: Trade[], metrics: BacktestMetrics }
    // where EquityPoint = { time: number; value: number } (Unix seconds, INR portfolio value),
    // Trade matches the MOCK_TRADES shape, and BacktestMetrics covers the stat cards in ResultsTab.
    // On success: setEquityCurve(res.equity_curve), populate trades + metrics state, setHasRun(true).
    // On error: show a toast and leave hasRun false so the results tab stays hidden.
    // The backtest-engine Python package exposes this via packages/backtest-engine (FastAPI router).
    setEquityCurve(MOCK_EQUITY_CURVE);
    setHasRun(true);
    setActiveTab("results");
  };

  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card shrink-0">
        <div className="flex items-center gap-2">
          <FlaskConical size={16} className="text-primary" />
          <span className="font-heading font-bold text-lg text-text-primary">
            Backtest Lab
          </span>
          {hasRun && (
            <Badge className="text-xs h-4 px-1.5 bg-neutral-bg text-primary border-neutral-border">
              Mock data
            </Badge>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-text-muted hover:text-text-primary transition-colors"
        >
          <X size={15} />
        </button>
      </div>

      {/* Tabs */}
      <Tabs
        value={activeTab}
        onValueChange={setActiveTab}
        className="flex flex-col flex-1 min-h-0"
      >
        <TabsList className="mx-4 mt-3 mb-0 h-8 bg-surface-card border border-border-default shrink-0 rounded-md w-auto self-start">
          <TabsTrigger
            value="configure"
            className="text-xs font-medium h-6 px-3 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary"
          >
            Configure
          </TabsTrigger>
          <TabsTrigger
            value="results"
            className="text-xs font-medium h-6 px-3 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary"
          >
            Results
          </TabsTrigger>
          <TabsTrigger
            value="trades"
            className="text-xs font-medium h-6 px-3 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary"
          >
            Trades
          </TabsTrigger>
        </TabsList>

        <TabsContent value="configure" className="flex-1 overflow-y-auto mt-0">
          <ConfigureTab onRunRequest={handleRunRequest} />
        </TabsContent>
        <TabsContent value="results" className="flex-1 overflow-y-auto mt-0">
          <ResultsTab hasRun={hasRun} equityCurve={equityCurve} />
        </TabsContent>
        <TabsContent value="trades" className="flex-1 overflow-y-auto mt-0">
          <TradesTab hasRun={hasRun} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

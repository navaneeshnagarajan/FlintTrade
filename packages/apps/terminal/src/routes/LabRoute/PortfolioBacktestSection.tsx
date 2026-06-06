import { useState } from "react";
import { Layers, Loader2 } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  runPortfolioBacktest,
  type PortfolioBacktestConfig,
  type PortfolioBacktestResult,
  type AllocationStrategy,
  type RebalanceFreq,
} from "@/services/ftApi";
import { MetricCard } from "./MetricCards";
import { fmtInr, fmtPct, fmtNum } from "./formatters";

const ALLOCATIONS: { value: AllocationStrategy; label: string }[] = [
  { value: "equal_weight", label: "Equal weight" },
  { value: "inverse_volatility", label: "Inverse volatility" },
  { value: "momentum", label: "Momentum" },
  { value: "market_cap", label: "Market cap" },
];

const REBALANCES: { value: RebalanceFreq; label: string }[] = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "yearly", label: "Yearly" },
];

/** Minimal inline SVG line for the portfolio equity curve (number[] series). */
function EquitySparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * 100},${100 - ((v - min) / range) * 100}`)
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className="h-24 w-full"
      role="img"
      aria-label="Portfolio equity curve"
    >
      <polyline
        points={points}
        fill="none"
        stroke={up ? "var(--color-profit)" : "var(--color-loss)"}
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/**
 * Multi-instrument portfolio backtest — equal-weight / inverse-vol / momentum /
 * market-cap allocation with periodic rebalancing, against the real
 * /backtest/portfolio engine (PortfolioBacktester). Distinct from the
 * single-instrument Backtest tab.
 */
export function PortfolioBacktestSection() {
  const [symbols, setSymbols] = useState("RELIANCE, TCS, INFY, HDFCBANK");
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [initialCapital, setInitialCapital] = useState(1_000_000);
  const [allocation, setAllocation] = useState<AllocationStrategy>("equal_weight");
  const [rebalance, setRebalance] = useState<RebalanceFreq>("monthly");

  const run = useMutation<PortfolioBacktestResult, Error, PortfolioBacktestConfig>({
    mutationFn: runPortfolioBacktest,
  });

  const symbolList = symbols
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  const canRun = symbolList.length >= 2 && Boolean(startDate) && Boolean(endDate);

  const onRun = () => {
    run.mutate({
      symbols: symbolList,
      start_date: startDate,
      end_date: endDate,
      initial_capital: initialCapital,
      allocation_strategy: allocation,
      rebalance_freq: rebalance,
    });
  };

  const result = run.data?.result;
  const comparison = run.data?.comparison;

  return (
    <div className="space-y-4">
      <GlassCard className="p-5 gap-3">
        <div className="flex items-center gap-2">
          <Layers size={16} className="text-accent" aria-hidden="true" />
          <h3 className="font-heading font-semibold text-sm text-text-primary">Portfolio Backtest</h3>
        </div>

        <label className="block text-xs text-text-secondary">
          Symbols (comma-separated, 2+)
          <Input
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            placeholder="RELIANCE, TCS, INFY"
            aria-label="Portfolio symbols"
            className="mt-1 font-mono"
          />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs text-text-secondary">
            Start date
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} aria-label="Start date" className="mt-1" />
          </label>
          <label className="block text-xs text-text-secondary">
            End date
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} aria-label="End date" className="mt-1" />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs text-text-secondary">
            Allocation
            <Select value={allocation} onValueChange={(v) => setAllocation(v as AllocationStrategy)}>
              <SelectTrigger aria-label="Allocation strategy" className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ALLOCATIONS.map((a) => (
                  <SelectItem key={a.value} value={a.value}>{a.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="block text-xs text-text-secondary">
            Rebalance
            <Select value={rebalance} onValueChange={(v) => setRebalance(v as RebalanceFreq)}>
              <SelectTrigger aria-label="Rebalance frequency" className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {REBALANCES.map((rb) => (
                  <SelectItem key={rb.value} value={rb.value}>{rb.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </div>

        <label className="block text-xs text-text-secondary">
          Initial capital (₹)
          <Input
            type="number"
            value={initialCapital}
            onChange={(e) => setInitialCapital(Number(e.target.value) || 0)}
            aria-label="Initial capital"
            className="mt-1 font-mono"
          />
        </label>

        <Button onClick={onRun} disabled={!canRun || run.isPending} className="w-full">
          {run.isPending ? <Loader2 size={14} className="mr-1.5 animate-spin" aria-hidden="true" /> : null}
          {run.isPending ? "Running…" : "Run portfolio backtest"}
        </Button>
        {!canRun && (
          <p className="text-xs text-text-muted">Enter at least two symbols and a date range.</p>
        )}
        {run.isError && (
          <p className="text-xs text-loss" role="alert">Backtest failed — {run.error.message}</p>
        )}
      </GlassCard>

      {result && (
        <>
          {result.equity_curve.length > 1 && (
            <GlassCard className="p-5 gap-3">
              <h4 className="font-heading font-semibold text-sm text-text-primary">Portfolio Equity</h4>
              <EquitySparkline values={result.equity_curve} />
            </GlassCard>
          )}

          <GlassCard className="p-5 gap-3">
            <h4 className="font-heading font-semibold text-sm text-text-primary">Performance</h4>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <MetricCard label="Total Return" value={fmtPct(result.total_return)} positive={result.total_return >= 0} />
              <MetricCard label="Annual Return" value={fmtPct(result.annual_return)} positive={result.annual_return >= 0} />
              <MetricCard label="Sharpe" value={fmtNum(result.sharpe_ratio)} positive={result.sharpe_ratio > 1} />
              <MetricCard label="Sortino" value={fmtNum(result.sortino_ratio)} positive={result.sortino_ratio > 1} />
              <MetricCard label="Max Drawdown" value={fmtPct(Math.abs(result.max_drawdown))} positive={false} />
              <MetricCard label="Calmar" value={fmtNum(result.calmar_ratio)} positive={result.calmar_ratio > 0} />
              <MetricCard label="Volatility" value={fmtPct(result.volatility)} positive={null} />
              <MetricCard label="Final Equity" value={fmtInr(result.final_equity)} positive={null} />
            </div>
            <p className="text-xxs text-text-muted">
              {result.rebalance_log.length} rebalance{result.rebalance_log.length === 1 ? "" : "s"} ·
              VaR(95%) {fmtPct(Math.abs(result.var_95))}
            </p>
          </GlassCard>

          {comparison && (
            <GlassCard className="p-5 gap-3">
              <h4 className="font-heading font-semibold text-sm text-text-primary">Vs Benchmark</h4>
              <div className="grid grid-cols-3 gap-3">
                <MetricCard label="Alpha" value={fmtPct(comparison.alpha)} positive={comparison.alpha >= 0} />
                <MetricCard label="Beta" value={fmtNum(comparison.beta)} positive={null} />
                <MetricCard label="Info Ratio" value={fmtNum(comparison.information_ratio)} positive={comparison.information_ratio >= 0} />
              </div>
            </GlassCard>
          )}
        </>
      )}
    </div>
  );
}

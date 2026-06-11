import { useMutation } from "@tanstack/react-query";
import { GitCompareArrows, Loader2, Trophy } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  compareBacktests,
  type BacktestResult,
  type StrategyComparison,
} from "@/services/ftApi";
import { BacktestResultDisplay } from "./BacktestResultDisplay";
import { fmtNum, fmtPct } from "./formatters";

export interface ResultsSectionProps {
  lastResult: BacktestResult | null;
  /** Every completed run this session, keyed by strategy name. */
  sessionRuns: Record<string, BacktestResult>;
}

/** Comparison metrics shown per strategy (key in data.metrics → label). */
const COMPARE_COLUMNS: Array<{ key: string; label: string; pct?: boolean }> = [
  { key: "sharpe", label: "Sharpe" },
  { key: "cagr", label: "CAGR", pct: true },
  { key: "max_drawdown", label: "Max DD", pct: true },
  { key: "win_rate", label: "Win Rate", pct: true },
  { key: "profit_factor", label: "PF" },
];

function CompareRunsCard({ sessionRuns }: { sessionRuns: Record<string, BacktestResult> }) {
  const runNames = Object.keys(sessionRuns);

  const compareMutation = useMutation<StrategyComparison, Error, void>({
    mutationFn: () => compareBacktests(sessionRuns),
  });
  const comparison = compareMutation.data;

  return (
    <GlassCard className="p-5 gap-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <GitCompareArrows size={16} className="text-accent" aria-hidden="true" />
          <h3 className="font-heading font-semibold text-base text-text-primary">
            Compare runs
          </h3>
          <span className="text-xs text-text-muted">
            {runNames.length} strategies this session
          </span>
        </div>
        <Button
          size="sm"
          onClick={() => compareMutation.mutate()}
          disabled={runNames.length < 2 || compareMutation.isPending}
          className="h-8 px-4 text-xs"
        >
          {compareMutation.isPending ? (
            <Loader2 size={12} className="animate-spin mr-1.5" aria-hidden="true" />
          ) : null}
          Compare
        </Button>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {runNames.map((name) => (
          <Badge key={name} variant="outline" className="text-xs font-mono">
            {name}
          </Badge>
        ))}
      </div>

      {runNames.length < 2 && (
        <p className="text-xs text-text-muted">
          Run a second strategy from the Backtest tab to enable comparison.
        </p>
      )}

      {compareMutation.isError && (
        <p className="text-xs text-loss">
          Comparison failed: {compareMutation.error.message}
        </p>
      )}

      {comparison && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 rounded border border-profit/30 bg-profit/5 px-3 py-2">
            <Trophy size={14} className="text-profit shrink-0" aria-hidden="true" />
            <span className="text-sm text-text-primary">
              Best overall (weighted composite):{" "}
              <span className="font-semibold font-mono">{comparison.best_overall}</span>
            </span>
          </div>

          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="text-xs text-text-muted font-medium">Strategy</TableHead>
                  {COMPARE_COLUMNS.map((c) => (
                    <TableHead key={c.key} className="text-xs text-text-muted font-medium text-right">
                      {c.label}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {comparison.strategies.map((name) => {
                  const m = comparison.metrics[name] ?? {};
                  const isBest = name === comparison.best_overall;
                  return (
                    <TableRow
                      key={name}
                      className={`border-border-subtle ${isBest ? "bg-profit/5" : "hover:bg-surface-base"}`}
                    >
                      <TableCell className="text-xs font-mono py-1.5 text-text-primary">
                        {name}
                        {isBest && <span className="text-profit ml-1.5">★</span>}
                      </TableCell>
                      {COMPARE_COLUMNS.map((c) => {
                        const v = m[c.key];
                        return (
                          <TableCell key={c.key} className="text-xs font-mono py-1.5 text-right tabular-nums text-text-secondary">
                            {typeof v === "number" ? (c.pct ? fmtPct(v / 100) : fmtNum(v)) : "—"}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>

          {Object.keys(comparison.optimal_blend).length > 0 && (
            <div>
              <p className="text-xxs uppercase tracking-wide text-text-muted mb-1">
                Suggested blend (inverse-variance, correlation-penalised)
              </p>
              <div className="flex items-center gap-1.5 flex-wrap">
                {Object.entries(comparison.optimal_blend)
                  .sort((a, b) => b[1] - a[1])
                  .map(([name, weight]) => (
                    <Badge key={name} variant="outline" className="text-xs font-mono">
                      {name} {(weight * 100).toFixed(0)}%
                    </Badge>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}
    </GlassCard>
  );
}

export function ResultsSection({ lastResult, sessionRuns }: ResultsSectionProps) {
  const hasRuns = Object.keys(sessionRuns).length > 0;

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
        {hasRuns && <CompareRunsCard sessionRuns={sessionRuns} />}
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
          analysis, and detailed trade logs.
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
          Run two or more strategies to compare them side by side.
        </p>
      </GlassCard>
    </div>
  );
}

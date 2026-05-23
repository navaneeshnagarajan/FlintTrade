import { Badge } from "@/components/ui/badge";
import { GlassCard } from "@/components/ui/GlassCard";
import { type BacktestResult } from "@/services/ftApi";
import { BacktestResultDisplay } from "./BacktestResultDisplay";

export interface ResultsSectionProps {
  lastResult: BacktestResult | null;
}

export function ResultsSection({ lastResult }: ResultsSectionProps) {
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
          Multi-run comparison and CSV export will be available in a future update.
        </p>
      </GlassCard>
    </div>
  );
}

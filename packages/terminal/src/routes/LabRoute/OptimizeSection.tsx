import { Badge } from "@/components/ui/badge";
import { GlassCard } from "@/components/ui/GlassCard";

export function OptimizeSection() {
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
          that generalise across market regimes.
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
              <li>Maximise Sharpe Ratio</li>
              <li>Maximise Sortino Ratio</li>
              <li>Minimise Max Drawdown</li>
              <li>Maximise Profit Factor</li>
            </ul>
          </div>
        </div>
      </GlassCard>
      <GlassCard className="p-4 gap-2">
        <Badge className="bg-atm-bg text-warning text-xs">
          Coming soon
        </Badge>
        <p className="text-sm text-text-muted">
          Parameter optimisation UI will be available in the next release. The
          Python backtest-engine package already supports walk-forward
          optimisation via{" "}
          <code className="text-xxs bg-surface-base px-1 py-0.5 rounded font-mono">
            Optimizer.optimize()
          </code>
          .
        </p>
      </GlassCard>
    </div>
  );
}

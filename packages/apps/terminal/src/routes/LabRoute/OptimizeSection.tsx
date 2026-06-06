import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { GlassCard } from "@/components/ui/GlassCard";
import { getLatestOptimiserReport } from "@/services/ftApi.ai";

export function OptimizeSection() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["optimiser", "report", "latest"],
    queryFn: getLatestOptimiserReport,
    staleTime: 60_000,
  });
  const report = data?.report ?? null;

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

      {/* Overnight optimisation report — the nightly "reports + improvement
          suggestions" the AI optimiser produces (02:00 IST), surfaced here. */}
      <GlassCard className="p-4 gap-3" data-testid="overnight-report-card">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Overnight optimisation report
          </h3>
          {report && (
            <Badge className="bg-surface-base text-text-muted text-xxs">
              {new Date(report.timestamp).toLocaleString("en-IN")}
            </Badge>
          )}
        </div>

        {isLoading && (
          <p className="text-xs text-text-muted">Loading the latest report…</p>
        )}
        {isError && (
          <p className="text-xs text-text-muted">
            The optimisation report is unavailable right now.
          </p>
        )}
        {!isLoading && !isError && !report && (
          <p className="text-sm text-text-muted" data-testid="overnight-report-empty">
            No optimisation reports yet. The optimiser runs overnight (02:00 IST)
            and its parameter-improvement suggestions appear here.
          </p>
        )}
        {report && (
          <div className="space-y-2" data-testid="overnight-report-body">
            <p className="text-xs text-text-secondary">
              {report.strategies_optimised} of {report.strategies_seen} strategies
              refined.
            </p>
            <ul className="space-y-2">
              {report.suggestions.map((s, i) => (
                <li
                  key={`${s.strategy_name}-${i}`}
                  className="bg-surface-base border border-border-default rounded-lg p-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-text-primary">
                      {s.strategy_name}
                    </span>
                    <span className="text-xxs text-text-muted">
                      confidence {(s.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  {s.analysis && (
                    <p className="text-xs text-text-secondary mt-1">{s.analysis}</p>
                  )}
                  {s.reasoning && (
                    <p className="text-xxs text-text-muted mt-1">{s.reasoning}</p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </GlassCard>
    </div>
  );
}

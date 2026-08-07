/**
 * PortfolioOptimiserWidget — mean-variance portfolio weight optimisation.
 *
 * Wired to /ft-api/v1/portfolio/optimise (numpy/scipy Markowitz family). When a
 * broker is connected it fetches ~1y of daily history for a large-cap basket,
 * derives length-aligned daily returns, and optimises; otherwise it shows a
 * badged sample so the widget is usable in explore mode. Read-only analysis —
 * it suggests target weights, it does not place any order.
 */

import { useState, useMemo, memo } from "react";
import { PieChart, Loader2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { FlintScatterChart, type FlintScatterPoint } from "@flinttrade/design-system";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useDataScope } from "@/hooks/useDataScope";
import { useModeStore } from "@/stores/modeStore";
import { getHistory } from "@/services/api";
import {
  getPortfolioFrontier,
  optimisePortfolio,
  type OptimisationMethod,
  type PortfolioResult,
} from "@/services/ftApi";
import { SAMPLE_BASKET, SAMPLE_FRONTIER, SAMPLE_RESULT } from "./sampleData";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASKET = [...SAMPLE_BASKET];
const EXCHANGE = "NSE";
/** Minimum aligned return points before optimisation is meaningful. */
const MIN_POINTS = 60;

const METHODS: { value: OptimisationMethod; label: string }[] = [
  { value: "markowitz", label: "Markowitz" },
  { value: "max_sharpe", label: "Max Sharpe" },
  { value: "min_variance", label: "Min Variance" },
  { value: "risk_parity", label: "Risk Parity" },
  { value: "equal_weight", label: "Equal Weight" },
];

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

/** Fetch the basket's daily history and build length-aligned return series. */
async function fetchBasketReturns(): Promise<Record<string, number[]>> {
  const today = new Date();
  const end = today.toISOString().slice(0, 10);
  const start = new Date(today.getTime() - 400 * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);

  const fetched = await Promise.all(
    BASKET.map((sym) =>
      getHistory(sym, EXCHANGE, "D", start, end)
        .then((bars) => ({
          sym,
          closes: (Array.isArray(bars) ? bars : [])
            .map((b) => Number(b.close))
            .filter((c) => Number.isFinite(c) && c > 0),
        }))
        .catch(() => ({ sym, closes: [] as number[] })),
    ),
  );

  const valid = fetched.filter((r) => r.closes.length > MIN_POINTS);
  if (valid.length < 2) {
    throw new Error("Not enough basket history to optimise");
  }
  // Align every series to the most-recent common length so the backend's
  // DataFrame columns line up (unequal lengths would misalign the covariance).
  const minLen = Math.min(...valid.map((r) => r.closes.length));
  const returns: Record<string, number[]> = {};
  for (const { sym, closes } of valid) {
    const window = closes.slice(closes.length - minLen);
    returns[sym] = window.slice(1).map((c, i) => (c - window[i]) / window[i]);
  }
  return returns;
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function PortfolioOptimiserWidget() {
  const isConnected = useBrokerConnected();
  const mode = useModeStore((state) => state.mode);
  const dataScope = useDataScope();
  const [method, setMethod] = useState<OptimisationMethod>("markowitz");
  const readsEnabled = mode === "practice" || (mode === "live" && isConnected);

  // Basket returns are fetched ONCE and shared by the optimise + frontier
  // queries (the frontier is method-independent — the chosen portfolio moves,
  // the curve does not).
  const returnsQuery = useQuery({
    queryKey: ["portfolioBasketReturns", dataScope],
    queryFn: fetchBasketReturns,
    enabled: readsEnabled,
  });
  const returns = returnsQuery.data;

  const query = useQuery({
    queryKey: ["portfolioOptimise", dataScope, method],
    queryFn: () => optimisePortfolio(returns as Record<string, number[]>, { method }),
    enabled: readsEnabled && !!returns,
  });
  const frontierQuery = useQuery({
    queryKey: ["portfolioFrontier", dataScope],
    queryFn: () => getPortfolioFrontier(returns as Record<string, number[]>, 25),
    enabled: readsEnabled && !!returns,
  });

  const hasApiResult = readsEnabled && query.isSuccess && !!query.data;
  const hasApiFrontier = readsEnabled
    && frontierQuery.isSuccess
    && !!frontierQuery.data?.length;
  const hasApiData = hasApiResult && hasApiFrontier;
  const isLive = mode === "live" && hasApiData;
  const isPractice = mode === "practice" && hasApiData;
  const result: PortfolioResult = hasApiData ? query.data : SAMPLE_RESULT;
  const frontier: PortfolioResult[] = hasApiData ? frontierQuery.data : SAMPLE_FRONTIER;
  const apiUnavailable = readsEnabled && !hasApiData && (
    returnsQuery.isError
    || query.isError
    || frontierQuery.isError
    || (frontierQuery.isSuccess && frontierQuery.data.length === 0)
  );

  const weightRows = Object.entries(result.weights).sort((a, b) => b[1] - a[1]);
  const maxWeight = Math.max(...weightRows.map(([, w]) => w), 0.0001);

  const frontierChart = useMemo(() => {
    const points: FlintScatterPoint[] = frontier.map((p, i) => ({
      id: `frontier-${i}`,
      label: `vol ${(p.expected_volatility * 100).toFixed(1)}% → ret ${(p.expected_return * 100).toFixed(1)}%`,
      x: p.expected_volatility * 100,
      y: p.expected_return * 100,
      radius: 2.5,
      color: "rgba(99,102,241,0.55)",
    }));
    points.push({
      id: "selected",
      label: `Selected: vol ${(result.expected_volatility * 100).toFixed(1)}% → ret ${(result.expected_return * 100).toFixed(1)}%`,
      x: result.expected_volatility * 100,
      y: result.expected_return * 100,
      radius: 5,
      color: "#22c55e",
      strokeColor: "#16a34a",
    });
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const yMin = Math.min(...ys);
    const yMax = Math.max(...ys);
    const xPad = Math.max((xMax - xMin) * 0.1, 0.5);
    const yPad = Math.max((yMax - yMin) * 0.1, 0.5);
    return {
      points,
      xDomain: [xMin - xPad, xMax + xPad] as const,
      yDomain: [yMin - yPad, yMax + yPad] as const,
    };
  }, [frontier, result]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <PieChart size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Portfolio Optimiser</span>
        {isLive ? (
          <span
            className="inline-flex items-center rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400"
            role="status"
            aria-label="Live: weights optimised from real basket history"
            title="Live — mean-variance weights from ~1y of the basket's real daily history."
          >
            Live
          </span>
        ) : isPractice ? (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Practice: weights optimised from sandbox-scoped basket history"
            title="Practice — read-only weights from the current Practice data scope."
          >
            Practice
          </span>
        ) : (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing sample data; connect a broker for a live optimisation"
            title="Sample optimisation so the widget is usable in explore mode — connect a broker to optimise the basket from real history."
          >
            Sample data
          </span>
        )}
        {(returnsQuery.isFetching || query.isFetching || frontierQuery.isFetching) && (
          <Loader2 size={12} className="animate-spin text-text-muted" aria-label="Optimising" />
        )}
        <div className="flex-1" />
        <Select value={method} onValueChange={(v) => setMethod(v as OptimisationMethod)}>
          <SelectTrigger className="h-7 w-32 text-xs bg-surface-hover border-border-default text-text-primary" aria-label="Optimisation method">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {METHODS.map((m) => (
              <SelectItem key={m.value} value={m.value} className="text-xs">{m.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Metrics row */}
      <div className="flex-none grid grid-cols-4 gap-px bg-border-subtle border-b border-border-default text-center">
        {[
          { label: "Exp. Return", value: pct(result.expected_return), cls: "text-profit" },
          { label: "Volatility", value: pct(result.expected_volatility), cls: "text-warning" },
          { label: "Sharpe", value: result.sharpe_ratio.toFixed(2), cls: "text-text-primary" },
          { label: "Diversif.", value: result.diversification_ratio.toFixed(2), cls: "text-text-primary" },
        ].map((m) => (
          <div key={m.label} className="bg-surface-elevated py-1.5">
            <div className="text-xxs text-text-muted uppercase tracking-wide">{m.label}</div>
            <div className={`text-sm font-mono font-semibold tabular-nums ${m.cls}`}>{m.value}</div>
          </div>
        ))}
      </div>

      {/* Efficient frontier */}
      <div className="flex-none px-3 pt-2">
        <div className="text-xxs uppercase tracking-wide text-text-muted mb-1">
          Efficient frontier
          <span className="normal-case tracking-normal"> · green dot = selected portfolio</span>
        </div>
        <FlintScatterChart
          ariaLabel="Efficient frontier: expected volatility versus expected return"
          points={frontierChart.points}
          xDomain={frontierChart.xDomain}
          yDomain={frontierChart.yDomain}
          xFormatter={(v) => `${v.toFixed(0)}%`}
          yFormatter={(v) => `${v.toFixed(0)}%`}
          xAxisLabel="Volatility"
          yAxisLabel="Return"
          width={520}
          height={170}
        />
      </div>

      {/* Weights */}
      <div className="flex-1 min-h-0 overflow-auto px-3 py-2 space-y-1.5">
        <div className="text-xxs uppercase tracking-wide text-text-muted mb-1">Target weights</div>
        {weightRows.map(([ticker, weight]) => (
          <div key={ticker} className="flex items-center gap-2">
            <span className="w-20 shrink-0 text-xs font-mono text-text-primary truncate">{ticker}</span>
            <div className="flex-1 h-3.5 bg-surface-hover rounded-sm overflow-hidden">
              <div
                className="h-full bg-accent/60 rounded-sm"
                style={{ width: `${(weight / maxWeight) * 100}%` }}
                aria-hidden="true"
              />
            </div>
            <span className="w-12 shrink-0 text-right text-xs font-mono tabular-nums text-text-secondary">
              {pct(weight)}
            </span>
          </div>
        ))}
        {apiUnavailable && (
          <p className="text-xxs text-text-muted pt-1">
            {mode === "practice" ? "Practice" : "Live"} optimisation unavailable — showing a sample allocation.
          </p>
        )}
      </div>

      {/* Footer note */}
      <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1 text-xxs text-text-muted">
        Mean-variance over {weightRows.length} assets · read-only suggestion, not an order.
      </div>
    </div>
  );
}

export default memo(PortfolioOptimiserWidget);

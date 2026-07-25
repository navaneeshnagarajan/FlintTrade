/**
 * RiskReturnTab.tsx
 *
 * Risk-Return scatter plot for the Invest route (advanced level).
 *
 * Layout:
 *   1. Stats bar — avg return, avg volatility, best Sharpe
 *   2. SVG scatter — X = annualised volatility, Y = annualised return
 *      Bubble radius ∝ Sharpe ratio, colour-coded by category
 *   3. Legend
 *
 * Data flow:
 *   GET /ft-api/api/v1/analytics/risk-return → TanStack Query (10 min stale)
 *
 * Design:
 *   - Pure SVG, no Plotly dependency
 *   - Axis ticks derived from data extent with a small padding
 *   - Tooltip via SVG <title> (screen reader + hover)
 *
 * Accessibility:
 *   - SVG has role="img" + aria-label
 *   - Each bubble has a <title> child (tooltip + screen reader)
 *   - Colour is supplemented by shape or symbol label on hover
 *   - Stats cards use dl/dt/dd semantics
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, RefreshCw } from "lucide-react";
import { FlintScatterChart } from "@flinttrade/design-system";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";
import { getRiskReturn, type RiskReturnPoint } from "@/services/ftApi";
import { formatPercent } from "../formatters";

// ─── Demo data ─────────────────────────────────────────────────────────────

const DEMO_POINTS: RiskReturnPoint[] = [
  { symbol: "NIFTYBEES", name: "Nifty 50 ETF", category: "Equity", annualised_return: 14.2, annualised_volatility: 15.8, sharpe_ratio: 0.89 },
  { symbol: "BANKBEES", name: "Bank ETF", category: "Equity", annualised_return: 8.4, annualised_volatility: 22.4, sharpe_ratio: 0.37 },
  { symbol: "ITBEES", name: "IT ETF", category: "Equity", annualised_return: 22.1, annualised_volatility: 24.6, sharpe_ratio: 0.90 },
  { symbol: "PHARMABEES", name: "Pharma ETF", category: "Equity", annualised_return: 12.3, annualised_volatility: 18.2, sharpe_ratio: 0.67 },
  { symbol: "JUNIORBEES", name: "Nifty Next50 ETF", category: "Equity", annualised_return: 18.9, annualised_volatility: 20.4, sharpe_ratio: 0.93 },
  { symbol: "CPSEETF", name: "CPSE ETF", category: "Equity", annualised_return: 28.4, annualised_volatility: 26.8, sharpe_ratio: 1.06 },
  { symbol: "NIFTYREALTY", name: "Realty Index", category: "Equity", annualised_return: 44.2, annualised_volatility: 38.6, sharpe_ratio: 1.14 },
  { symbol: "GOLDBEES", name: "Gold ETF", category: "Gold", annualised_return: 16.4, annualised_volatility: 12.2, sharpe_ratio: 1.34 },
  { symbol: "GOLDIETF", name: "HDFC Gold ETF", category: "Gold", annualised_return: 16.1, annualised_volatility: 12.0, sharpe_ratio: 1.34 },
  { symbol: "SILVERBEES", name: "Silver ETF", category: "Silver", annualised_return: 8.2, annualised_volatility: 18.8, sharpe_ratio: 0.44 },
  { symbol: "LIQUIDBEES", name: "Liquid ETF", category: "Debt", annualised_return: 7.1, annualised_volatility: 0.4, sharpe_ratio: 17.75 },
  { symbol: "MAFANG", name: "FANG+ ETF", category: "International", annualised_return: 18.6, annualised_volatility: 28.4, sharpe_ratio: 0.65 },
];

// ─── Category colours ─────────────────────────────────────────────────────────

const CATEGORY_COLOURS: Record<string, { fill: string; stroke: string; label: string }> = {
  Equity: { fill: "#3b82f6", stroke: "#2563eb", label: "Equity" },
  Gold: { fill: "#f59e0b", stroke: "#d97706", label: "Gold" },
  Silver: { fill: "#94a3b8", stroke: "#64748b", label: "Silver" },
  Debt: { fill: "#10b981", stroke: "#059669", label: "Debt" },
  International: { fill: "#a855f7", stroke: "#9333ea", label: "International" },
};

function colourFor(category: string) {
  return CATEGORY_COLOURS[category] ?? { fill: "#6b7280", stroke: "#4b5563", label: category };
}

// ─── Stats card ───────────────────────────────────────────────────────────────

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <GlassCard className="p-4">
      <dl>
        <dt className="text-xxs text-text-muted uppercase tracking-wider">{label}</dt>
        <dd className="font-mono text-lg font-bold text-text-primary tabular-nums mt-1">{value}</dd>
        {sub && <dd className="text-xs text-text-muted">{sub}</dd>}
      </dl>
    </GlassCard>
  );
}

// ─── Scatter plot ─────────────────────────────────────────────────────────────

const SVG_W = 560;
const SVG_H = 360;

function ScatterPlot({ points }: { points: RiskReturnPoint[] }) {
  const [hoveredSymbol, setHoveredSymbol] = useState<string | null>(null);

  const { xMin, xMax, yMin, yMax, maxSharpe } = useMemo(() => {
    const xs = points.map((p) => p.annualised_volatility);
    const ys = points.map((p) => p.annualised_return);
    const sharpes = points.map((p) => Math.abs(p.sharpe_ratio));
    return {
      xMin: Math.max(0, Math.min(...xs) - 2),
      xMax: Math.max(...xs) + 4,
      yMin: Math.min(...ys) - 3,
      yMax: Math.max(...ys) + 5,
      maxSharpe: Math.max(...sharpes),
    };
  }, [points]);

  function toR(sharpe: number) {
    const norm = Math.abs(sharpe) / Math.max(maxSharpe, 1);
    return 5 + norm * 14;
  }

  // Axis ticks
  const xTicks = useMemo(() => {
    const step = (xMax - xMin) / 5;
    return Array.from({ length: 6 }, (_, i) => Math.round(xMin + i * step));
  }, [xMin, xMax]);

  const yTicks = useMemo(() => {
    const step = (yMax - yMin) / 5;
    return Array.from({ length: 6 }, (_, i) => Math.round(yMin + i * step));
  }, [yMin, yMax]);

  const hoveredPoint = hoveredSymbol ? points.find((point) => point.symbol === hoveredSymbol) ?? null : null;

  return (
    <div className="relative">
      <FlintScatterChart
        ariaLabel="Risk-Return scatter plot: X axis = annualised volatility, Y axis = annualised return. Bubble size proportional to Sharpe ratio."
        points={points.map((point) => {
          const col = colourFor(point.category);
          return {
            id: point.symbol,
            label: `${point.symbol} — ${point.name}. Return: ${formatPercent(point.annualised_return)}. Volatility: ${formatPercent(point.annualised_volatility)}. Sharpe: ${point.sharpe_ratio.toFixed(2)}.`,
            x: point.annualised_volatility,
            y: point.annualised_return,
            radius: toR(point.sharpe_ratio),
            color: col.fill,
            strokeColor: col.stroke,
          };
        })}
        xDomain={[xMin, xMax]}
        yDomain={[yMin, yMax]}
        xTicks={xTicks}
        yTicks={yTicks}
        xFormatter={(value) => `${value}%`}
        yFormatter={(value) => `${value}%`}
        xAxisLabel="Annualised Volatility"
        yAxisLabel="Annualised Return"
        width={SVG_W}
        height={SVG_H}
        activePointId={hoveredSymbol}
        onPointHover={(point) => setHoveredSymbol(point?.id ?? null)}
      />

      {/* Tooltip overlay */}
      {hoveredPoint && (
        <div className="absolute top-2 right-2 bg-surface-card border border-border-default rounded-lg p-3 text-xs shadow-lg pointer-events-none">
          <div className="font-mono font-bold text-text-primary">{hoveredPoint.symbol}</div>
          <div className="text-text-muted leading-tight">{hoveredPoint.name}</div>
          <div className="mt-2 space-y-0.5">
            <div className="flex justify-between gap-4">
              <span className="text-text-muted">Return</span>
              <span className={cn("font-mono font-semibold", hoveredPoint.annualised_return >= 0 ? "text-profit" : "text-loss")}>
                {formatPercent(hoveredPoint.annualised_return)}
              </span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-text-muted">Volatility</span>
              <span className="font-mono text-text-primary">{formatPercent(hoveredPoint.annualised_volatility)}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-text-muted">Sharpe</span>
              <span className="font-mono text-text-primary">{hoveredPoint.sharpe_ratio.toFixed(2)}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function RiskReturnTab() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["risk-return"],
    queryFn: getRiskReturn,
    staleTime: 10 * 60_000,
    retry: 1,
  });

  const isDemo = isError || (!isLoading && (!data || data.is_sample_data !== false));
  const points = data?.points ?? DEMO_POINTS;

  // Category legend — unique categories
  const categories = useMemo(
    () => [...new Set(points.map((p) => p.category))],
    [points],
  );

  const avgReturn = data?.avg_return ?? (points.reduce((s, p) => s + p.annualised_return, 0) / points.length);
  const avgVol = data?.avg_volatility ?? (points.reduce((s, p) => s + p.annualised_volatility, 0) / points.length);
  const bestSharpeSymbol = data?.best_sharpe_symbol ?? points.reduce((b, p) => (p.sharpe_ratio > b.sharpe_ratio ? p : b), points[0]);
  const bestSharpe = data?.best_sharpe ?? (typeof bestSharpeSymbol === "object" ? bestSharpeSymbol.sharpe_ratio : 0);
  const bestSymbol = typeof bestSharpeSymbol === "string" ? bestSharpeSymbol : (data?.best_sharpe_symbol ?? (points.reduce((b, p) => (p.sharpe_ratio > b.sharpe_ratio ? p : b), points[0])).symbol);

  if (isLoading) {
    return (
      <div
        className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted"
        role="status"
        aria-live="polite"
      >
        <RefreshCw className="size-5 animate-spin" aria-hidden="true" />
        <span className="text-sm">Computing risk-return analytics...</span>
      </div>
    );
  }

  if (isError && !data) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-text-muted">
        <AlertCircle className="size-6" aria-hidden="true" />
        <p className="text-sm">Could not load risk-return data.</p>
        <Button variant="ghost" size="sm" onClick={() => void refetch()} aria-label="Retry loading risk-return data">
          <RefreshCw className="size-3 mr-1.5" aria-hidden="true" /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {isDemo && <DemoBanner />}

      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="font-heading font-semibold text-sm text-text-primary">Risk-Return Analysis</h3>
          <p className="text-xs text-text-muted mt-0.5">
            Annualised return vs volatility — bubble size proportional to Sharpe ratio
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void refetch()}
          className="text-xs text-text-muted h-6 px-2 gap-1 shrink-0"
          aria-label="Refresh risk-return data"
        >
          <RefreshCw className="size-3" aria-hidden="true" />
          Refresh
        </Button>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard
          label="Avg Return"
          value={formatPercent(avgReturn)}
          sub="annualised"
        />
        <StatCard
          label="Avg Volatility"
          value={formatPercent(avgVol)}
          sub="annualised"
        />
        <StatCard
          label="Best Sharpe"
          value={bestSharpe.toFixed(2)}
          sub={bestSymbol}
        />
      </div>

      {/* Scatter plot */}
      <GlassCard className="p-4">
        <ScatterPlot points={points} />

        {/* Legend */}
        <div className="flex flex-wrap gap-3 mt-3 pt-3 border-t border-border-default">
          {categories.map((cat) => {
            const col = colourFor(cat);
            return (
              <div key={cat} className="flex items-center gap-1.5">
                <span
                  className="size-3 rounded-full"
                  style={{ backgroundColor: col.fill }}
                  aria-hidden="true"
                />
                <span className="text-xs text-text-secondary">{cat}</span>
              </div>
            );
          })}
          <div className="ml-auto flex items-center gap-1.5">
            <span className="text-xxs text-text-muted">Bubble size = Sharpe ratio</span>
          </div>
        </div>
      </GlassCard>

      {/* Note on Liquid ETF */}
      {points.some((p) => p.symbol === "LIQUIDBEES") && (
        <div className="flex items-start gap-2 text-xs text-text-muted">
          <Badge variant="outline" className="text-xs h-5 border-border-default shrink-0">Note</Badge>
          <span>
            Liquid ETF (LIQUIDBEES) has near-zero volatility and very high Sharpe — it is shown at the far left of the chart.
            Its bubble may appear off-scale if Sharpe &gt; 10.
          </span>
        </div>
      )}

      <p className="text-xs text-text-muted">
        Returns are trailing 1-year annualised. Volatility = annualised std dev of daily returns.
        Sharpe = excess return / volatility. Risk-free rate assumed 6.5% p.a.
        {isDemo ? " Sample data shown — connect broker for live data." : ""}
      </p>
    </div>
  );
}

export default RiskReturnTab;

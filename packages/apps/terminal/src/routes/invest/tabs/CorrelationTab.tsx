/**
 * CorrelationTab.tsx
 *
 * Correlation matrix heatmap + market regime indicator for the Invest route (advanced).
 *
 * Layout:
 *   1. Regime banner — Risk-On / Risk-Off / Rotation with VIX + DXY badges
 *   2. HTML table with colour-coded correlation cells (−1 → +1 spectrum)
 *   3. Methodology note
 *
 * Data flow:
 *   GET /ft-api/api/v1/analytics/correlation → TanStack Query (15 min stale)
 *
 * Design:
 *   - Pure HTML table + inline styles for cell colour — no Plotly
 *   - 5-step diverging palette: deep red → white → deep blue
 *   - Self-correlation diagonal is neutral (1.00, grey)
 *
 * Accessibility:
 *   - Table has aria-label; diagonal cells are aria-hidden
 *   - Regime badge uses role="status"
 *   - Colour is supplemented by numeric value in each cell
 *   - Loading state uses role="status" / aria-live
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, RefreshCw, TrendingUp, TrendingDown, Repeat2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";
import { getCorrelationMatrix, type MarketRegime } from "@/services/ftApi";

// ─── Demo data ─────────────────────────────────────────────────────────────

const DEMO_SYMBOLS = ["NIFTY50", "BANKNIFTY", "IT", "GOLD", "USD/INR", "NIFTY500"];

const DEMO_MATRIX: number[][] = [
  [1.00,  0.84,  0.62, -0.18, -0.32,  0.96],
  [0.84,  1.00,  0.48, -0.22, -0.38,  0.82],
  [0.62,  0.48,  1.00, -0.08, -0.44,  0.68],
  [-0.18, -0.22, -0.08,  1.00,  0.28, -0.14],
  [-0.32, -0.38, -0.44,  0.28,  1.00, -0.28],
  [0.96,  0.82,  0.68, -0.14, -0.28,  1.00],
];

// ─── Correlation colour helper ────────────────────────────────────────────────

/**
 * Map a correlation value in [−1, 1] to an RGB CSS string.
 * −1 → deep red (#dc2626), 0 → near-white (#1a1a2e), +1 → deep blue (#2563eb)
 * The background is dark so we treat the midpoint as a dark neutral.
 */
function corrColour(value: number): { bg: string; fg: string } {
  if (value >= 0.99) return { bg: "#1e3a5f", fg: "#93c5fd" }; // diagonal / perfect

  const clamped = Math.max(-1, Math.min(1, value));

  if (clamped >= 0) {
    // 0 → dark neutral, 1 → strong blue
    const intensity = clamped;
    const r = Math.round(15 + (37 - 15) * (1 - intensity));
    const g = Math.round(15 + (99 - 15) * (1 - intensity));
    const b = Math.round(31 + (235 - 31) * intensity);
    return {
      bg: `rgb(${r},${g},${b})`,
      fg: intensity > 0.5 ? "#dbeafe" : "#a5b4fc",
    };
  } else {
    // 0 → dark neutral, −1 → strong red
    const intensity = Math.abs(clamped);
    const r = Math.round(15 + (220 - 15) * intensity);
    const g = Math.round(15 + (38 - 15) * (1 - intensity));
    const b = Math.round(31 + (38 - 31) * (1 - intensity));
    return {
      bg: `rgb(${r},${g},${b})`,
      fg: intensity > 0.5 ? "#fecaca" : "#fca5a5",
    };
  }
}

// ─── Regime banner ────────────────────────────────────────────────────────────

const REGIME_CONFIG: Record<
  MarketRegime,
  { icon: typeof TrendingUp; colour: string; description: string }
> = {
  "Risk-On": {
    icon: TrendingUp,
    colour: "text-emerald-400 bg-emerald-400/10 border-emerald-400/30",
    description: "Equities and high-beta assets outperforming. Capital flowing into risk assets.",
  },
  "Risk-Off": {
    icon: TrendingDown,
    colour: "text-rose-400 bg-rose-400/10 border-rose-400/30",
    description: "Defensive positioning. Gold, bonds, and low-volatility assets in favour.",
  },
  "Rotation": {
    icon: Repeat2,
    colour: "text-amber-400 bg-amber-400/10 border-amber-400/30",
    description: "Active sector rotation. Leadership changing between cyclicals and defensives.",
  },
};

function RegimeBanner({
  regime,
  rationale,
  vix,
  dxy,
}: {
  regime: MarketRegime;
  rationale: string;
  vix: number;
  dxy: number;
}) {
  const config = REGIME_CONFIG[regime];
  const Icon = config.icon;

  return (
    <div
      className={cn("rounded-lg border px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3", config.colour)}
      role="status"
      aria-label={`Market regime: ${regime}`}
    >
      <div className="flex items-center gap-2 shrink-0">
        <Icon className="size-4" aria-hidden="true" />
        <span className="font-semibold text-sm">{regime}</span>
      </div>
      <p className="text-xs flex-1">{rationale}</p>
      <div className="flex items-center gap-2 shrink-0">
        <Badge variant="outline" className="text-xs border-current gap-1 font-mono tabular-nums">
          VIX {vix.toFixed(1)}
        </Badge>
        <Badge variant="outline" className="text-xs border-current gap-1 font-mono tabular-nums">
          DXY {dxy.toFixed(1)}
        </Badge>
      </div>
    </div>
  );
}

// ─── Correlation matrix table ─────────────────────────────────────────────────

function CorrelationMatrix({
  symbols,
  matrix,
}: {
  symbols: string[];
  matrix: number[][];
}) {
  return (
    <div className="overflow-x-auto" role="region" aria-label="Correlation matrix">
      <table
        className="min-w-full border-collapse text-xs font-mono"
        aria-label="Pairwise correlation coefficients between instruments"
      >
        <thead>
          <tr>
            {/* Top-left empty corner */}
            <th className="h-9 w-24 sticky left-0 bg-surface-card z-10" aria-hidden="true" />
            {symbols.map((sym) => (
              <th
                key={sym}
                scope="col"
                className="h-9 px-2 text-center text-xxs font-medium text-text-muted uppercase tracking-wider whitespace-nowrap"
              >
                {sym}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, ri) => (
            <tr key={symbols[ri]}>
              {/* Row header */}
              <th
                scope="row"
                className="h-9 px-3 text-left text-xs font-medium text-text-secondary whitespace-nowrap sticky left-0 bg-surface-card z-10"
              >
                {symbols[ri]}
              </th>
              {row.map((val, ci) => {
                const isDiag = ri === ci;
                const { bg, fg } = corrColour(val);
                return (
                  <td
                    key={ci}
                    className="h-9 w-16 text-center tabular-nums font-mono text-xs font-semibold transition-opacity hover:opacity-90"
                    style={{ backgroundColor: bg, color: fg }}
                    aria-label={isDiag ? undefined : `${symbols[ri]} vs ${symbols[ci]}: ${val.toFixed(2)}`}
                    aria-hidden={isDiag ? true : undefined}
                  >
                    {val.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Colour scale legend ──────────────────────────────────────────────────────

function ColourScaleLegend() {
  const steps = [-1, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1];
  return (
    <div className="flex items-center gap-1">
      <span className="text-xxs text-text-muted mr-1">−1</span>
      {steps.map((v) => {
        const { bg } = corrColour(v);
        return (
          <div
            key={v}
            className="h-4 w-6 rounded-sm"
            style={{ backgroundColor: bg }}
            aria-hidden="true"
          />
        );
      })}
      <span className="text-xxs text-text-muted ml-1">+1</span>
    </div>
  );
}

// ─── Insight pills ────────────────────────────────────────────────────────────

function InsightPills({ symbols, matrix }: { symbols: string[]; matrix: number[][] }) {
  const insights = useMemo(() => {
    const results: { a: string; b: string; corr: number; type: "high" | "low" }[] = [];
    for (let i = 0; i < symbols.length; i++) {
      for (let j = i + 1; j < symbols.length; j++) {
        const corr = matrix[i][j];
        if (corr >= 0.85) results.push({ a: symbols[i], b: symbols[j], corr, type: "high" });
        if (corr <= -0.40) results.push({ a: symbols[i], b: symbols[j], corr, type: "low" });
      }
    }
    // Top 4 insights
    return results.sort((a, b) => Math.abs(b.corr) - Math.abs(a.corr)).slice(0, 4);
  }, [symbols, matrix]);

  if (insights.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2">
      {insights.map(({ a, b, corr, type }) => (
        <div
          key={`${a}-${b}`}
          className={cn(
            "text-xs rounded-md px-3 py-1.5 border",
            type === "high"
              ? "bg-blue-500/10 border-blue-500/30 text-blue-300"
              : "bg-rose-500/10 border-rose-500/30 text-rose-300",
          )}
        >
          <span className="font-mono font-semibold">{a} / {b}</span>
          <span className="ml-2 font-mono tabular-nums">{corr >= 0 ? "+" : ""}{corr.toFixed(2)}</span>
          <span className="ml-1.5 text-xxs opacity-80">
            {type === "high" ? "high correlation" : "inverse"}
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function CorrelationTab() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["correlation-matrix"],
    queryFn: getCorrelationMatrix,
    staleTime: 15 * 60_000,
    retry: 1,
  });

  const isDemo = isError || (!isLoading && (!data || data.is_sample_data !== false));
  const symbols = data?.symbols ?? DEMO_SYMBOLS;
  const matrix = data?.matrix ?? DEMO_MATRIX;
  const regime = data?.regime ?? "Risk-On";
  const rationale = data?.regime_rationale ?? "Sample data — regime based on rolling 30-day index correlations";
  const vix = data?.vix ?? 14.2;
  const dxy = data?.dxy ?? 103.8;

  if (isLoading) {
    return (
      <div
        className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted"
        role="status"
        aria-live="polite"
      >
        <RefreshCw className="size-5 animate-spin" aria-hidden="true" />
        <span className="text-sm">Computing correlation matrix...</span>
      </div>
    );
  }

  if (isError && !data) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-text-muted">
        <AlertCircle className="size-6" aria-hidden="true" />
        <p className="text-sm">Could not load correlation data.</p>
        <Button variant="ghost" size="sm" onClick={() => void refetch()} aria-label="Retry loading correlation data">
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
          <h3 className="font-heading font-semibold text-sm text-text-primary">Correlation Matrix</h3>
          <p className="text-xs text-text-muted mt-0.5">
            Pairwise correlations across {symbols.length} instruments — rolling 30-day window
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void refetch()}
          className="text-xs text-text-muted h-6 px-2 gap-1 shrink-0"
          aria-label="Refresh correlation matrix"
        >
          <RefreshCw className="size-3" aria-hidden="true" />
          Refresh
        </Button>
      </div>

      {/* Regime banner */}
      <RegimeBanner regime={regime} rationale={rationale} vix={vix} dxy={dxy} />

      {/* Key insights */}
      <InsightPills symbols={symbols} matrix={matrix} />

      {/* Correlation matrix heatmap */}
      <GlassCard className="p-0 overflow-hidden">
        <div className="p-4 border-b border-border-default">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-xxs text-text-muted uppercase tracking-wider">
              Correlation coefficients (30-day rolling)
            </span>
            <ColourScaleLegend />
          </div>
        </div>
        <CorrelationMatrix symbols={symbols} matrix={matrix} />
      </GlassCard>

      {/* Interpretation guide */}
      <GlassCard className="p-4">
        <p className="text-xxs text-text-muted uppercase tracking-wider mb-3">How to read this</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs text-text-secondary">
          <div>
            <span className="font-semibold text-blue-400">High positive (≥0.7)</span>
            <p className="text-text-muted mt-1">
              Instruments move together. Low diversification benefit between them.
            </p>
          </div>
          <div>
            <span className="font-semibold text-text-primary">Near zero (−0.3 to +0.3)</span>
            <p className="text-text-muted mt-1">
              Mostly uncorrelated. Combining them reduces overall portfolio volatility.
            </p>
          </div>
          <div>
            <span className="font-semibold text-rose-400">High negative (≤−0.4)</span>
            <p className="text-text-muted mt-1">
              Natural hedge. One tends to rise when the other falls — useful for risk reduction.
            </p>
          </div>
        </div>
      </GlassCard>

      <p className="text-xs text-text-muted">
        Correlation computed from daily closing prices over a rolling 30-day window.
        Values change daily and should not be treated as permanent relationships.
        {isDemo ? " Sample data shown — connect broker for live data." : ""}
      </p>
    </div>
  );
}

export default CorrelationTab;

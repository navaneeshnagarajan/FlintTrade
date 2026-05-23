/**
 * BenchmarkTab.tsx — Portfolio vs Indian benchmark comparison.
 *
 * Shows portfolio returns against NIFTY 50, NIFTY Next 50, NIFTY Midcap 150,
 * SENSEX, and NIFTY Bank across multiple time periods.
 * Alpha (portfolio - benchmark) is highlighted green/red.
 *
 * Uses sample data for portfolio and realistic benchmark returns.
 */

import { useMemo } from "react";
import {
  TrendingUp,
  ArrowUpRight,
  ArrowDownRight,
  Activity,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlossaryTooltip } from "@/components/ui/GlossaryTooltip";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────────────────────

interface PeriodReturns {
  "1D": number;
  "1W": number;
  "1M": number;
  "3M": number;
  "6M": number;
  "1Y": number;
  "3Y": number;
  "5Y": number;
}

type PeriodKey = keyof PeriodReturns;

interface BenchmarkRow {
  name: string;
  returns: PeriodReturns;
}

// ─── Sample data ─────────────────────────────────────────────────────────────

const PERIODS: PeriodKey[] = ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"];

const PORTFOLIO_RETURNS: PeriodReturns = {
  "1D": 0.42,
  "1W": 1.15,
  "1M": 2.31,
  "3M": 5.87,
  "6M": 9.12,
  "1Y": 18.45,
  "3Y": 52.3,
  "5Y": 112.5,
};

const BENCHMARKS: BenchmarkRow[] = [
  {
    name: "NIFTY 50",
    returns: {
      "1D": 0.35,
      "1W": 0.92,
      "1M": 1.85,
      "3M": 4.52,
      "6M": 7.38,
      "1Y": 14.2,
      "3Y": 42.1,
      "5Y": 95.6,
    },
  },
  {
    name: "NIFTY Next 50",
    returns: {
      "1D": 0.28,
      "1W": 0.75,
      "1M": 2.12,
      "3M": 5.1,
      "6M": 8.45,
      "1Y": 16.8,
      "3Y": 48.5,
      "5Y": 105.2,
    },
  },
  {
    name: "NIFTY Midcap 150",
    returns: {
      "1D": 0.52,
      "1W": 1.35,
      "1M": 3.15,
      "3M": 7.82,
      "6M": 12.5,
      "1Y": 22.3,
      "3Y": 65.8,
      "5Y": 145.2,
    },
  },
  {
    name: "SENSEX",
    returns: {
      "1D": 0.33,
      "1W": 0.88,
      "1M": 1.78,
      "3M": 4.35,
      "6M": 7.15,
      "1Y": 13.8,
      "3Y": 40.5,
      "5Y": 92.3,
    },
  },
  {
    name: "NIFTY Bank",
    returns: {
      "1D": 0.18,
      "1W": 0.62,
      "1M": 1.45,
      "3M": 3.28,
      "6M": 5.92,
      "1Y": 11.5,
      "3Y": 35.2,
      "5Y": 78.4,
    },
  },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatReturn(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function BenchmarkTab() {
  const alphaRows = useMemo(
    () =>
      BENCHMARKS.map((b) => {
        const alpha: PeriodReturns = {} as PeriodReturns;
        for (const p of PERIODS) {
          alpha[p] = PORTFOLIO_RETURNS[p] - b.returns[p];
        }
        return { name: b.name, alpha };
      }),
    [],
  );

  return (
    <div className="space-y-6">
      {/* Demo banner */}
      <DemoBanner />

      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="size-8 rounded-lg flex items-center justify-center bg-surface-elevated">
          <Activity className="size-4 text-accent" />
        </div>
        <div>
          <h2 className="font-heading font-semibold text-base text-text-primary">
            Benchmark Comparison
          </h2>
          <p className="text-xs text-text-muted">
            Portfolio performance vs major Indian indices
          </p>
        </div>
      </div>

      {/* Main comparison table */}
      <GlassCard className="p-0 gap-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs" role="table">
            <thead>
              <tr className="border-b border-border-default bg-surface-elevated/50">
                <th className="text-left px-4 py-3 font-heading font-semibold text-text-secondary whitespace-nowrap sticky left-0 bg-surface-elevated/50 z-10">
                  Index
                </th>
                {PERIODS.map((p) => (
                  <th
                    key={p}
                    className="text-right px-3 py-3 font-mono font-semibold text-text-secondary whitespace-nowrap"
                  >
                    {p}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {/* Portfolio row — highlighted */}
              <tr className="border-b border-border-default bg-accent/5">
                <td className="px-4 py-3 font-heading font-semibold text-accent whitespace-nowrap sticky left-0 bg-accent/5 z-10">
                  <div className="flex items-center gap-2">
                    <TrendingUp className="size-3.5" />
                    Your Portfolio
                  </div>
                </td>
                {PERIODS.map((p) => {
                  const val = PORTFOLIO_RETURNS[p];
                  return (
                    <td
                      key={p}
                      className={cn(
                        "text-right px-3 py-3 font-mono tabular-nums font-semibold",
                        val >= 0 ? "text-profit" : "text-loss",
                      )}
                    >
                      {formatReturn(val)}
                    </td>
                  );
                })}
              </tr>

              {/* Benchmark rows */}
              {BENCHMARKS.map((b) => (
                <tr
                  key={b.name}
                  className="border-b border-border-default last:border-0 hover:bg-surface-elevated/30 transition-colors"
                >
                  <td className="px-4 py-3 font-heading font-medium text-text-primary whitespace-nowrap sticky left-0 bg-surface-card z-10">
                    {b.name}
                  </td>
                  {PERIODS.map((p) => {
                    const val = b.returns[p];
                    return (
                      <td
                        key={p}
                        className={cn(
                          "text-right px-3 py-3 font-mono tabular-nums",
                          val >= 0 ? "text-text-primary" : "text-loss",
                        )}
                      >
                        {formatReturn(val)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {/* Alpha table */}
      <GlassCard className="p-0 gap-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-border-default">
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            <GlossaryTooltip term="Alpha">Alpha</GlossaryTooltip>{" "}
            <span className="font-normal text-text-muted">(Portfolio - Benchmark)</span>
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" role="table">
            <thead>
              <tr className="border-b border-border-default bg-surface-elevated/50">
                <th className="text-left px-4 py-3 font-heading font-semibold text-text-secondary whitespace-nowrap sticky left-0 bg-surface-elevated/50 z-10">
                  vs Index
                </th>
                {PERIODS.map((p) => (
                  <th
                    key={p}
                    className="text-right px-3 py-3 font-mono font-semibold text-text-secondary whitespace-nowrap"
                  >
                    {p}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {alphaRows.map((row) => (
                <tr
                  key={row.name}
                  className="border-b border-border-default last:border-0 hover:bg-surface-elevated/30 transition-colors"
                >
                  <td className="px-4 py-3 font-heading font-medium text-text-primary whitespace-nowrap sticky left-0 bg-surface-card z-10">
                    {row.name}
                  </td>
                  {PERIODS.map((p) => {
                    const val = row.alpha[p];
                    return (
                      <td key={p} className="text-right px-3 py-3">
                        <span
                          className={cn(
                            "inline-flex items-center gap-0.5 font-mono tabular-nums font-semibold",
                            val >= 0 ? "text-profit" : "text-loss",
                          )}
                        >
                          {val >= 0 ? (
                            <ArrowUpRight className="size-3" />
                          ) : (
                            <ArrowDownRight className="size-3" />
                          )}
                          {formatReturn(val)}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <GlassCard className="p-4 gap-2">
          <p className="text-xxs text-text-muted uppercase tracking-wider font-medium">
            Best 1Y Alpha
          </p>
          {(() => {
            const best = alphaRows.reduce((best, row) =>
              row.alpha["1Y"] > best.alpha["1Y"] ? row : best,
            );
            return (
              <>
                <div className="text-lg font-mono font-bold tabular-nums text-profit">
                  {formatReturn(best.alpha["1Y"])}
                </div>
                <p className="text-xs text-text-muted">vs {best.name}</p>
              </>
            );
          })()}
        </GlassCard>

        <GlassCard className="p-4 gap-2">
          <p className="text-xxs text-text-muted uppercase tracking-wider font-medium">
            Worst 1Y Alpha
          </p>
          {(() => {
            const worst = alphaRows.reduce((worst, row) =>
              row.alpha["1Y"] < worst.alpha["1Y"] ? row : worst,
            );
            const val = worst.alpha["1Y"];
            return (
              <>
                <div
                  className={cn(
                    "text-lg font-mono font-bold tabular-nums",
                    val >= 0 ? "text-profit" : "text-loss",
                  )}
                >
                  {formatReturn(val)}
                </div>
                <p className="text-xs text-text-muted">vs {worst.name}</p>
              </>
            );
          })()}
        </GlassCard>

        <GlassCard className="p-4 gap-2">
          <p className="text-xxs text-text-muted uppercase tracking-wider font-medium">
            Benchmarks Beaten (1Y)
          </p>
          <div className="text-lg font-mono font-bold tabular-nums text-text-primary">
            {alphaRows.filter((r) => r.alpha["1Y"] > 0).length}/{alphaRows.length}
          </div>
          <p className="text-xs text-text-muted">indices outperformed</p>
        </GlassCard>
      </div>

      <p className="text-xs text-text-muted">
        Benchmark data is illustrative. Live index data requires a market data subscription.
        Returns are absolute (not annualised) for periods under 1Y.
      </p>
    </div>
  );
}

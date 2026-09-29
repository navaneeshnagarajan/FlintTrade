/**
 * BenchmarkTab.tsx — Portfolio vs Indian benchmark comparison.
 *
 * Index rows are sample figures and keep the Example chip. The portfolio row
 * shows the book return only when the holdings are the account, with no chip.
 * Alpha and other verdicts stay hidden until the indices are real.
 */

import {
  TrendingUp,
  Activity,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ExampleLabel } from "@/components/data/ExampleLabel";
import { cn } from "@/lib/utils";
import { formatPercent } from "../formatters";
import { useInvest } from "../InvestContext";

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

const COMPARISON_NOTE = "Comparison needs real index data.";

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
  return formatPercent(value);
}

/**
 * Cost-basis return of a holdings book, in percent.
 *
 * This is the account figure (total P&L over amount invested). It is not a
 * 1D/1Y index return, and it is not comparable with the sample index rows.
 */
export function portfolioBookReturn(
  holdings: readonly { averagePrice: number; quantity: number; pnl: number }[],
): number | null {
  let invested = 0;
  let pnl = 0;
  for (const holding of holdings) {
    const price = Number.isFinite(holding.averagePrice) ? holding.averagePrice : 0;
    const quantity = Number.isFinite(holding.quantity) ? Math.abs(holding.quantity) : 0;
    const linePnl = Number.isFinite(holding.pnl) ? holding.pnl : 0;
    invested += price * quantity;
    pnl += linePnl;
  }
  if (invested <= 0) return null;
  return (pnl / invested) * 100;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function BenchmarkTab() {
  const { holdings, isSampleData } = useInvest();
  const hasHoldings = holdings.length > 0;
  const hasRealHoldings = hasHoldings && !isSampleData;
  const bookReturn = portfolioBookReturn(holdings);
  const portfolioLabel = hasRealHoldings
    ? "Your Portfolio (since first buy)"
    : "Your Portfolio";

  return (
    <div className="space-y-6">
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
              <tr
                className="border-b border-border-default bg-accent/5"
                data-testid="benchmark-portfolio-row"
                aria-label={portfolioLabel}
              >
                <td className="px-4 py-3 font-heading font-semibold text-accent whitespace-nowrap sticky left-0 bg-accent/5 z-10">
                  <div className="flex items-center gap-2">
                    <TrendingUp className="size-3.5" />
                    {portfolioLabel}
                    {hasHoldings && (
                      <span
                        data-testid="benchmark-portfolio-return"
                        className={cn(
                          "font-mono tabular-nums",
                          bookReturn == null
                            ? "text-text-muted"
                            : bookReturn >= 0
                              ? "text-profit"
                              : "text-loss",
                        )}
                      >
                        {bookReturn == null ? "—" : formatReturn(bookReturn)}
                      </span>
                    )}
                    {hasHoldings && !hasRealHoldings && (
                      <ExampleLabel testId="benchmark-portfolio-example" />
                    )}
                  </div>
                </td>
                {PERIODS.map((p) => (
                  <td
                    key={p}
                    className="text-right px-3 py-3 font-mono tabular-nums text-text-muted"
                  >
                    —
                  </td>
                ))}
              </tr>

              {/* Benchmark rows */}
              {BENCHMARKS.map((b) => (
                <tr
                  key={b.name}
                  className="border-b border-border-default last:border-0 hover:bg-surface-elevated/30 transition-colors"
                >
                  <td className="px-4 py-3 font-heading font-medium text-text-primary whitespace-nowrap sticky left-0 bg-surface-card z-10">
                    <div className="flex items-center gap-2">
                      {b.name}
                      <ExampleLabel testId="benchmark-row-example" />
                    </div>
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

      {!hasHoldings && (
        <p className="text-xs text-text-muted" data-testid="benchmark-empty-note">
          Add holdings to compare against benchmarks.
        </p>
      )}

      {hasHoldings && (
        <p className="text-xs text-text-muted" data-testid="benchmark-comparison-note">
          {COMPARISON_NOTE}
        </p>
      )}

      <p className="text-xs text-text-muted">
        Benchmark data is illustrative. Live index data requires a market data subscription.
        Returns are absolute (not annualised) for periods under 1Y.
      </p>
    </div>
  );
}

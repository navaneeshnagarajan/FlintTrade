import { useMemo } from "react";
import { useMutation } from "@tanstack/react-query";
import { Dices } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/GlassCard";
import { runPermutationTest, type BacktestResult } from "@/services/ftApi";
import { fmtNum } from "./formatters";

/** Minimum return observations for a permutation test to be worth trusting. */
const MIN_RETURNS = 10;

/** Period-over-period returns from the equity curve (drops zero-equity rows). */
function deriveReturns(curve: BacktestResult["equity_curve"]): number[] {
  const out: number[] = [];
  for (let i = 1; i < curve.length; i += 1) {
    const prev = curve[i - 1].equity;
    if (prev !== 0) out.push((curve[i].equity - prev) / prev);
  }
  return out;
}

/**
 * Permutation (Monte-Carlo) significance test for a completed backtest — asks
 * "is this edge real or could a random reordering of the same returns have done
 * as well?". Derives the return series from the equity curve and posts it to
 * the real ``/v1/backtest/permutation`` engine; the verdict is the backend's,
 * never fabricated.
 */
export function RobustnessCard({ result }: { result: BacktestResult }) {
  const returns = useMemo(() => deriveReturns(result.equity_curve), [result.equity_curve]);
  const enough = returns.length >= MIN_RETURNS;
  const test = useMutation({ mutationFn: () => runPermutationTest(returns) });
  const r = test.data;

  return (
    <GlassCard className="p-5 gap-3">
      <div className="flex items-center justify-between gap-3">
        <h4 className="font-heading font-semibold text-sm text-text-primary">
          Robustness — Skill vs Luck
        </h4>
        <Button
          size="sm"
          onClick={() => test.mutate()}
          disabled={!enough || test.isPending}
          aria-label="Run permutation test"
        >
          <Dices size={14} className="mr-1.5" aria-hidden="true" />
          {test.isPending ? "Testing…" : "Run permutation test"}
        </Button>
      </div>

      {!enough && (
        <p className="text-xs text-text-muted">
          A reliable significance test needs at least {MIN_RETURNS} equity points — this
          backtest produced {returns.length}. Run a longer backtest first.
        </p>
      )}

      {test.isError && (
        <p className="text-xs text-loss">
          Permutation test failed — {(test.error as Error).message}
        </p>
      )}

      {r && (
        <div className="space-y-2">
          <Badge variant={r.is_significant ? "bullish" : "bearish"}>
            {r.is_significant
              ? "Statistically significant edge"
              : "Not significant — likely luck"}
          </Badge>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div>
              <p className="text-text-muted">p-value</p>
              <p className="font-mono text-text-primary">{r.p_value.toFixed(4)}</p>
            </div>
            <div>
              <p className="text-text-muted">Confidence</p>
              <p className="font-mono text-text-primary">{(r.confidence_level * 100).toFixed(0)}%</p>
            </div>
            <div>
              <p className="text-text-muted">Percentile rank</p>
              <p className="font-mono text-text-primary">{r.percentile_rank.toFixed(1)}</p>
            </div>
            <div>
              <p className="text-text-muted">Permutations</p>
              <p className="font-mono text-text-primary">{r.n_permutations.toLocaleString("en-IN")}</p>
            </div>
          </div>
          <p className="text-xxs text-text-muted">
            Observed {fmtNum(r.original_metric)} vs random mean {fmtNum(r.permutation_mean)} (±
            {fmtNum(r.permutation_std)}). A low p-value means a random reordering rarely matched
            this result — the edge is unlikely to be chance.
          </p>
        </div>
      )}
    </GlassCard>
  );
}

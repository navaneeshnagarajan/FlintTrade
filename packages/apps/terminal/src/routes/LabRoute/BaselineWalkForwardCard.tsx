/**
 * BaselineWalkForwardCard — honest UI over /v1/backtest/walkforward.
 *
 * The route walk-forwards its built-in BUY-AND-HOLD baseline (custom
 * strategies are programmatic-only), so this card is explicitly framed as a
 * regime-stability check on the instrument's data — how consistent the
 * baseline Sharpe is between in-sample and out-of-sample windows — and NOT a
 * robustness test of the user's strategy (RobustnessCard covers that).
 */

import { useState } from "react";
import { Loader2, Play, SlidersHorizontal } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { getHistory } from "@/services/api";
import { runBaselineWalkForward, type WalkForwardResult } from "@/services/ftApi";
import { fmtNum } from "./formatters";

const MIN_BARS = 60;

async function runForSymbol(symbol: string, lookbackDays: number, nSplits: number): Promise<WalkForwardResult> {
  const today = new Date();
  const end = today.toISOString().slice(0, 10);
  const start = new Date(today.getTime() - lookbackDays * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);

  const bars = await getHistory(symbol.toUpperCase(), "NSE_INDEX", "D", start, end);
  if (!Array.isArray(bars) || bars.length < MIN_BARS) {
    throw new Error(
      `Not enough history for ${symbol.toUpperCase()} (${Array.isArray(bars) ? bars.length : 0} bars; need ${MIN_BARS}+)`,
    );
  }
  return runBaselineWalkForward(bars, "sharpe_ratio", { n_splits: nSplits });
}

export function BaselineWalkForwardCard() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [lookbackDays, setLookbackDays] = useState(365);
  const [nSplits, setNSplits] = useState(5);

  const mutation = useMutation<WalkForwardResult, Error, void>({
    mutationFn: () => runForSymbol(symbol, lookbackDays, nSplits),
  });
  const result = mutation.data;

  return (
    <GlassCard className="p-5 gap-3">
      <div className="flex items-center gap-2">
        <SlidersHorizontal size={15} className="text-accent" aria-hidden="true" />
        <h3 className="font-heading font-semibold text-base text-text-primary">
          Baseline walk-forward (buy &amp; hold)
        </h3>
      </div>
      <p className="text-xs text-text-muted leading-relaxed">
        Walk-forwards a <span className="font-semibold">buy-and-hold baseline</span> over
        the instrument&rsquo;s real history — a regime-stability check on the data
        (does the baseline Sharpe hold up out-of-sample?). It does <span className="font-semibold">not</span> test
        your strategy; use the Robustness panel for that.
      </p>

      <div className="flex items-end gap-2 flex-wrap">
        <label className="flex flex-col gap-1 text-xxs text-text-muted uppercase tracking-wide">
          Symbol
          <Input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="h-8 w-32 text-xs bg-surface-base border-border-default text-text-primary"
            aria-label="Walk-forward symbol"
          />
        </label>
        <label className="flex flex-col gap-1 text-xxs text-text-muted uppercase tracking-wide">
          Lookback (days)
          <Input
            type="number"
            value={lookbackDays}
            onChange={(e) => setLookbackDays(Math.max(90, Number(e.target.value) || 365))}
            className="h-8 w-28 text-xs bg-surface-base border-border-default text-text-primary"
            aria-label="Lookback days"
          />
        </label>
        <label className="flex flex-col gap-1 text-xxs text-text-muted uppercase tracking-wide">
          Splits
          <Input
            type="number"
            value={nSplits}
            onChange={(e) => setNSplits(Math.min(12, Math.max(2, Number(e.target.value) || 5)))}
            className="h-8 w-20 text-xs bg-surface-base border-border-default text-text-primary"
            aria-label="Number of splits"
          />
        </label>
        <Button
          size="sm"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !symbol.trim()}
          className="h-8 px-4 text-xs"
        >
          {mutation.isPending
            ? <Loader2 size={12} className="animate-spin mr-1.5" aria-hidden="true" />
            : <Play size={11} className="mr-1.5" aria-hidden="true" />}
          Run
        </Button>
      </div>

      {mutation.isError && (
        <p className="text-xs text-loss">{mutation.error.message}</p>
      )}

      {result && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "In-sample Sharpe", value: fmtNum(result.avg_train_metric) },
              { label: "Out-of-sample Sharpe", value: fmtNum(result.avg_test_metric) },
              { label: "Degradation", value: `${fmtNum(result.degradation_pct, 1)}%` },
              { label: "Splits run", value: String(result.n_splits_run) },
            ].map((s) => (
              <div key={s.label} className="bg-surface-base border border-border-default rounded-lg p-3 text-center">
                <p className="text-xxs text-text-muted">{s.label}</p>
                <p className="text-sm font-mono text-text-primary mt-1 tabular-nums">{s.value}</p>
              </div>
            ))}
          </div>

          <Badge
            className={result.is_robust
              ? "bg-bullish-bg text-profit text-xs"
              : "bg-atm-bg text-warning text-xs"}
          >
            {result.is_robust
              ? "Stable — baseline holds out-of-sample (degradation < 30%)"
              : "Unstable — baseline degrades out-of-sample (regime shift likely)"}
          </Badge>

          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="text-xxs text-text-muted font-medium">Split</TableHead>
                  <TableHead className="text-xxs text-text-muted font-medium text-right">Train bars</TableHead>
                  <TableHead className="text-xxs text-text-muted font-medium text-right">Test bars</TableHead>
                  <TableHead className="text-xxs text-text-muted font-medium text-right">Train Sharpe</TableHead>
                  <TableHead className="text-xxs text-text-muted font-medium text-right">Test Sharpe</TableHead>
                  <TableHead className="text-xxs text-text-muted font-medium text-right">Degradation</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.splits.map((s) => (
                  <TableRow key={s.split_index} className="border-border-subtle hover:bg-surface-base">
                    <TableCell className="text-xs font-mono py-1 text-text-primary">#{s.split_index + 1}</TableCell>
                    <TableCell className="text-xs font-mono py-1 text-right tabular-nums text-text-secondary">{s.n_train_bars}</TableCell>
                    <TableCell className="text-xs font-mono py-1 text-right tabular-nums text-text-secondary">{s.n_test_bars}</TableCell>
                    <TableCell className="text-xs font-mono py-1 text-right tabular-nums text-text-secondary">{fmtNum(s.train_metric)}</TableCell>
                    <TableCell className="text-xs font-mono py-1 text-right tabular-nums text-text-secondary">{fmtNum(s.test_metric)}</TableCell>
                    <TableCell className={`text-xs font-mono py-1 text-right tabular-nums ${Math.abs(s.degradation_pct) < 30 ? "text-profit" : "text-warning"}`}>
                      {fmtNum(s.degradation_pct, 1)}%
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </GlassCard>
  );
}

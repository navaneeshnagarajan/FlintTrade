import { memo, useMemo, useState } from "react";
import { ArrowUpDown } from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import { Button } from "@/components/ui/button";
import { useModeStore } from "@/stores/modeStore";
import { EXAMPLE_FUNDING_RATES, type ExampleFundingRate } from "./sampleData";

type SortMode = "magnitude" | "rate" | "alpha";
const SORT_LABELS: Record<SortMode, string> = {
  magnitude: "Sort: Magnitude",
  rate: "Sort: Highest rate",
  alpha: "Sort: A–Z",
};
const EXAMPLE_NOTIONAL_USD = 10_000;

function formatRate(rate: number): string {
  return `${rate >= 0 ? "+" : ""}${(rate * 100).toFixed(4)}%`;
}

function RateRow({ entry }: { entry: ExampleFundingRate }) {
  const payment = EXAMPLE_NOTIONAL_USD * entry.rate;
  const colour = entry.rate > 0 ? "text-profit" : entry.rate < 0 ? "text-loss" : "text-text-muted";
  const last = entry.history.at(-1) ?? 0;
  const previous = entry.history.at(-2) ?? last;

  return (
    <tr className="border-b border-border-subtle hover:bg-surface-hover/40">
      <th scope="row" className="px-3 py-2 text-xs font-mono text-text-primary">{entry.symbol}</th>
      <td className={`px-3 py-2 text-right text-xs font-mono tabular-nums ${colour}`}>
        {formatRate(entry.rate)}
      </td>
      <td className="px-3 py-2 text-right text-xs tabular-nums text-text-secondary">
        {payment === 0 ? "No payment" : `${payment > 0 ? "Pays" : "Receives"} $${Math.abs(payment).toFixed(2)}`}
      </td>
      <td className="px-3 py-2">
        <FlintMiniSparkline
          points={[...entry.history]}
          positive={last >= previous}
          ariaLabel={`${entry.symbol} illustrative funding history`}
          className="h-6 w-20"
        />
      </td>
    </tr>
  );
}

function FundingRateWidget() {
  const mode = useModeStore((state) => state.mode);
  const [sortMode, setSortMode] = useState<SortMode>("magnitude");
  const entries = useMemo(() => [...EXAMPLE_FUNDING_RATES].sort((left, right) => {
    if (sortMode === "alpha") return left.symbol.localeCompare(right.symbol);
    if (sortMode === "rate") return right.rate - left.rate;
    return Math.abs(right.rate) - Math.abs(left.rate);
  }), [sortMode]);

  // The native adapter catalogue has no funding-rate provider. Account
  // connection cannot turn these illustrative figures into market data.
  if (mode !== "explore") {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-2 bg-surface-base px-4 text-center" role="status">
        <span className="text-sm font-medium text-text-primary">Funding rates are Example only</span>
        <p className="text-xs text-text-muted max-w-72">
          No native funding-rate source is available. Choose Example in the Mode menu to view the illustration.
        </p>
      </div>
    );
  }

  const positive = entries.filter((entry) => entry.rate > 0).length;
  const negative = entries.filter((entry) => entry.rate < 0).length;
  const mean = entries.reduce((sum, entry) => sum + entry.rate, 0) / entries.length;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">
      <div className="flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <span className="text-xs font-medium text-text-primary">Funding Rates</span>
        <span className="rounded bg-warning/10 px-1.5 py-0.5 text-xxs text-warning" role="status" aria-label="Illustrative funding rates; no market feed">Example</span>
        <div className="flex-1" />
        <Button
          variant="outline"
          size="sm"
          onClick={() => setSortMode((current) => current === "magnitude" ? "rate" : current === "rate" ? "alpha" : "magnitude")}
          className="h-6 px-2 text-xs text-text-muted border-border-subtle"
          aria-label="Cycle sort order"
        >
          <ArrowUpDown size={11} aria-hidden="true" />
          {SORT_LABELS[sortMode]}
        </Button>
      </div>
      <p className="px-3 py-2 text-xs text-text-muted border-b border-border-subtle">
        Fixed illustrative rates per funding period. Positive rates: longs pay shorts; negative rates: shorts pay longs.
        Payments below use a hypothetical $10,000 position.
      </p>
      <dl className="flex items-center gap-4 px-3 py-1.5 text-xs border-b border-border-subtle">
        <div className="flex gap-1.5"><dt className="text-text-muted">Positive</dt><dd className="text-profit font-mono">{positive}</dd></div>
        <div className="flex gap-1.5"><dt className="text-text-muted">Negative</dt><dd className="text-loss font-mono">{negative}</dd></div>
        <div className="flex gap-1.5"><dt className="text-text-muted">Average example rate</dt><dd className="text-text-secondary font-mono">{formatRate(mean)}</dd></div>
      </dl>
      <div className="flex-1 overflow-auto">
        <table className="w-full text-left border-collapse" aria-label="Example perpetual funding rates">
          <thead className="sticky top-0 bg-surface-card">
            <tr className="border-b border-border-default text-xxs text-text-muted">
              <th scope="col" className="px-3 py-2">Symbol</th>
              <th scope="col" className="px-3 py-2 text-right">Example rate</th>
              <th scope="col" className="px-3 py-2 text-right">Long position funding</th>
              <th scope="col" className="px-3 py-2">Illustrative history</th>
            </tr>
          </thead>
          <tbody>{entries.map((entry) => <RateRow key={entry.symbol} entry={entry} />)}</tbody>
        </table>
      </div>
    </div>
  );
}

export default memo(FundingRateWidget);

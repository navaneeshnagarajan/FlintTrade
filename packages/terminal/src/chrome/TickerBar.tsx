import { useAtomValue } from "jotai";
import { indicesSummaryAtom } from "@/atoms/marketAtoms";
import type { WsTick } from "@/types/api";

interface IndexChipProps {
  name: string;
  data: WsTick | null;
}

function IndexChip({ name, data }: IndexChipProps) {
  const ltp = data?.ltp ?? null;
  const change = data?.change ?? 0;
  const pct = data?.pct ?? 0;
  const isUp = change >= 0;

  return (
    <div className="flex items-center gap-2 px-3 shrink-0 border-r border-border-default last:border-r-0 h-full">
      <span className="text-xs text-text-muted">{name}</span>
      <span className="text-xs font-mono text-text-primary tabular-nums">
        {ltp !== null
          ? ltp.toLocaleString("en-IN", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })
          : "\u2014"}
      </span>
      {ltp !== null && (
        <span
          className={`text-xs font-mono tabular-nums rounded px-1 ${
            isUp ? "bg-bullish-bg text-bullish-text" : "bg-bearish-bg text-bearish-text"
          }`}
        >
          {isUp ? "\u25b2" : "\u25bc"}{Math.abs(pct).toFixed(2)}%
        </span>
      )}
    </div>
  );
}

/**
 * TickerBar -- always-visible bar at h-7 showing live index prices.
 * Reads from Jotai indicesSummaryAtom (populated by useWsBridge).
 */
export default function TickerBar() {
  const indices = useAtomValue(indicesSummaryAtom);

  return (
    <div
      className="h-7 bg-surface-base border-b border-border-default flex items-center overflow-x-auto shrink-0"
      role="region"
      aria-label="Market indices"
    >
      {indices.map((idx) => (
        <IndexChip key={idx.name} name={idx.name} data={idx.data} />
      ))}
    </div>
  );
}

/**
 * MiniChartCard — NIFTY 50 headline (live atom) + an illustrative sparkline.
 *
 * The headline price/change read the live NIFTY atom — the simulated demo feed
 * in Explore, the broker WebSocket in Live. With no tick yet they show a dash,
 * never a fabricated number. The sparkline is illustrative SHAPE data only (a
 * real history hook lands in a later wave), so it carries a visible Sample
 * provenance badge: no unguarded placeholder price may render on a live surface
 * (the no-mock-data house rule — a card that shows a fake price next to a real
 * order button is a safety bug).
 */

import { useState } from "react";
import { useAtomValue } from "jotai";
import { BentoCard } from "@/components/bento/BentoCard";
import { TrendingUp } from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import { niftyAtom } from "@/atoms/marketAtoms";
import { ProvenanceBadge } from "@/routes/home/DemoBadge";

type Timeframe = "1D" | "1W" | "1M" | "3M";
const TIMEFRAMES: Timeframe[] = ["1D", "1W", "1M", "3M"];

// Illustrative sparkline SHAPE only — NOT real history and NOT a real price. The
// headline number never comes from here; the visible Sample badge marks it.
const SAMPLE_SHAPE: Record<Timeframe, number[]> = {
  "1D": [22100, 22150, 22090, 22200, 22180, 22250, 22230, 22300, 22280, 22350, 22320, 22400],
  "1W": [21800, 21950, 22100, 22050, 22200, 22150, 22300],
  "1M": [21000, 21200, 21500, 21300, 21700, 22000, 22200, 22400],
  "3M": [20000, 20500, 21000, 20800, 21500, 22000, 22400],
};

export function MiniChartCard() {
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");
  const tick = useAtomValue(niftyAtom);

  const shape = SAMPLE_SHAPE[timeframe];
  const ltp = tick?.ltp ?? null;
  const change = tick?.change ?? null;
  const changePct = tick?.pct ?? null;
  const positive = (change ?? 0) >= 0;

  return (
    <BentoCard size="wide" label="NIFTY Chart" data-testid="mini-chart-card">
      <div className="p-4 h-full flex flex-col gap-3">
        {/* Header — live LTP/change, or a dash when no tick has arrived */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp size={13} className="text-text-muted" aria-hidden="true" />
            <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
              NIFTY 50
            </p>
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className="font-mono text-sm font-semibold text-text-primary"
              data-testid="mini-chart-ltp"
            >
              {ltp !== null ? ltp.toLocaleString("en-IN") : "—"}
            </span>
            <span
              className="font-mono text-xs"
              style={{ color: positive ? "var(--color-bullish-text)" : "var(--color-bearish-text)" }}
            >
              {change !== null && changePct !== null
                ? `${positive ? "+" : ""}${change.toFixed(0)} (${positive ? "+" : ""}${changePct.toFixed(2)}%)`
                : "—"}
            </span>
          </div>
        </div>

        {/* Sparkline — illustrative shape, badged so it cannot read as live data */}
        <div className="flex-1 relative">
          <ProvenanceBadge
            label="Sample"
            testId="mini-chart-demo-badge"
            title="Illustrative shape only — not live price history"
          />
          <FlintMiniSparkline
            points={shape}
            positive={positive}
            ariaLabel={`NIFTY 50 ${timeframe} illustrative sparkline (sample data)`}
            className="h-full w-full"
          />
        </div>

        {/* Timeframe pills */}
        <div className="flex items-center gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              aria-pressed={timeframe === tf}
              className="px-2 py-0.5 rounded-md text-[10px] font-medium transition-colors"
              style={{
                background: timeframe === tf
                  ? "var(--color-surface-active)"
                  : "transparent",
                color: timeframe === tf ? "var(--color-text-primary)" : "var(--color-text-muted)",
                border: "1px solid",
                borderColor: timeframe === tf
                  ? "var(--color-border-default)"
                  : "transparent",
              }}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>
    </BentoCard>
  );
}

/**
 * PortfolioCard — Net worth + allocation bar (Equity/MF/Gold/F&O).
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { useFunds } from "@/hooks/useFunds";
import { useHoldings } from "@/hooks/useHoldings";
import { getDemoFunds, getDemoHoldings } from "@/hooks/useModeData";
import { useModeStore } from "@/stores/modeStore";

interface AllocationSlice {
  label: string;
  color: string;
  pct: number;
}

const ALLOCATION: AllocationSlice[] = [
  { label: "Equity", color: "#3b82f6", pct: 45 },
  { label: "MF",     color: "#8b5cf6", pct: 30 },
  { label: "Gold",   color: "#f59e0b", pct: 10 },
  { label: "F&O",    color: "#22c55e", pct: 15 },
];

export function PortfolioCard() {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const fundsQuery = useFunds();
  const holdingsQuery = useHoldings();

  const funds = isExplore ? getDemoFunds() : fundsQuery.data;
  const holdings = isExplore ? getDemoHoldings() : holdingsQuery.data;

  const holdingsValue = holdings?.reduce(
    (sum, h) => sum + h.ltp * Math.abs(h.quantity),
    0
  ) ?? 0;

  const netWorth = holdingsValue + (funds?.availableCash ?? 0);

  return (
    <BentoCard size="default" label="Portfolio" data-testid="portfolio-card">
      <div className="p-4 h-full flex flex-col gap-3">
        <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
          Portfolio
        </p>

        <div>
          <p className="text-[10px] text-text-muted mb-0.5">Net Worth</p>
          <p className="font-mono text-xl font-semibold text-text-primary">
            {netWorth > 0
              ? netWorth.toLocaleString("en-IN", {
                  style: "currency",
                  currency: "INR",
                  maximumFractionDigits: 0,
                })
              : "—"}
          </p>
        </div>

        {/* Allocation bar */}
        <div>
          <p className="text-[10px] text-text-muted mb-1.5">Allocation</p>
          <div
            className="flex h-2 rounded-full overflow-hidden"
            role="img"
            aria-label="Portfolio allocation bar"
          >
            {ALLOCATION.map((slice) => (
              <div
                key={slice.label}
                style={{ width: `${slice.pct}%`, background: slice.color }}
                title={`${slice.label}: ${slice.pct}%`}
              />
            ))}
          </div>
          {/* Legend */}
          <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
            {ALLOCATION.map((slice) => (
              <div key={slice.label} className="flex items-center gap-1">
                <span
                  className="inline-block w-2 h-2 rounded-full"
                  style={{ background: slice.color }}
                  aria-hidden="true"
                />
                <span className="text-[10px] text-text-secondary">
                  {slice.label} {slice.pct}%
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </BentoCard>
  );
}

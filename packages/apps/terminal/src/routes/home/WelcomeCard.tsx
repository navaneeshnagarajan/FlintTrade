/**
 * WelcomeCard — Hero card (wide). Greeting + daily P&L + regime + position count.
 */

import { useCurrentTradingState } from "@/stores/tradingStore";
import { usePositions } from "@/hooks/usePositions";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { getDemoPositions } from "@/hooks/useModeData";
import { useModeStore } from "@/stores/modeStore";
import { cn } from "@/lib/utils";
import { BentoCard } from "@/components/bento/BentoCard";
import { DemoBadge } from "./DemoBadge";
import { ExampleLabel } from "@/components/data/ExampleLabel";
import { getIstGreeting } from "./getIstGreeting";
import { useOperatorGreetingName } from "./operatorGreetingName";

export function WelcomeCard() {
  const name = useOperatorGreetingName();
  const isExplore = useModeStore((s) => s.mode === "explore");
  const accountReadsEnabled = useAccountReadsEnabled();
  const aggregate = useCurrentTradingState();
  const query = usePositions({ enabled: accountReadsEnabled });

  // Demo mode: simulated positions + a P&L derived from them (the trading-store
  // mirror isn't fed in explore).
  const positions = isExplore ? getDemoPositions() : query.data;
  const openPositions = positions?.filter((p) => p.quantity !== 0) ?? [];
  const positionCount = openPositions.length;
  const totalPnl = isExplore
    ? openPositions.reduce((sum, p) => sum + p.pnl, 0)
    : aggregate.totalPnl;
  const hasAggregate = isExplore || aggregate.positionsStatus === "ready" || aggregate.positionsStatus === "stale";

  const pnlPositive = totalPnl >= 0;

  return (
    <BentoCard size="wide" label="Welcome" data-testid="welcome-card">
      {isExplore && <DemoBadge />}
      <div className="p-5 h-full flex flex-col justify-between gap-4">
        <div>
          <p className="text-[12px] font-medium uppercase tracking-widest text-text-muted mb-1">
            Dashboard
          </p>
          <h2 className="font-heading text-xl font-semibold text-text-primary">
            {getIstGreeting()}{name ? `, ${name}` : ""}
          </h2>
        </div>

        <div className="flex items-end justify-between gap-4">
          {/* Daily P&L */}
          <div>
            <p className="text-[12px] uppercase tracking-wider text-text-muted mb-0.5">
              {isExplore || accountReadsEnabled ? "Today's P&L" : "Broker required"}
            </p>
            <p
              className={cn("font-mono text-2xl font-semibold", !hasAggregate ? "text-text-muted" : pnlPositive ? "text-bullish-text" : "text-bearish-text")}
            >
              {hasAggregate ? `${pnlPositive ? "+" : ""}${totalPnl.toLocaleString("en-IN", {
                style: "currency",
                currency: "INR",
                maximumFractionDigits: 0,
              })}` : "—"}
            </p>
            {!isExplore && aggregate.positionsStatus !== "ready" && (
              <p role="status" className="text-xs text-text-muted">
                {aggregate.positionsStatus === "loading" ? "Loading positions" : aggregate.positionsStatus === "stale" ? "Positions stale — last known P&L" : "Positions unavailable"}
              </p>
            )}
          </div>

          {/* Position count */}
          <div className="text-right">
            <p className="text-[12px] uppercase tracking-wider text-text-muted mb-0.5">
              Open Positions
            </p>
            <p className="font-mono text-2xl font-semibold text-text-primary">
              {hasAggregate ? positionCount : "—"}
            </p>
          </div>

          {/* Regime badge */}
          <div className="text-right">
            <p className="text-[12px] uppercase tracking-wider text-text-muted mb-0.5 flex items-center justify-end gap-1.5">
              Regime
              <ExampleLabel testId="welcome-regime-example" />
            </p>
            <span className="inline-block px-2 py-0.5 rounded-full text-[12px] font-medium bg-neutral-bg text-text-primary border border-neutral-border">
              Neutral
            </span>
          </div>
        </div>
      </div>
    </BentoCard>
  );
}

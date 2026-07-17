/**
 * WelcomeCard — Hero card (wide). Greeting + daily P&L + regime + position count.
 */

import { useSettingsStore } from "@/stores/settingsStore";
import { useTradingStore } from "@/stores/tradingStore";
import { usePositions } from "@/hooks/usePositions";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { getDemoPositions } from "@/hooks/useModeData";
import { useModeStore } from "@/stores/modeStore";
import { BentoCard } from "@/components/bento/BentoCard";
import { DemoBadge } from "./DemoBadge";

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export function WelcomeCard() {
  const name = useSettingsStore((s) => s.name);
  const isExplore = useModeStore((s) => s.mode === "explore");
  const accountReadsEnabled = useAccountReadsEnabled();
  const storePnl = useTradingStore((s) => s.totalPnl);
  const query = usePositions({ enabled: accountReadsEnabled });

  // Demo mode: simulated positions + a P&L derived from them (the trading-store
  // mirror isn't fed in explore).
  const positions = isExplore ? getDemoPositions() : query.data;
  const openPositions = positions?.filter((p) => p.quantity !== 0) ?? [];
  const positionCount = openPositions.length;
  const totalPnl = isExplore
    ? openPositions.reduce((sum, p) => sum + p.pnl, 0)
    : accountReadsEnabled ? storePnl : 0;

  const pnlPositive = totalPnl >= 0;

  return (
    <BentoCard size="wide" label="Welcome" data-testid="welcome-card">
      {isExplore && <DemoBadge />}
      <div className="p-5 h-full flex flex-col justify-between gap-4">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted mb-1">
            Dashboard
          </p>
          <h2 className="font-heading text-xl font-semibold text-text-primary">
            {getGreeting()}{name ? `, ${name}` : ""}
          </h2>
        </div>

        <div className="flex items-end justify-between gap-4">
          {/* Daily P&L */}
          <div>
            <p className="text-[10px] uppercase tracking-wider text-text-muted mb-0.5">
              {isExplore || accountReadsEnabled ? "Today's P&L" : "Broker required"}
            </p>
            <p
              className="font-mono text-2xl font-semibold"
              style={{ color: pnlPositive ? "var(--color-bullish-text)" : "var(--color-bearish-text)" }}
            >
              {pnlPositive ? "+" : ""}
              {totalPnl.toLocaleString("en-IN", {
                style: "currency",
                currency: "INR",
                maximumFractionDigits: 0,
              })}
            </p>
          </div>

          {/* Position count */}
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-wider text-text-muted mb-0.5">
              Open Positions
            </p>
            <p className="font-mono text-2xl font-semibold text-text-primary">
              {positionCount}
            </p>
          </div>

          {/* Regime badge */}
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-wider text-text-muted mb-0.5">
              Regime
            </p>
            <span className="inline-block px-2 py-0.5 rounded-full text-[11px] font-medium bg-neutral-bg text-text-primary border border-neutral-border">
              Neutral
            </span>
          </div>
        </div>
      </div>
    </BentoCard>
  );
}

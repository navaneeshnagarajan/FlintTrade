/**
 * WelcomeCard — Hero card (wide). Greeting + daily P&L + regime + position count.
 */

import { useSettingsStore } from "@/stores/settingsStore";
import { useTradingStore } from "@/stores/tradingStore";
import { usePositions } from "@/hooks/usePositions";
import { BentoCard } from "@/components/bento/BentoCard";

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export function WelcomeCard() {
  const name = useSettingsStore((s) => s.name);
  const totalPnl = useTradingStore((s) => s.totalPnl);
  const { data: positions } = usePositions();
  const positionCount = positions?.filter((p) => p.quantity !== 0).length ?? 0;

  const pnlPositive = totalPnl >= 0;

  return (
    <BentoCard size="wide" label="Welcome" data-testid="welcome-card">
      <div className="p-5 h-full flex flex-col justify-between gap-4">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-widest text-[#505068] mb-1">
            Dashboard
          </p>
          <h2 className="font-heading text-xl font-semibold text-[#e8e8f0]">
            {getGreeting()}{name ? `, ${name}` : ""}
          </h2>
        </div>

        <div className="flex items-end justify-between gap-4">
          {/* Daily P&L */}
          <div>
            <p className="text-[10px] uppercase tracking-wider text-[#505068] mb-0.5">
              Today&apos;s P&amp;L
            </p>
            <p
              className="font-mono text-2xl font-semibold"
              style={{ color: pnlPositive ? "#22c55e" : "#ef4444" }}
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
            <p className="text-[10px] uppercase tracking-wider text-[#505068] mb-0.5">
              Open Positions
            </p>
            <p className="font-mono text-2xl font-semibold text-[#e8e8f0]">
              {positionCount}
            </p>
          </div>

          {/* Regime badge */}
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-wider text-[#505068] mb-0.5">
              Regime
            </p>
            <span className="inline-block px-2 py-0.5 rounded-full text-[11px] font-medium bg-[rgba(59,130,246,0.15)] text-[#3b82f6] border border-[rgba(59,130,246,0.25)]">
              Neutral
            </span>
          </div>
        </div>
      </div>
    </BentoCard>
  );
}

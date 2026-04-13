/**
 * PositionsCard — Live positions from usePositions hook, P&L per position, net total.
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { usePositions } from "@/hooks/usePositions";
import { useTradingStore } from "@/stores/tradingStore";
import { Loader2 } from "lucide-react";

export function PositionsCard() {
  const { data: positions, isLoading } = usePositions();
  const totalPnl = useTradingStore((s) => s.totalPnl);

  const openPositions = positions?.filter((p) => p.quantity !== 0) ?? [];
  const totalPnlPositive = totalPnl >= 0;

  return (
    <BentoCard size="tall" label="Open Positions" data-testid="positions-card">
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-medium uppercase tracking-widest text-[#505068]">
            Positions
          </p>
          <span
            className="font-mono text-sm font-semibold"
            style={{ color: totalPnlPositive ? "#22c55e" : "#ef4444" }}
          >
            {totalPnlPositive ? "+" : ""}
            {totalPnl.toLocaleString("en-IN", {
              style: "currency",
              currency: "INR",
              maximumFractionDigits: 0,
            })}
          </span>
        </div>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 size={16} className="animate-spin text-[#505068]" aria-label="Loading positions" />
          </div>
        ) : openPositions.length === 0 ? (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-xs text-[#505068]">No open positions</p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto space-y-1" style={{ scrollbarWidth: "none" }}>
            {openPositions.map((pos) => {
              const pnlPositive = pos.pnl >= 0;
              return (
                <div
                  key={`${pos.symbol}-${pos.exchange}`}
                  className="flex items-center justify-between py-1.5 px-2 rounded-[8px]"
                  style={{ background: "var(--glass-l2-bg, rgba(255,255,255,0.03))" }}
                >
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-[#e8e8f0] truncate">{pos.symbol}</p>
                    <p className="text-[10px] text-[#505068]">
                      {pos.quantity > 0 ? "LONG" : "SHORT"} · {Math.abs(pos.quantity)}
                    </p>
                  </div>
                  <div className="text-right shrink-0 ml-2">
                    <p
                      className="font-mono text-xs font-semibold"
                      style={{ color: pnlPositive ? "#22c55e" : "#ef4444" }}
                    >
                      {pnlPositive ? "+" : ""}
                      {pos.pnl.toLocaleString("en-IN", {
                        style: "currency",
                        currency: "INR",
                        maximumFractionDigits: 0,
                      })}
                    </p>
                    <p
                      className="font-mono text-[10px]"
                      style={{ color: pnlPositive ? "#22c55e" : "#ef4444" }}
                    >
                      {pnlPositive ? "+" : ""}{pos.pnlPercent.toFixed(2)}%
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </BentoCard>
  );
}

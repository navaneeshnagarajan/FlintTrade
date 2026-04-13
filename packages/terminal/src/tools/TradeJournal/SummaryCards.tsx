import { Activity, TrendingUp, TrendingDown, Trophy } from "lucide-react";
import { formatCurrencyCompact } from "@/lib/formatters";
import { type TradeAnalytics } from "@/lib/journalAnalytics";
import { StatCard } from "./StatCard";

export function SummaryCards({ analytics }: { analytics: TradeAnalytics }) {
  const { totalTrades, wins, losses, netPnl, winRate, bestTrade, worstTrade } = analytics;

  return (
    <div className="grid grid-cols-5 gap-2 px-3 pt-2 pb-1 shrink-0">
      <StatCard
        label="Total Trades"
        value={String(totalTrades)}
        sub={`${wins + losses} closed`}
        icon={<Activity size={13} />}
      />
      <StatCard
        label="Net P&L"
        value={formatCurrencyCompact(netPnl)}
        positive={netPnl >= 0}
        icon={
          netPnl >= 0 ? <TrendingUp size={13} /> : <TrendingDown size={13} />
        }
      />
      <StatCard
        label="Win Rate"
        value={`${winRate.toFixed(1)}%`}
        sub={`${wins}W / ${losses}L`}
        positive={winRate >= 50}
      />
      <StatCard
        label="Best Trade"
        value={formatCurrencyCompact(bestTrade)}
        positive={bestTrade > 0}
        icon={<Trophy size={13} />}
      />
      <StatCard
        label="Worst Trade"
        value={formatCurrencyCompact(worstTrade)}
        positive={worstTrade >= 0}
      />
    </div>
  );
}

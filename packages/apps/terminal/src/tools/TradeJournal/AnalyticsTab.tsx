import { useMemo } from "react";
import { BarChart2, Trophy } from "lucide-react";
import { FlintRankedBarList, FlintSignedCategoricalBarChart } from "@flinttrade/design-system";
import { formatCurrencyCompact } from "@/lib/formatters";
import { computeAnalytics } from "@/lib/journalAnalytics";
import { type JournalTrade } from "@/services/ftApi";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { StatCard } from "./StatCard";

export function AnalyticsTab({ trades }: { trades: JournalTrade[] }) {
  const a = useMemo(() => computeAnalytics(trades), [trades]);

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
        <BarChart2 size={40} />
        <p className="text-sm">No trade data for analytics</p>
      </div>
    );
  }

  const dayOfWeekEntries = a.byDayOfWeek.map(({ day, pnl }) => ({
    label: day,
    value: pnl,
    color: pnl >= 0 ? "var(--color-profit, #22c55e)" : "var(--color-loss, #ef4444)",
  }));
  const symbolPnlEntries = a.bySymbol.map(({ symbol, pnl }) => ({
    label: symbol,
    value: pnl,
    color: pnl >= 0 ? "var(--color-profit, #22c55e)" : "var(--color-loss, #ef4444)",
  }));

  return (
    <ScrollArea className="flex-1 px-3 py-2">
      <div className="space-y-3">
        {/* KPI cards */}
        <div className="grid grid-cols-4 gap-2">
          <StatCard
            label="Net P&L"
            value={formatCurrencyCompact(a.netPnl)}
            positive={a.netPnl >= 0}
          />
          <StatCard
            label="Win Rate"
            value={`${a.winRate.toFixed(1)}%`}
            sub={`${a.wins}W / ${a.losses}L`}
            positive={a.winRate >= 50}
          />
          <StatCard
            label="Profit Factor"
            value={
              isFinite(a.profitFactor) ? a.profitFactor.toFixed(2) : "∞"
            }
            positive={a.profitFactor >= 1}
          />
          <StatCard label="Trades" value={String(a.totalTrades)} />
        </div>

        <div className="grid grid-cols-4 gap-2">
          <StatCard label="Avg Win" value={formatCurrencyCompact(a.avgWin)} positive={true} />
          <StatCard
            label="Avg Loss"
            value={formatCurrencyCompact(a.avgLoss)}
            positive={false}
          />
          <StatCard
            label="Best Trade"
            value={formatCurrencyCompact(a.bestTrade)}
            positive={true}
          />
          <StatCard
            label="Worst Trade"
            value={formatCurrencyCompact(a.worstTrade)}
            positive={false}
          />
        </div>

        {/* Streak */}
        {a.streakType !== "none" && (
          <Card className="bg-surface-card border-border-default">
            <CardContent className="p-3 flex items-center gap-2">
              <Trophy
                size={14}
                className={
                  a.streakType === "win" ? "text-profit" : "text-loss"
                }
              />
              <span className="text-xs text-text-secondary">
                Current streak:
              </span>
              <span
                className={`text-sm font-bold font-mono ${
                  a.streakType === "win" ? "text-profit" : "text-loss"
                }`}
              >
                {a.currentStreak} {a.streakType === "win" ? "wins" : "losses"}
              </span>
            </CardContent>
          </Card>
        )}

        {/* P&L by Day of Week */}
        <Card className="bg-surface-card border-border-default">
          <CardHeader className="p-3 pb-1">
            <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
              P&L by Day of Week
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-1">
            <FlintSignedCategoricalBarChart
              ariaLabel="Trade journal P&L by day of week"
              entries={dayOfWeekEntries}
              valueFormatter={formatCurrencyCompact}
              className="text-text-primary"
            />
            <div className="mt-2 grid grid-cols-5 gap-1 text-center">
              {a.byDayOfWeek.map(({ day, count }) => (
                <div key={day} className="text-xxs text-text-muted">
                  {count}t
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* P&L by Symbol */}
        {a.bySymbol.length > 0 && (
          <Card className="bg-surface-card border-border-default">
            <CardHeader className="p-3 pb-1">
              <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
                P&L by Symbol
              </CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-1">
              <FlintRankedBarList
                ariaLabel="Trade journal P&L by symbol"
                entries={symbolPnlEntries}
                valueFormatter={formatCurrencyCompact}
              />
              <div className="mt-2 space-y-1">
                {a.bySymbol.map(({ symbol, trades }) => (
                  <div key={symbol} className="flex justify-between gap-2 text-xs text-text-muted">
                    <span className="truncate font-mono text-text-secondary">{symbol}</span>
                    <span className="shrink-0">{trades}t</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </ScrollArea>
  );
}

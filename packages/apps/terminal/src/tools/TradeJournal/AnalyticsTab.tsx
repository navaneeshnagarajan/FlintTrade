import { useMemo } from "react";
import { BarChart2, Trophy } from "lucide-react";
import { formatCurrencyCompact } from "@/lib/formatters";
import { computeAnalytics } from "@/lib/journalAnalytics";
import { type JournalTrade } from "@/services/ftApi";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { StatCard } from "./StatCard";
import { pnlColor } from "./utils";

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

  const maxDowAbs = Math.max(...a.byDayOfWeek.map((d) => Math.abs(d.pnl)), 1);
  const maxSymAbs = Math.max(...a.bySymbol.map((s) => Math.abs(s.pnl)), 1);

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
            <div className="flex items-end gap-2 h-16">
              {a.byDayOfWeek.map(({ day, pnl, count }) => {
                const h = maxDowAbs > 0 ? Math.abs(pnl) / maxDowAbs : 0;
                return (
                  <div key={day} className="flex flex-col items-center gap-1 flex-1">
                    <div
                      className="w-full flex items-end justify-center"
                      style={{ height: "44px" }}
                    >
                      <div
                        className={`w-full rounded-sm transition-[height] ${
                          pnl >= 0 ? "bg-emerald-600/60" : "bg-red-600/60"
                        }`}
                        style={{ height: `${Math.max(2, h * 44)}px` }}
                        title={`${day}: ${formatCurrencyCompact(pnl)} (${count} trades)`}
                      />
                    </div>
                    <span className="text-xxs text-text-muted">{day}</span>
                  </div>
                );
              })}
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
            <CardContent className="p-3 pt-1 space-y-1.5">
              {a.bySymbol.map(({ symbol, pnl, trades }) => {
                const w =
                  maxSymAbs > 0 ? (Math.abs(pnl) / maxSymAbs) * 100 : 0;
                return (
                  <div key={symbol} className="flex items-center gap-2">
                    <span className="text-xs font-mono text-text-primary w-24 shrink-0 truncate">
                      {symbol}
                    </span>
                    <div className="flex-1 h-4 bg-surface-base rounded overflow-hidden">
                      <div
                        className={`h-full rounded transition-[width] ${
                          pnl >= 0 ? "bg-emerald-700/60" : "bg-red-700/60"
                        }`}
                        style={{ width: `${w}%` }}
                      />
                    </div>
                    <span
                      className={`text-xs font-mono w-20 text-right shrink-0 ${pnlColor(pnl)}`}
                    >
                      {formatCurrencyCompact(pnl)}
                    </span>
                    <span className="text-xs text-text-muted w-14 text-right shrink-0">
                      {trades}t
                    </span>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        )}
      </div>
    </ScrollArea>
  );
}

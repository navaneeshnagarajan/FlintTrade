import { useState, useMemo } from "react";
import { Target, Activity, Clock, Flame, Calendar } from "lucide-react";
import { formatCurrencyCompact } from "@/lib/formatters";
import {
  computeWeeklyWinRate,
  computeMonthlyWinRate,
  computeAvgPnlPerTrade,
  computeDayPnl,
  getBestDays,
  getWorstDays,
  computeInstrumentPnl,
  computeHoldingTime,
  computeAllStreaks,
  getLongestWinStreak,
  getLongestLossStreak,
  computeRiskRewardDistribution,
} from "@/lib/journalAnalytics";
import { type JournalTrade } from "@/services/ftApi";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { StatCard } from "./StatCard";
import { pnlColor, formatMinutes } from "./utils";

export function DeepAnalyticsTab({ trades }: { trades: JournalTrade[] }) {
  const [winRatePeriod, setWinRatePeriod] = useState<"weekly" | "monthly">("weekly");

  const weeklyWR = useMemo(() => computeWeeklyWinRate(trades), [trades]);
  const monthlyWR = useMemo(() => computeMonthlyWinRate(trades), [trades]);
  const avgPnl = useMemo(() => computeAvgPnlPerTrade(trades), [trades]);
  const dayPnls = useMemo(() => computeDayPnl(trades), [trades]);
  const bestDays = useMemo(() => getBestDays(dayPnls, 5), [dayPnls]);
  const worstDays = useMemo(() => getWorstDays(dayPnls, 5), [dayPnls]);
  const instruments = useMemo(() => computeInstrumentPnl(trades), [trades]);
  const holdingTime = useMemo(() => computeHoldingTime(trades), [trades]);
  const allStreaks = useMemo(() => computeAllStreaks(trades), [trades]);
  const longestWin = useMemo(() => getLongestWinStreak(allStreaks), [allStreaks]);
  const longestLoss = useMemo(() => getLongestLossStreak(allStreaks), [allStreaks]);
  const rrBuckets = useMemo(() => computeRiskRewardDistribution(trades), [trades]);

  const winRateData = winRatePeriod === "weekly" ? weeklyWR : monthlyWR;

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
        <Target size={40} />
        <p className="text-sm">No trade data for deep analytics</p>
      </div>
    );
  }

  const maxRR = Math.max(...rrBuckets.map((b) => b.count), 1);
  const topInstruments = instruments.slice(0, 8);
  const maxInstrPnl = Math.max(...topInstruments.map((i) => Math.abs(i.pnl)), 1);

  return (
    <ScrollArea className="flex-1 px-3 py-2">
      <div className="space-y-3">
        {/* Summary row */}
        <div className="grid grid-cols-4 gap-2">
          <StatCard
            label="Avg P&L / Trade"
            value={formatCurrencyCompact(avgPnl)}
            positive={avgPnl >= 0}
            icon={<Activity size={13} />}
          />
          <StatCard
            label="Avg Hold Time"
            value={holdingTime.avgMinutes > 0 ? formatMinutes(holdingTime.avgMinutes) : "N/A"}
            sub={holdingTime.medianMinutes > 0 ? `Median: ${formatMinutes(holdingTime.medianMinutes)}` : undefined}
            icon={<Clock size={13} />}
          />
          <StatCard
            label="Best Win Streak"
            value={String(longestWin)}
            sub={`Longest loss: ${longestLoss}`}
            positive={longestWin > longestLoss}
            icon={<Flame size={13} />}
          />
          <StatCard
            label="Trading Days"
            value={String(dayPnls.length)}
            sub={`${dayPnls.filter((d) => d.pnl > 0).length} green / ${dayPnls.filter((d) => d.pnl <= 0).length} red`}
            icon={<Calendar size={13} />}
          />
        </div>

        {/* Win Rate Over Time */}
        <Card className="bg-surface-card border-border-default">
          <CardHeader className="p-3 pb-1">
            <div className="flex items-center justify-between">
              <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
                Win Rate Over Time
              </CardTitle>
              <div className="flex gap-1">
                {(["weekly", "monthly"] as const).map((p) => (
                  <Button
                    key={p}
                    variant="ghost"
                    size="sm"
                    className={`h-5 px-2 text-xxs ${
                      winRatePeriod === p
                        ? "bg-surface-elevated text-text-primary"
                        : "text-text-muted hover:text-text-primary"
                    }`}
                    onClick={() => setWinRatePeriod(p)}
                  >
                    {p === "weekly" ? "Weekly" : "Monthly"}
                  </Button>
                ))}
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-3 pt-1">
            {winRateData.length === 0 ? (
              <p className="text-xs text-text-muted text-center py-4">No data for this period</p>
            ) : (
              <div className="space-y-1">
                {winRateData.map((d) => {
                  const label = winRatePeriod === "weekly"
                    ? (d as { week: string }).week
                    : (d as { month: string }).month;
                  const wr = d.winRate;
                  return (
                    <div key={label} className="flex items-center gap-2">
                      <span className="text-xxs font-mono text-text-muted w-16 shrink-0">
                        {label}
                      </span>
                      <div className="flex-1 h-3 bg-surface-base rounded overflow-hidden">
                        <div
                          className={`h-full rounded transition-[width] ${wr >= 50 ? "bg-emerald-600/60" : "bg-red-600/60"}`}
                          style={{ width: `${Math.min(100, wr)}%` }}
                        />
                      </div>
                      <span className={`text-xxs font-mono w-12 text-right shrink-0 ${wr >= 50 ? "text-profit" : "text-loss"}`}>
                        {wr.toFixed(0)}%
                      </span>
                      <span className="text-xxs text-text-muted w-14 text-right shrink-0">
                        {d.wins}W/{d.losses}L
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Best / Worst Trading Days */}
        <div className="grid grid-cols-2 gap-2">
          <Card className="bg-surface-card border-border-default">
            <CardHeader className="p-3 pb-1">
              <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
                Best Days
              </CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-1 space-y-1">
              {bestDays.map((d) => (
                <div key={d.date} className="flex items-center justify-between">
                  <span className="text-xxs font-mono text-text-muted">{d.date}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xxs text-text-muted">{d.tradeCount}t</span>
                    <span className="text-xs font-mono text-profit font-medium">
                      {formatCurrencyCompact(d.pnl)}
                    </span>
                  </div>
                </div>
              ))}
              {bestDays.length === 0 && (
                <p className="text-xxs text-text-muted text-center py-2">No data</p>
              )}
            </CardContent>
          </Card>

          <Card className="bg-surface-card border-border-default">
            <CardHeader className="p-3 pb-1">
              <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
                Worst Days
              </CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-1 space-y-1">
              {worstDays.map((d) => (
                <div key={d.date} className="flex items-center justify-between">
                  <span className="text-xxs font-mono text-text-muted">{d.date}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xxs text-text-muted">{d.tradeCount}t</span>
                    <span className="text-xs font-mono text-loss font-medium">
                      {formatCurrencyCompact(d.pnl)}
                    </span>
                  </div>
                </div>
              ))}
              {worstDays.length === 0 && (
                <p className="text-xxs text-text-muted text-center py-2">No data</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Most Profitable Instruments */}
        <Card className="bg-surface-card border-border-default">
          <CardHeader className="p-3 pb-1">
            <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
              Instrument Performance
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-1 space-y-1.5">
            {topInstruments.map(({ symbol, pnl, trades: tradeCount }) => {
              const w = maxInstrPnl > 0 ? (Math.abs(pnl) / maxInstrPnl) * 100 : 0;
              return (
                <div key={symbol} className="flex items-center gap-2">
                  <span className="text-xs font-mono text-text-primary w-24 shrink-0 truncate">
                    {symbol}
                  </span>
                  <div className="flex-1 h-4 bg-surface-base rounded overflow-hidden">
                    <div
                      className={`h-full rounded transition-[width] ${pnl >= 0 ? "bg-emerald-700/60" : "bg-red-700/60"}`}
                      style={{ width: `${w}%` }}
                    />
                  </div>
                  <span className={`text-xs font-mono w-20 text-right shrink-0 ${pnlColor(pnl)}`}>
                    {formatCurrencyCompact(pnl)}
                  </span>
                  <span className="text-xs text-text-muted w-10 text-right shrink-0">
                    {tradeCount}t
                  </span>
                </div>
              );
            })}
            {topInstruments.length === 0 && (
              <p className="text-xs text-text-muted text-center py-2">No data</p>
            )}
          </CardContent>
        </Card>

        {/* Streak History */}
        <Card className="bg-surface-card border-border-default">
          <CardHeader className="p-3 pb-1">
            <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
              Streak History
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-1">
            <div className="flex items-center gap-1 flex-wrap">
              {allStreaks.map((s, i) => (
                <div
                  key={i}
                  className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xxs font-mono ${
                    s.type === "win"
                      ? "bg-emerald-900/30 text-profit"
                      : "bg-red-900/30 text-loss"
                  }`}
                  title={`${s.length} ${s.type === "win" ? "wins" : "losses"} in a row`}
                >
                  {s.type === "win" ? "W" : "L"}{s.length}
                </div>
              ))}
              {allStreaks.length === 0 && (
                <p className="text-xxs text-text-muted">No streaks to display</p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Risk-Reward Distribution */}
        {rrBuckets.length > 0 && (
          <Card className="bg-surface-card border-border-default">
            <CardHeader className="p-3 pb-1">
              <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
                Risk-Reward Distribution
              </CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-1">
              <div className="flex items-end gap-2 h-20">
                {rrBuckets.map(({ label, count }) => {
                  const h = maxRR > 0 ? count / maxRR : 0;
                  return (
                    <div key={label} className="flex flex-col items-center gap-1 flex-1">
                      <div
                        className="w-full flex items-end justify-center"
                        style={{ height: "56px" }}
                      >
                        <div
                          className="w-full rounded-sm bg-accent/40 transition-[height]"
                          style={{ height: `${Math.max(2, h * 56)}px` }}
                          title={`${label}: ${count} trades`}
                        />
                      </div>
                      <span className="text-xxs text-text-muted">{label}</span>
                      <span className="text-xxs font-mono text-text-secondary">{count}</span>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Holding Time Details */}
        {holdingTime.avgMinutes > 0 && (
          <Card className="bg-surface-card border-border-default">
            <CardHeader className="p-3 pb-1">
              <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
                Holding Time
              </CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-1">
              <div className="grid grid-cols-4 gap-x-4 gap-y-1">
                <div className="flex justify-between items-center">
                  <span className="text-xs text-text-muted">Average</span>
                  <span className="text-xs font-mono text-text-primary">{formatMinutes(holdingTime.avgMinutes)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-text-muted">Median</span>
                  <span className="text-xs font-mono text-text-primary">{formatMinutes(holdingTime.medianMinutes)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-text-muted">Fastest</span>
                  <span className="text-xs font-mono text-text-primary">{formatMinutes(holdingTime.minMinutes)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-text-muted">Longest</span>
                  <span className="text-xs font-mono text-text-primary">{formatMinutes(holdingTime.maxMinutes)}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </ScrollArea>
  );
}

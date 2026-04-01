// Absorbed patterns from:
//   trading-journal/frontend/app/dashboard/portfolios/[id]/page.tsx — TradesTable, win/loss stat cards
//   trading-journal/frontend/app/dashboard/analytics/page.tsx — analytics metrics, formatINR pattern

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { formatCurrencyCompact } from "@/lib/formatters";
import {
  computeAnalytics,
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
  type TradeAnalytics,
} from "@/lib/journalAnalytics";
import {
  BookOpen,
  X,
  Search,
  BarChart2,
  FileText,
  Trophy,
  AlertCircle,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Activity,
  Brain,
  Loader2,
  Clock,
  Target,
  Flame,
  Calendar,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { getTradeJournal, type JournalTrade } from "@/services/ftApi";

interface Props {
  onClose?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPrice(value: number): string {
  return value.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatDate(ts: string): string {
  if (!ts) return "-";
  try {
    const d = new Date(ts);
    return d.toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "2-digit",
    });
  } catch {
    return ts;
  }
}

function formatTime(ts: string): string {
  if (!ts) return "-";
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

function pnlColor(value: number): string {
  if (value > 0) return "text-profit";
  if (value < 0) return "text-loss";
  return "text-text-secondary";
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function sevenDaysAgoISO(): string {
  const d = new Date();
  d.setDate(d.getDate() - 6);
  return d.toISOString().slice(0, 10);
}

// Analytics functions extracted to @/lib/journalAnalytics for testability

const NOTES_KEY = "flinttrade_journal_notes";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  sub,
  positive,
  icon,
}: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <Card className="bg-surface-card border-border-default">
      <CardContent className="p-3">
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-text-secondary uppercase tracking-wider">
            {label}
          </div>
          {icon && (
            <div className="text-text-muted opacity-60">{icon}</div>
          )}
        </div>
        <div
          className={`text-lg font-bold font-mono tabular-nums ${
            positive === undefined
              ? "text-text-primary"
              : positive
                ? "text-profit"
                : "text-loss"
          }`}
        >
          {value}
        </div>
        {sub && (
          <div className="text-xs text-text-muted mt-0.5">{sub}</div>
        )}
      </CardContent>
    </Card>
  );
}

function SkeletonRows({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <TableRow key={i} className="border-border-subtle">
          {Array.from({ length: 10 }).map((_, j) => (
            <TableCell key={j} className="py-1.5">
              <Skeleton className="h-3 w-full bg-surface-elevated" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Summary Cards
// ---------------------------------------------------------------------------

function SummaryCards({ analytics }: { analytics: TradeAnalytics }) {
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

// ---------------------------------------------------------------------------
// Trade Log Tab
// ---------------------------------------------------------------------------

function TradeLogTab({
  trades,
  analytics,
  isLoading,
  isError,
  onRetry,
}: {
  trades: JournalTrade[];
  analytics: TradeAnalytics;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  const [search, setSearch] = useState("");
  const [filterAction, setFilterAction] = useState<"ALL" | "BUY" | "SELL">(
    "ALL",
  );

  // Sort newest first
  const sorted = useMemo(
    () =>
      [...trades].sort(
        (a, b) =>
          new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
      ),
    [trades],
  );

  const filtered = useMemo(() => {
    return sorted.filter((t) => {
      const matchSearch =
        search === "" || t.symbol.toLowerCase().includes(search.toLowerCase());
      const matchAction =
        filterAction === "ALL" || t.action === filterAction;
      return matchSearch && matchAction;
    });
  }, [sorted, search, filterAction]);

  return (
    <div className="flex flex-col h-full gap-2">
      {/* Summary cards */}
      {!isLoading && !isError && trades.length > 0 && (
        <SummaryCards analytics={analytics} />
      )}

      {/* Filters */}
      <div className="flex items-center gap-2 px-3 shrink-0">
        <div className="relative flex-1 max-w-52">
          <Search
            size={13}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <Input
            className="pl-7 h-7 text-xs bg-surface-base border-border-default text-text-primary placeholder:text-text-muted"
            placeholder="Search symbol..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-1">
          {(["ALL", "BUY", "SELL"] as const).map((v) => (
            <Button
              key={v}
              variant="ghost"
              size="sm"
              className={`h-7 px-2 text-xs ${
                filterAction === v
                  ? "bg-surface-elevated text-text-primary"
                  : "text-text-muted hover:text-text-primary"
              }`}
              onClick={() => setFilterAction(v)}
            >
              {v}
            </Button>
          ))}
        </div>
        {!isLoading && !isError && (
          <span className="text-xs text-text-muted ml-auto">
            {filtered.length} trades
          </span>
        )}
      </div>

      {/* Table */}
      <ScrollArea className="flex-1 px-3 pb-2">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              <TableHead className="text-xs text-text-muted h-7 font-normal">
                Date / Time
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">
                Symbol
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">
                Exch
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">
                Side
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">
                Qty
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">
                Entry
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">
                Exit
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">
                P&L
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">
                Fees
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">
                Strategy
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && <SkeletonRows count={8} />}

            {isError && (
              <TableRow>
                <TableCell
                  colSpan={10}
                  className="text-center py-8 text-text-muted"
                >
                  <div className="flex flex-col items-center gap-2">
                    <AlertCircle size={20} className="text-loss" />
                    <span className="text-xs">Failed to load trade journal</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-xs h-6 text-text-muted hover:text-text-primary"
                      onClick={onRetry}
                    >
                      <RefreshCw size={11} className="mr-1" />
                      Retry
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            )}

            {!isLoading && !isError && filtered.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={10}
                  className="text-center py-8 text-text-muted"
                >
                  <div className="flex flex-col items-center gap-2">
                    <BookOpen size={24} />
                    <span className="text-xs">
                      No trades found for this period
                    </span>
                  </div>
                </TableCell>
              </TableRow>
            )}

            {!isLoading &&
              !isError &&
              filtered.map((trade, idx) => (
                <TableRow
                  key={`${trade.timestamp}-${trade.symbol}-${idx}`}
                  className="border-border-subtle hover:bg-surface-card"
                >
                  <TableCell className="py-1 text-xs text-text-secondary whitespace-nowrap">
                    <span>{formatDate(trade.timestamp)}</span>
                    <span className="ml-1 text-text-muted">
                      {formatTime(trade.timestamp)}
                    </span>
                  </TableCell>
                  <TableCell className="py-1 text-xs font-mono text-text-primary font-medium">
                    {trade.symbol}
                  </TableCell>
                  <TableCell className="py-1 text-xs text-text-muted">
                    {trade.exchange}
                  </TableCell>
                  <TableCell className="py-1">
                    <Badge
                      variant="outline"
                      className={`text-xxs px-1.5 py-0 border-0 font-medium ${
                        trade.action === "BUY"
                          ? "bg-bullish-bg text-profit"
                          : "bg-bearish-bg text-loss"
                      }`}
                    >
                      {trade.action}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-1 text-xs font-mono text-text-secondary text-right">
                    {trade.quantity}
                  </TableCell>
                  <TableCell className="py-1 text-xs font-mono text-text-primary text-right">
                    {formatPrice(trade.entry_price)}
                  </TableCell>
                  <TableCell className="py-1 text-xs font-mono text-text-primary text-right">
                    {trade.exit_price > 0 ? formatPrice(trade.exit_price) : "-"}
                  </TableCell>
                  <TableCell
                    className={`py-1 text-xs font-mono text-right font-medium ${pnlColor(trade.pnl)}`}
                  >
                    {trade.pnl !== 0 ? formatCurrencyCompact(trade.pnl) : "-"}
                  </TableCell>
                  <TableCell className="py-1 text-xs font-mono text-text-muted text-right">
                    {trade.fees > 0 ? formatPrice(trade.fees) : "-"}
                  </TableCell>
                  <TableCell className="py-1 text-xs text-text-muted max-w-24 truncate">
                    {trade.strategy || "-"}
                  </TableCell>
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </ScrollArea>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Analytics Tab
// ---------------------------------------------------------------------------

function AnalyticsTab({ trades }: { trades: JournalTrade[] }) {
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

// ---------------------------------------------------------------------------
// Deep Analytics Tab — enhanced analytics from persona research
// ---------------------------------------------------------------------------

function formatMinutes(mins: number): string {
  if (mins < 1) return "<1m";
  if (mins < 60) return `${Math.round(mins)}m`;
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function DeepAnalyticsTab({ trades }: { trades: JournalTrade[] }) {
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

// ---------------------------------------------------------------------------
// Coach Tab — behavioral layer
// ---------------------------------------------------------------------------

/** Discriminated union for tilt detection state. */
type TiltStatus =
  | { level: "calm"; reason: null }
  | { level: "warning"; reason: string }
  | { level: "tilted"; reason: string };

function detectTilt(trades: JournalTrade[]): TiltStatus {
  // Only evaluate closed trades (non-zero pnl), chronological order
  const closed = [...trades]
    .filter((t) => t.pnl !== 0)
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  // Inspect the most recent 5 closed trades
  const recent = closed.slice(-5);
  const recentLosses = recent.filter((t) => t.pnl < 0).length;

  if (recentLosses >= 4) {
    return { level: "tilted", reason: "4+ recent losses — consider pausing" };
  }
  if (recentLosses >= 3) {
    return { level: "warning", reason: "3 recent losses — watch your next trade carefully" };
  }
  return { level: "calm", reason: null };
}

function TiltBadge({ status }: { status: TiltStatus }) {
  if (status.level === "tilted") {
    return (
      <Badge className="bg-red-900/40 text-red-400 border-red-700/40 text-xs font-semibold">
        Tilt Detected
      </Badge>
    );
  }
  if (status.level === "warning") {
    return (
      <Badge className="bg-yellow-900/40 text-yellow-400 border-yellow-700/40 text-xs font-semibold">
        Caution
      </Badge>
    );
  }
  return (
    <Badge className="bg-emerald-900/40 text-emerald-400 border-emerald-700/40 text-xs font-semibold">
      Focused
    </Badge>
  );
}

function CoachTab({ trades }: { trades: JournalTrade[] }) {
  const [aiResponse, setAiResponse] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  const a = useMemo(() => computeAnalytics(trades), [trades]);
  const tilt = useMemo(() => detectTilt(trades), [trades]);

  const winRate = a.winRate.toFixed(1);
  const avgWin = a.avgWin.toFixed(0);
  const avgLoss = Math.abs(a.avgLoss).toFixed(0);
  const streak =
    a.streakType === "none"
      ? "No streak"
      : `${a.currentStreak} ${a.streakType === "win" ? "win" : "loss"} streak`;

  async function handleAiCoach() {
    setIsLoading(true);
    setAiError(null);
    setAiResponse(null);

    try {
      const base = import.meta.env.DEV ? "/ft-api" : "";
      const res = await fetch(`${base}/api/v1/advisor`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: `Analyze my recent trading behavior. Win rate: ${winRate}%, Average win: ₹${avgWin}, Average loss: ₹${avgLoss}, Current streak: ${streak}. What patterns do you see and what should I improve?`,
        }),
      });

      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { message?: string };
        setAiError(err.message ?? `Request failed (${res.status})`);
        return;
      }

      const data = (await res.json()) as { data?: { response?: string }; response?: string };
      const reply = data?.data?.response ?? data?.response ?? "";
      setAiResponse(reply || "No response from advisor.");
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "Network error");
    } finally {
      setIsLoading(false);
    }
  }

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
        <Brain size={40} />
        <p className="text-sm">No trade data for coaching</p>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1 px-3 py-2">
      <div className="space-y-3">
        {/* Tilt detection */}
        <Card className="bg-surface-card border-border-default">
          <CardHeader className="p-3 pb-1">
            <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
              Behavioral State
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-2 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted">Current state:</span>
              <TiltBadge status={tilt} />
            </div>
            {tilt.reason && (
              <p
                className={`text-xs ${tilt.level === "tilted" ? "text-red-400" : "text-yellow-400"}`}
                role="alert"
              >
                {tilt.reason}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Behavioral summary */}
        <Card className="bg-surface-card border-border-default">
          <CardHeader className="p-3 pb-1">
            <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
              Pattern Summary
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-1">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Win rate</span>
                <span
                  className={`text-xs font-mono font-semibold ${a.winRate >= 50 ? "text-profit" : "text-loss"}`}
                >
                  {winRate}%
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Streak</span>
                <span
                  className={`text-xs font-mono font-semibold ${
                    a.streakType === "win"
                      ? "text-profit"
                      : a.streakType === "loss"
                        ? "text-loss"
                        : "text-text-muted"
                  }`}
                >
                  {streak}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Avg win</span>
                <span className="text-xs font-mono text-profit">₹{avgWin}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Avg loss</span>
                <span className="text-xs font-mono text-loss">₹{avgLoss}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Profit factor</span>
                <span
                  className={`text-xs font-mono font-semibold ${a.profitFactor >= 1 ? "text-profit" : "text-loss"}`}
                >
                  {isFinite(a.profitFactor) ? a.profitFactor.toFixed(2) : "∞"}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-text-muted">Total trades</span>
                <span className="text-xs font-mono text-text-primary">{a.totalTrades}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* AI Coaching */}
        <Card className="bg-surface-card border-border-default">
          <CardHeader className="p-3 pb-1">
            <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
              AI Coaching
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-2 space-y-2">
            <Button
              size="sm"
              className="w-full h-8 text-xs gap-1.5"
              onClick={handleAiCoach}
              disabled={isLoading}
              aria-busy={isLoading}
            >
              {isLoading ? (
                <Loader2 size={12} className="animate-spin" aria-hidden="true" />
              ) : (
                <Brain size={12} aria-hidden="true" />
              )}
              {isLoading ? "Analyzing..." : "Request AI Coaching Analysis"}
            </Button>

            {aiError && (
              <div
                className="flex items-start gap-1.5 text-xs text-loss bg-red-900/10 border border-red-900/20 rounded p-2"
                role="alert"
              >
                <AlertCircle size={12} className="shrink-0 mt-0.5" />
                <span>{aiError}</span>
              </div>
            )}

            {aiResponse && (
              <div
                className="text-xs text-text-secondary leading-relaxed bg-surface-base rounded p-2.5 whitespace-pre-wrap"
                aria-live="polite"
              >
                {aiResponse}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Notes Tab
// ---------------------------------------------------------------------------

function NotesTab() {
  const today = new Date().toISOString().slice(0, 10);
  const key = `${NOTES_KEY}_${today}`;
  const [notes, setNotes] = useState(() => {
    try {
      return localStorage.getItem(key) ?? "";
    } catch {
      return "";
    }
  });

  const save = (val: string) => {
    setNotes(val);
    try {
      localStorage.setItem(key, val);
    } catch {
      // noop
    }
  };

  const wordCount = notes.trim() ? notes.trim().split(/\s+/).length : 0;

  return (
    <div className="flex flex-col gap-2 p-3 h-full">
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-muted">Daily notes — {today}</span>
        <span className="text-xs text-text-muted">
          {wordCount} words · auto-saved
        </span>
      </div>
      <Textarea
        className="flex-1 text-sm leading-relaxed"
        placeholder={
          "Write your trading notes for today...\n\n- Market observations\n- Strategy notes\n- Lessons learned\n- Plan for tomorrow"
        }
        value={notes}
        onChange={(e) => save(e.target.value)}
      />
      {notes && (
        <Button
          variant="ghost"
          size="sm"
          className="self-end text-xs text-text-muted hover:text-loss h-6"
          onClick={() => save("")}
        >
          Clear
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function TradeJournalTool({ onClose }: Props) {
  const [startDate, setStartDate] = useState(sevenDaysAgoISO);
  const [endDate, setEndDate] = useState(todayISO);
  const [strategy, setStrategy] = useState("");

  // Committed search state — only updates when user clicks Search
  const [queryStart, setQueryStart] = useState(sevenDaysAgoISO);
  const [queryEnd, setQueryEnd] = useState(todayISO);
  const [queryStrategy, setQueryStrategy] = useState("");

  const {
    data,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["tradeJournal", queryStart, queryEnd, queryStrategy],
    queryFn: () =>
      getTradeJournal(queryStart, queryEnd, queryStrategy || undefined, 200),
    enabled: !!queryStart,
  });

  const trades = data?.trades ?? [];
  const analytics = useMemo(() => computeAnalytics(trades), [trades]);

  function handleSearch() {
    setQueryStart(startDate);
    setQueryEnd(endDate);
    setQueryStrategy(strategy);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleSearch();
  }

  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border-default bg-surface-card shrink-0 flex-wrap">
        <div className="flex items-center gap-2 shrink-0">
          <BookOpen size={16} className="text-primary" />
          <h1 className="font-heading font-bold text-base text-text-primary">
            Trade Journal
          </h1>
        </div>

        {/* Date range + strategy filters */}
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <Input
            type="text"
            placeholder="YYYY-MM-DD"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            onKeyDown={handleKeyDown}
            className="h-7 text-xs w-28 bg-surface-base border-border-default text-text-primary placeholder:text-text-muted font-mono"
            aria-label="Start date"
          />
          <span className="text-text-muted text-xs shrink-0">to</span>
          <Input
            type="text"
            placeholder="YYYY-MM-DD"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            onKeyDown={handleKeyDown}
            className="h-7 text-xs w-28 bg-surface-base border-border-default text-text-primary placeholder:text-text-muted font-mono"
            aria-label="End date"
          />
          <Input
            type="text"
            placeholder="Strategy (optional)"
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            onKeyDown={handleKeyDown}
            className="h-7 text-xs w-36 bg-surface-base border-border-default text-text-primary placeholder:text-text-muted"
            aria-label="Strategy filter"
          />
          <Button
            size="sm"
            className="h-7 px-3 text-xs"
            onClick={handleSearch}
          >
            <Search size={11} className="mr-1" />
            Search
          </Button>
        </div>

        {/* Status badges */}
        <div className="flex items-center gap-2 shrink-0">
          {isLoading && (
            <span className="text-xs text-text-muted flex items-center gap-1">
              <RefreshCw size={11} className="animate-spin" />
              Loading...
            </span>
          )}
          {isError && (
            <span className="text-xs text-loss flex items-center gap-1">
              <AlertCircle size={11} />
              Error
            </span>
          )}
          {!isLoading && !isError && (
            <Badge
              variant="outline"
              className="text-xxs border-border-default text-text-muted font-normal"
            >
              {trades.length} trades
            </Badge>
          )}
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors"
            aria-label="Close trade journal"
          >
            <X size={15} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="log" className="flex-1 flex flex-col min-h-0">
        <TabsList className="shrink-0 rounded-none bg-surface-base border-b border-border-default justify-start px-3 h-8 gap-1">
          <TabsTrigger
            value="log"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <BookOpen size={11} className="mr-1" />
            Trade Log
          </TabsTrigger>
          <TabsTrigger
            value="analytics"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <BarChart2 size={11} className="mr-1" />
            Analytics
          </TabsTrigger>
          <TabsTrigger
            value="deep-analytics"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <Target size={11} className="mr-1" />
            Deep Analytics
          </TabsTrigger>
          <TabsTrigger
            value="notes"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <FileText size={11} className="mr-1" />
            Notes
          </TabsTrigger>
          <TabsTrigger
            value="coach"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <Brain size={11} className="mr-1" />
            Coach
          </TabsTrigger>
        </TabsList>

        <TabsContent
          value="log"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <TradeLogTab
            trades={trades}
            analytics={analytics}
            isLoading={isLoading}
            isError={isError}
            onRetry={() => refetch()}
          />
        </TabsContent>

        <TabsContent
          value="analytics"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <AnalyticsTab trades={trades} />
        </TabsContent>

        <TabsContent
          value="deep-analytics"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <DeepAnalyticsTab trades={trades} />
        </TabsContent>

        <TabsContent
          value="notes"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <NotesTab />
        </TabsContent>

        <TabsContent
          value="coach"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <CoachTab trades={trades} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

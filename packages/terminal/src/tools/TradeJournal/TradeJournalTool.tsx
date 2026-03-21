// Absorbed patterns from:
//   trading-journal/frontend/app/dashboard/portfolios/[id]/page.tsx — TradesTable, win/loss stat cards
//   trading-journal/frontend/app/dashboard/analytics/page.tsx — analytics metrics, formatINR pattern

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
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

function formatINR(value: number): string {
  const abs = Math.abs(value);
  let formatted: string;
  if (abs >= 10_000_000) {
    formatted = `${(abs / 10_000_000).toFixed(2)}Cr`;
  } else if (abs >= 100_000) {
    formatted = `${(abs / 100_000).toFixed(2)}L`;
  } else if (abs >= 1_000) {
    formatted = `${(abs / 1_000).toFixed(2)}K`;
  } else {
    formatted = abs.toFixed(2);
  }
  return `${value < 0 ? "-" : ""}₹${formatted}`;
}

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

// ---------------------------------------------------------------------------
// Analytics derived from JournalTrade[] (P&L is pre-computed by backend)
// ---------------------------------------------------------------------------

interface TradeAnalytics {
  totalTrades: number;
  netPnl: number;
  winRate: number;
  wins: number;
  losses: number;
  avgWin: number;
  avgLoss: number;
  profitFactor: number;
  bestTrade: number;
  worstTrade: number;
  byDayOfWeek: { day: string; pnl: number; count: number }[];
  bySymbol: { symbol: string; pnl: number; trades: number }[];
  currentStreak: number;
  streakType: "win" | "loss" | "none";
}

function computeAnalytics(trades: JournalTrade[]): TradeAnalytics {
  // Use pre-computed pnl from backend (only closed trades have non-zero pnl)
  const closed = trades.filter((t) => t.pnl !== 0);

  const wins = closed.filter((t) => t.pnl > 0);
  const losses = closed.filter((t) => t.pnl <= 0);
  const netPnl = closed.reduce((s, t) => s + t.pnl, 0);
  const avgWin = wins.length
    ? wins.reduce((s, t) => s + t.pnl, 0) / wins.length
    : 0;
  const avgLoss = losses.length
    ? losses.reduce((s, t) => s + t.pnl, 0) / losses.length
    : 0;
  const grossWin = wins.reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(losses.reduce((s, t) => s + t.pnl, 0));
  const profitFactor =
    grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0;
  const bestTrade = closed.length ? Math.max(...closed.map((t) => t.pnl)) : 0;
  const worstTrade = closed.length
    ? Math.min(...closed.map((t) => t.pnl))
    : 0;

  // By day of week
  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const dowMap: Record<string, { pnl: number; count: number }> = {};
  closed.forEach((t) => {
    try {
      const d = new Date(t.timestamp);
      const key = DOW[d.getDay()];
      if (!dowMap[key]) dowMap[key] = { pnl: 0, count: 0 };
      dowMap[key].pnl += t.pnl;
      dowMap[key].count += 1;
    } catch {
      // skip
    }
  });
  const byDayOfWeek = ["Mon", "Tue", "Wed", "Thu", "Fri"].map((day) => ({
    day,
    pnl: dowMap[day]?.pnl ?? 0,
    count: dowMap[day]?.count ?? 0,
  }));

  // By symbol
  const symMap: Record<string, { pnl: number; trades: number }> = {};
  closed.forEach((t) => {
    if (!symMap[t.symbol]) symMap[t.symbol] = { pnl: 0, trades: 0 };
    symMap[t.symbol].pnl += t.pnl;
    symMap[t.symbol].trades += 1;
  });
  const bySymbol = Object.entries(symMap)
    .map(([symbol, v]) => ({ symbol, ...v }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
    .slice(0, 10);

  // Streak (chronological order)
  const sorted = [...closed].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );
  let streak = 0;
  let streakType: "win" | "loss" | "none" = "none";
  if (sorted.length > 0) {
    const last = sorted[sorted.length - 1].pnl > 0 ? "win" : "loss";
    streakType = last;
    for (let i = sorted.length - 1; i >= 0; i--) {
      const cur = sorted[i].pnl > 0 ? "win" : "loss";
      if (cur !== last) break;
      streak++;
    }
  }

  return {
    totalTrades: closed.length,
    netPnl,
    winRate: closed.length ? (wins.length / closed.length) * 100 : 0,
    wins: wins.length,
    losses: losses.length,
    avgWin,
    avgLoss,
    profitFactor,
    bestTrade,
    worstTrade,
    byDayOfWeek,
    bySymbol,
    currentStreak: streak,
    streakType,
  };
}

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

function SummaryCards({ trades }: { trades: JournalTrade[] }) {
  const closed = trades.filter((t) => t.pnl !== 0);
  const netPnl = closed.reduce((s, t) => s + t.pnl, 0);
  const wins = closed.filter((t) => t.pnl > 0);
  const winRate = closed.length ? (wins.length / closed.length) * 100 : 0;
  const bestTrade = closed.length ? Math.max(...closed.map((t) => t.pnl)) : 0;
  const worstTrade = closed.length
    ? Math.min(...closed.map((t) => t.pnl))
    : 0;

  return (
    <div className="grid grid-cols-5 gap-2 px-3 pt-2 pb-1 shrink-0">
      <StatCard
        label="Total Trades"
        value={String(trades.length)}
        sub={`${closed.length} closed`}
        icon={<Activity size={13} />}
      />
      <StatCard
        label="Net P&L"
        value={formatINR(netPnl)}
        positive={netPnl >= 0}
        icon={
          netPnl >= 0 ? <TrendingUp size={13} /> : <TrendingDown size={13} />
        }
      />
      <StatCard
        label="Win Rate"
        value={`${winRate.toFixed(1)}%`}
        sub={`${wins.length}W / ${closed.length - wins.length}L`}
        positive={winRate >= 50}
      />
      <StatCard
        label="Best Trade"
        value={formatINR(bestTrade)}
        positive={bestTrade > 0}
        icon={<Trophy size={13} />}
      />
      <StatCard
        label="Worst Trade"
        value={formatINR(worstTrade)}
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
  isLoading,
  isError,
  onRetry,
}: {
  trades: JournalTrade[];
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
        <SummaryCards trades={trades} />
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
                    {trade.pnl !== 0 ? formatINR(trade.pnl) : "-"}
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
            value={formatINR(a.netPnl)}
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
          <StatCard label="Avg Win" value={formatINR(a.avgWin)} positive={true} />
          <StatCard
            label="Avg Loss"
            value={formatINR(a.avgLoss)}
            positive={false}
          />
          <StatCard
            label="Best Trade"
            value={formatINR(a.bestTrade)}
            positive={true}
          />
          <StatCard
            label="Worst Trade"
            value={formatINR(a.worstTrade)}
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
                        className={`w-full rounded-sm transition-all ${
                          pnl >= 0 ? "bg-emerald-600/60" : "bg-red-600/60"
                        }`}
                        style={{ height: `${Math.max(2, h * 44)}px` }}
                        title={`${day}: ${formatINR(pnl)} (${count} trades)`}
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
                        className={`h-full rounded transition-all ${
                          pnl >= 0 ? "bg-emerald-700/60" : "bg-red-700/60"
                        }`}
                        style={{ width: `${w}%` }}
                      />
                    </div>
                    <span
                      className={`text-xs font-mono w-20 text-right shrink-0 ${pnlColor(pnl)}`}
                    >
                      {formatINR(pnl)}
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
            value="notes"
            className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted"
          >
            <FileText size={11} className="mr-1" />
            Notes
          </TabsTrigger>
        </TabsList>

        <TabsContent
          value="log"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <TradeLogTab
            trades={trades}
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
          value="notes"
          className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden"
        >
          <NotesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

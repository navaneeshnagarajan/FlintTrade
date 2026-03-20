// Absorbed patterns from:
//   trading-journal/frontend/app/dashboard/portfolios/[id]/page.tsx — TradesTable, win/loss stat cards
//   trading-journal/frontend/app/dashboard/analytics/page.tsx — analytics metrics, formatINR pattern

import { useState, useMemo } from "react";
import { BookOpen, X, Search, BarChart2, FileText, Trophy, AlertCircle } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useTradebook } from "@/hooks/useTradebook";
import type { Trade } from "@/types/api";

interface Props {
  onClose?: () => void;
}

// --- Helpers absorbed from trading-journal/frontend/lib/currency.ts ---
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

function formatDate(ts: string): string {
  if (!ts) return "-";
  try {
    const d = new Date(ts);
    return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" });
  } catch {
    return ts;
  }
}

function formatTime(ts: string): string {
  if (!ts) return "-";
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return ts;
  }
}

// Derive a P&L for each trade from tradebook entries
// In OpenAlgo tradebook, BUY/SELL trades are paired by symbol
// For display we simply show each trade; pair matching is in Analytics tab
function pnlColor(value: number): string {
  if (value > 0) return "text-emerald-400";
  if (value < 0) return "text-red-400";
  return "text-text-secondary";
}

// Analytics computed from tradebook (pairing BUY→SELL by symbol, intraday)
interface TradeAnalytics {
  totalTrades: number;
  totalPnl: number;
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

function computeAnalytics(trades: Trade[]): TradeAnalytics {
  // Group trades by symbol → pair BUY and SELL by FIFO to compute realized P&L
  const pnlList: { pnl: number; ts: string; symbol: string }[] = [];

  const groups: Record<string, Trade[]> = {};
  trades.forEach((t) => {
    if (!groups[t.symbol]) groups[t.symbol] = [];
    groups[t.symbol].push(t);
  });

  for (const symbol of Object.keys(groups)) {
    const legs = groups[symbol];
    const buys = legs.filter((t) => t.action === "BUY").map((t) => ({ qty: t.quantity, price: t.price, ts: t.timestamp }));
    const sells = legs.filter((t) => t.action === "SELL").map((t) => ({ qty: t.quantity, price: t.price, ts: t.timestamp }));

    // Simple FIFO pairing
    let bi = 0;
    let si = 0;
    while (bi < buys.length && si < sells.length) {
      const matched = Math.min(buys[bi].qty, sells[si].qty);
      const pnl = (sells[si].price - buys[bi].price) * matched;
      pnlList.push({ pnl, ts: sells[si].ts, symbol });
      buys[bi] = { ...buys[bi], qty: buys[bi].qty - matched };
      sells[si] = { ...sells[si], qty: sells[si].qty - matched };
      if (buys[bi].qty === 0) bi++;
      if (sells[si].qty === 0) si++;
    }
  }

  const wins = pnlList.filter((p) => p.pnl > 0);
  const losses = pnlList.filter((p) => p.pnl <= 0);
  const totalPnl = pnlList.reduce((s, p) => s + p.pnl, 0);
  const avgWin = wins.length ? wins.reduce((s, p) => s + p.pnl, 0) / wins.length : 0;
  const avgLoss = losses.length ? losses.reduce((s, p) => s + p.pnl, 0) / losses.length : 0;
  const grossWin = wins.reduce((s, p) => s + p.pnl, 0);
  const grossLoss = Math.abs(losses.reduce((s, p) => s + p.pnl, 0));
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0;
  const bestTrade = pnlList.length ? Math.max(...pnlList.map((p) => p.pnl)) : 0;
  const worstTrade = pnlList.length ? Math.min(...pnlList.map((p) => p.pnl)) : 0;

  // By day of week
  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const dowMap: Record<string, { pnl: number; count: number }> = {};
  pnlList.forEach(({ pnl, ts }) => {
    try {
      const d = new Date(ts);
      const key = DOW[d.getDay()];
      if (!dowMap[key]) dowMap[key] = { pnl: 0, count: 0 };
      dowMap[key].pnl += pnl;
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
  pnlList.forEach(({ pnl, symbol }) => {
    if (!symMap[symbol]) symMap[symbol] = { pnl: 0, trades: 0 };
    symMap[symbol].pnl += pnl;
    symMap[symbol].trades += 1;
  });
  const bySymbol = Object.entries(symMap)
    .map(([symbol, v]) => ({ symbol, ...v }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
    .slice(0, 10);

  // Streak
  const sorted = [...pnlList].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
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
    totalTrades: pnlList.length,
    totalPnl,
    winRate: pnlList.length ? (wins.length / pnlList.length) * 100 : 0,
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

// ---- Sub-components ----

function StatCard({ label, value, sub, positive }: { label: string; value: string; sub?: string; positive?: boolean }) {
  return (
    <Card className="bg-surface-card border-border-default">
      <CardContent className="p-3">
        <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">{label}</div>
        <div className={`text-lg font-bold font-mono tabular-nums ${positive === undefined ? "text-text-primary" : positive ? "text-emerald-400" : "text-red-400"}`}>
          {value}
        </div>
        {sub && <div className="text-xs text-text-muted mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function TradeLogTab({ trades }: { trades: Trade[] }) {
  const [search, setSearch] = useState("");
  const [filterAction, setFilterAction] = useState<"ALL" | "BUY" | "SELL">("ALL");

  const filtered = useMemo(() => {
    return trades.filter((t) => {
      const matchSearch = search === "" || t.symbol.toLowerCase().includes(search.toLowerCase());
      const matchAction = filterAction === "ALL" || t.action === filterAction;
      return matchSearch && matchAction;
    });
  }, [trades, search, filterAction]);

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
        <BookOpen size={40} />
        <p className="text-sm">No trades in tradebook today</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full gap-2">
      {/* Filters */}
      <div className="flex items-center gap-2 px-3 pt-2">
        <div className="relative flex-1 max-w-55">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
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
              className={`h-7 px-2 text-xs ${filterAction === v ? "bg-surface-elevated text-text-primary" : "text-text-muted hover:text-text-primary"}`}
              onClick={() => setFilterAction(v)}
            >
              {v}
            </Button>
          ))}
        </div>
        <span className="text-xs text-text-muted ml-auto">{filtered.length} trades</span>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto px-3 pb-2">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              <TableHead className="text-xs text-text-muted h-7 font-normal">Symbol</TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">Action</TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">Qty</TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">Price</TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">Date</TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">Time</TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">Exchange</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((trade, idx) => (
              <TableRow key={trade.tradeId || idx} className="border-border-subtle hover:bg-surface-card">
                <TableCell className="py-1 text-xs font-mono text-text-primary font-medium">{trade.symbol}</TableCell>
                <TableCell className="py-1">
                  <Badge
                    variant="outline"
                    className={`text-xxs px-1.5 py-0 border-0 font-medium ${
                      trade.action === "BUY"
                        ? "bg-emerald-900/40 text-emerald-400"
                        : "bg-red-900/40 text-red-400"
                    }`}
                  >
                    {trade.action}
                  </Badge>
                </TableCell>
                <TableCell className="py-1 text-xs font-mono text-text-secondary text-right">{trade.quantity}</TableCell>
                <TableCell className="py-1 text-xs font-mono text-text-primary text-right">
                  {trade.price.toFixed(2)}
                </TableCell>
                <TableCell className="py-1 text-xs text-text-secondary">{formatDate(trade.timestamp)}</TableCell>
                <TableCell className="py-1 text-xs text-text-secondary">{formatTime(trade.timestamp)}</TableCell>
                <TableCell className="py-1 text-xs text-text-muted">{trade.exchange}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function AnalyticsTab({ trades }: { trades: Trade[] }) {
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
    <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
      {/* KPI cards — absorbed from trading-journal analytics page card layout */}
      <div className="grid grid-cols-4 gap-2">
        <StatCard label="Total P&L" value={formatINR(a.totalPnl)} positive={a.totalPnl >= 0} />
        <StatCard label="Win Rate" value={`${a.winRate.toFixed(1)}%`} sub={`${a.wins}W / ${a.losses}L`} positive={a.winRate >= 50} />
        <StatCard label="Profit Factor" value={isFinite(a.profitFactor) ? a.profitFactor.toFixed(2) : "∞"} positive={a.profitFactor >= 1} />
        <StatCard label="Trades" value={String(a.totalTrades)} />
      </div>

      <div className="grid grid-cols-4 gap-2">
        <StatCard label="Avg Win" value={formatINR(a.avgWin)} positive={true} />
        <StatCard label="Avg Loss" value={formatINR(a.avgLoss)} positive={false} />
        <StatCard label="Best Trade" value={formatINR(a.bestTrade)} positive={true} />
        <StatCard label="Worst Trade" value={formatINR(a.worstTrade)} positive={false} />
      </div>

      {/* Streak */}
      {a.streakType !== "none" && (
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3 flex items-center gap-2">
            <Trophy size={14} className={a.streakType === "win" ? "text-emerald-400" : "text-red-400"} />
            <span className="text-xs text-text-secondary">Current streak:</span>
            <span className={`text-sm font-bold font-mono ${a.streakType === "win" ? "text-emerald-400" : "text-red-400"}`}>
              {a.currentStreak} {a.streakType === "win" ? "wins" : "losses"}
            </span>
          </CardContent>
        </Card>
      )}

      {/* P&L by Day of Week — absorbed from trading-journal bar chart concept */}
      <Card className="bg-surface-card border-border-default">
        <CardHeader className="p-3 pb-1">
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">P&L by Day of Week</CardTitle>
        </CardHeader>
        <CardContent className="p-3 pt-1">
          <div className="flex items-end gap-2 h-16">
            {a.byDayOfWeek.map(({ day, pnl, count }) => {
              const h = maxDowAbs > 0 ? Math.abs(pnl) / maxDowAbs : 0;
              return (
                <div key={day} className="flex flex-col items-center gap-1 flex-1">
                  <div className="w-full flex items-end justify-center" style={{ height: "44px" }}>
                    <div
                      className={`w-full rounded-sm transition-all ${pnl >= 0 ? "bg-emerald-600/60" : "bg-red-600/60"}`}
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
            <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">P&L by Symbol</CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-1 space-y-1.5">
            {a.bySymbol.map(({ symbol, pnl, trades }) => {
              const w = maxSymAbs > 0 ? (Math.abs(pnl) / maxSymAbs) * 100 : 0;
              return (
                <div key={symbol} className="flex items-center gap-2">
                  <span className="text-xs font-mono text-text-primary w-24 shrink-0 truncate">{symbol}</span>
                  <div className="flex-1 h-4 bg-surface-base rounded overflow-hidden">
                    <div
                      className={`h-full rounded transition-all ${pnl >= 0 ? "bg-emerald-700/60" : "bg-red-700/60"}`}
                      style={{ width: `${w}%` }}
                    />
                  </div>
                  <span className={`text-xs font-mono w-20 text-right shrink-0 ${pnlColor(pnl)}`}>{formatINR(pnl)}</span>
                  <span className="text-xs text-text-muted w-14 text-right shrink-0">{trades}t</span>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function NotesTab() {
  const today = new Date().toISOString().slice(0, 10);
  const key = `${NOTES_KEY}_${today}`;
  const [notes, setNotes] = useState(() => {
    try { return localStorage.getItem(key) ?? ""; } catch { return ""; }
  });

  const save = (val: string) => {
    setNotes(val);
    try { localStorage.setItem(key, val); } catch { /* noop */ }
  };

  const wordCount = notes.trim() ? notes.trim().split(/\s+/).length : 0;

  return (
    <div className="flex flex-col gap-2 p-3 h-full">
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-muted">Daily notes — {today}</span>
        <span className="text-xs text-text-muted">{wordCount} words · auto-saved</span>
      </div>
      <Textarea
        className="flex-1 text-sm leading-relaxed"
        placeholder={"Write your trading notes for today...\n\n- Market observations\n- Strategy notes\n- Lessons learned\n- Plan for tomorrow"}
        value={notes}
        onChange={(e) => save(e.target.value)}
      />
      {notes && (
        <Button
          variant="ghost"
          size="sm"
          className="self-end text-xs text-text-muted hover:text-red-400 h-6"
          onClick={() => save("")}
        >
          Clear
        </Button>
      )}
    </div>
  );
}

// ---- Main component ----

export default function TradeJournalTool({ onClose }: Props) {
  const { data: trades = [], isLoading, isError } = useTradebook();

  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card shrink-0">
        <div className="flex items-center gap-2">
          <BookOpen size={16} className="text-primary" />
          <h1 className="font-heading font-bold text-lg text-text-primary">Trade Journal</h1>
          {isLoading && <span className="text-xs text-text-muted">Loading...</span>}
          {isError && <AlertCircle size={12} className="text-red-400" />}
          {!isLoading && !isError && (
            <Badge variant="outline" className="text-xxs border-border-default text-text-muted font-normal">
              {trades.length} trades today
            </Badge>
          )}
        </div>
        <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
          <X size={15} />
        </button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="log" className="flex-1 flex flex-col min-h-0">
        <TabsList className="shrink-0 rounded-none bg-surface-base border-b border-border-default justify-start px-3 h-8 gap-1">
          <TabsTrigger value="log" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <BookOpen size={11} className="mr-1" />Trade Log
          </TabsTrigger>
          <TabsTrigger value="analytics" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <BarChart2 size={11} className="mr-1" />Analytics
          </TabsTrigger>
          <TabsTrigger value="notes" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <FileText size={11} className="mr-1" />Notes
          </TabsTrigger>
        </TabsList>

        <TabsContent value="log" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <TradeLogTab trades={trades} />
        </TabsContent>

        <TabsContent value="analytics" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <AnalyticsTab trades={trades} />
        </TabsContent>

        <TabsContent value="notes" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <NotesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

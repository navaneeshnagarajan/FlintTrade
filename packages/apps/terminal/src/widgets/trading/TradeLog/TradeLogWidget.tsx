/**
 * TradeLogWidget — Detailed execution history with filter, sort, CSV export.
 *
 * Columns: time · symbol · action · qty · price · type · status · strategy · P&L
 *
 * Filters:
 *   - Status: All / Filled / Rejected / Cancelled
 *   - Symbol: free-text search
 *   - Date: today / this-week / custom (stub for live mode)
 *
 * Statistics row (footer):
 *   - Total filled, total realised P&L, avg fill time
 *
 * CSV export: downloads all currently filtered rows.
 */

import { useState, useMemo, useCallback, useEffect, memo } from "react";
import { FileText, Download, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type OrderStatus  = "filled" | "rejected" | "cancelled" | "pending";
export type OrderAction  = "BUY" | "SELL";
export type OrderType    = "MARKET" | "LIMIT" | "SL" | "SL-M";

export interface TradeLogEntry {
  id: string;
  time: string;
  symbol: string;
  action: OrderAction;
  qty: number;
  price: number;
  orderType: OrderType;
  status: OrderStatus;
  strategy: string;
  pnl: number | null;      // null if status is not filled
  fillTimeMs: number | null;  // null if not filled
}

export interface TradeLogStats {
  totalFilled: number;
  totalPnl: number;
  avgFillTimeMs: number;
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

export const SAMPLE_TRADES: TradeLogEntry[] = [
  { id: "O001", time: "09:17:32", symbol: "NIFTY 22200 CE", action: "BUY",  qty: 50,  price: 138.5, orderType: "MARKET", status: "filled",    strategy: "Scalper",   pnl: 2750,  fillTimeMs: 245 },
  { id: "O002", time: "09:35:14", symbol: "NIFTY 22200 CE", action: "SELL", qty: 50,  price: 193.5, orderType: "LIMIT",  status: "filled",    strategy: "Scalper",   pnl: 2750,  fillTimeMs: 1820 },
  { id: "O003", time: "10:02:08", symbol: "BANKNIFTY FUT",  action: "BUY",  qty: 15,  price: 48150, orderType: "MARKET", status: "filled",    strategy: "Momentum",  pnl: 5625,  fillTimeMs: 310 },
  { id: "O004", time: "10:48:55", symbol: "BANKNIFTY FUT",  action: "SELL", qty: 15,  price: 48525, orderType: "SL",     status: "filled",    strategy: "Momentum",  pnl: 5625,  fillTimeMs: 580 },
  { id: "O005", time: "11:15:20", symbol: "NIFTY 22300 PE", action: "BUY",  qty: 100, price:  72.0, orderType: "LIMIT",  status: "rejected",  strategy: "Manual",    pnl: null,  fillTimeMs: null },
  { id: "O006", time: "11:22:44", symbol: "NIFTY 22100 PE", action: "BUY",  qty: 100, price:  65.5, orderType: "MARKET", status: "filled",    strategy: "Manual",    pnl: -890,  fillTimeMs: 198 },
  { id: "O007", time: "11:48:30", symbol: "NIFTY 22100 PE", action: "SELL", qty: 100, price:  56.6, orderType: "SL-M",   status: "filled",    strategy: "Manual",    pnl: -890,  fillTimeMs: 421 },
  { id: "O008", time: "12:10:05", symbol: "FINNIFTY FUT",   action: "BUY",  qty: 40,  price: 23180, orderType: "MARKET", status: "cancelled", strategy: "Auto",      pnl: null,  fillTimeMs: null },
  { id: "O009", time: "13:30:17", symbol: "NIFTY FUT",      action: "BUY",  qty: 50,  price: 22380, orderType: "LIMIT",  status: "filled",    strategy: "Scalper",   pnl: 3200,  fillTimeMs: 950 },
  { id: "O010", time: "14:55:42", symbol: "NIFTY FUT",      action: "SELL", qty: 50,  price: 22444, orderType: "MARKET", status: "filled",    strategy: "Scalper",   pnl: 3200,  fillTimeMs: 275 },
];

// ---------------------------------------------------------------------------
// Computed stats
// ---------------------------------------------------------------------------

export function computeStats(entries: TradeLogEntry[]): TradeLogStats {
  const filled = entries.filter((e) => e.status === "filled");
  const totalFilled = filled.length;
  const totalPnl = filled.reduce((s, e) => s + (e.pnl ?? 0), 0) / 2;  // paired trades share P&L
  const fillTimes = filled.map((e) => e.fillTimeMs).filter((t): t is number => t !== null);
  const avgFillTimeMs = fillTimes.length > 0
    ? fillTimes.reduce((s, t) => s + t, 0) / fillTimes.length
    : 0;
  return { totalFilled, totalPnl, avgFillTimeMs };
}

// ---------------------------------------------------------------------------
// CSV export
// ---------------------------------------------------------------------------

function exportCSV(rows: TradeLogEntry[]): void {
  const header = ["Time", "Symbol", "Action", "Qty", "Price", "Type", "Status", "Strategy", "P&L"];
  const lines = rows.map((r) => [
    r.time, r.symbol, r.action, r.qty, r.price, r.orderType, r.status, r.strategy,
    r.pnl != null ? r.pnl.toString() : "",
  ].join(","));
  const csv = [header.join(","), ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `trade-log-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_BG: Record<OrderStatus, string> = {
  filled:    "bg-bullish-bg text-profit border-bullish-border",
  rejected:  "bg-bearish-bg text-loss border-bearish-border",
  cancelled: "bg-surface-hover text-text-muted border-border-default",
  pending:   "bg-atm-bg text-warning border-atm-border",
};

function fmtPnl(pnl: number): string {
  const sign = pnl >= 0 ? "+" : "−";
  return `${sign}₹${Math.abs(pnl).toLocaleString("en-IN")}`;
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

// ---------------------------------------------------------------------------
// Table row
// ---------------------------------------------------------------------------

function TradeRow({ entry }: { entry: TradeLogEntry }) {
  return (
    <tr
      className="border-b border-border-subtle hover:bg-surface-hover transition-colors"
      aria-label={`Order ${entry.id}: ${entry.symbol} ${entry.action} ${entry.qty} @ ${entry.price}`}
    >
      <td className="py-1 px-1.5 text-xxs text-text-muted font-mono whitespace-nowrap">{entry.time}</td>
      <td className="py-1 px-1.5 text-xs text-text-secondary truncate max-w-28" title={entry.symbol}>{entry.symbol}</td>
      <td className="py-1 px-1.5 text-center">
        <span className={cn("text-xxs font-bold", entry.action === "BUY" ? "text-profit" : "text-loss")}>
          {entry.action}
        </span>
      </td>
      <td className="py-1 px-1.5 text-xs font-mono tabular-nums text-text-primary text-right">{entry.qty}</td>
      <td className="py-1 px-1.5 text-xs font-mono tabular-nums text-text-primary text-right">
        {entry.price.toLocaleString("en-IN")}
      </td>
      <td className="py-1 px-1.5 text-xxs text-text-muted text-center whitespace-nowrap">{entry.orderType}</td>
      <td className="py-1 px-1.5 text-center">
        <span className={cn("text-xxs px-1.5 py-0.5 rounded border font-medium", STATUS_BG[entry.status])}>
          {entry.status}
        </span>
      </td>
      <td className="py-1 px-1.5 text-xxs text-text-muted truncate max-w-20" title={entry.strategy}>
        {entry.strategy}
      </td>
      <td className={cn(
        "py-1 px-1.5 text-xs font-mono tabular-nums text-right font-medium",
        entry.pnl == null
          ? "text-text-muted"
          : entry.pnl >= 0 ? "text-profit" : "text-loss",
      )}>
        {entry.pnl != null ? fmtPnl(entry.pnl) : "—"}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Stats footer
// ---------------------------------------------------------------------------

function StatsFooter({ stats }: { stats: TradeLogStats }) {
  return (
    <div
      className="flex-none flex items-center gap-4 px-3 py-2 bg-surface-card border-t border-border-default flex-wrap"
      aria-label="Trade log statistics"
    >
      <div className="flex items-center gap-1.5">
        <span className="text-xxs text-text-muted uppercase tracking-wide">Filled</span>
        <span className="text-xs font-semibold font-mono text-text-primary">{stats.totalFilled}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-xxs text-text-muted uppercase tracking-wide">Total P&L</span>
        <span className={cn("text-xs font-semibold font-mono tabular-nums", stats.totalPnl >= 0 ? "text-profit" : "text-loss")}>
          {fmtPnl(stats.totalPnl)}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-xxs text-text-muted uppercase tracking-wide">Avg Fill</span>
        <span className="text-xs font-semibold font-mono text-text-secondary">
          {stats.avgFillTimeMs > 0 ? fmtMs(stats.avgFillTimeMs) : "—"}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

type StatusFilter = "All" | OrderStatus;

function TradeLogWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("All");
  const [symbolSearch, setSymbolSearch] = useState("");

  useEffect(() => {
    track("trade", "widget_view_trade_log");
  }, [track]);

  const filtered = useMemo(() => {
    let rows = SAMPLE_TRADES;
    if (statusFilter !== "All") rows = rows.filter((r) => r.status === statusFilter);
    if (symbolSearch.trim()) {
      const q = symbolSearch.trim().toLowerCase();
      rows = rows.filter((r) => r.symbol.toLowerCase().includes(q));
    }
    return rows;
  }, [statusFilter, symbolSearch]);

  const stats = useMemo(() => computeStats(filtered), [filtered]);

  const handleExport = useCallback(() => {
    track("trade", "trade_log_export_csv");
    exportCSV(filtered);
  }, [track, filtered]);

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="Trade Log widget"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <FileText size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Trade Log</span>
        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
        <div className="flex-1" />
        <Button
          variant="outline"
          size="sm"
          onClick={handleExport}
          className="flex items-center gap-1 h-auto px-2 py-0.5 text-xs bg-surface-hover border-border-default text-text-muted hover:text-text-primary hover:border-accent/40 transition-colors"
          aria-label="Export CSV"
          title="Export filtered rows as CSV"
        >
          <Download size={10} />
          CSV
        </Button>
      </div>

      {/* Filter bar */}
      <div
        className="flex-none flex items-center gap-1.5 px-2 py-1.5 bg-surface-card border-b border-border-subtle flex-wrap"
        aria-label="Trade log filters"
      >
        {/* Status filter pills */}
        <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
          {(["All", "filled", "rejected", "cancelled"] as StatusFilter[]).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={cn(
                "px-2 py-0.5 text-xxs font-medium capitalize transition-colors",
                s === statusFilter
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
              aria-pressed={s === statusFilter}
            >
              {s}
            </button>
          ))}
        </div>

        {/* Symbol search */}
        <div className="relative">
          <Search size={10} className="absolute left-1.5 top-1/2 -translate-y-1/2 text-text-disabled pointer-events-none" />
          <Input
            type="text"
            value={symbolSearch}
            onChange={(e) => setSymbolSearch(e.target.value)}
            placeholder="Symbol…"
            className="pl-5 pr-2 py-0.5 text-xs bg-surface-hover border-border-default rounded text-text-primary placeholder:text-text-muted focus-visible:ring-0 focus-visible:border-accent/50 w-28 h-auto"
            aria-label="Search symbol"
          />
        </div>

        <span className="text-xxs text-text-muted font-mono ml-auto">{filtered.length} orders</span>
      </div>

      {/* Table */}
      <div className="flex-1 min-h-0 overflow-auto">
        <table className="w-full text-xs" aria-label="Execution history table">
          <thead className="sticky top-0 bg-surface-card z-10">
            <tr className="border-b border-border-default">
              <th className="text-left py-1 px-1.5 text-xxs text-text-muted font-medium whitespace-nowrap">Time</th>
              <th className="text-left py-1 px-1.5 text-xxs text-text-muted font-medium">Symbol</th>
              <th className="text-center py-1 px-1.5 text-xxs text-text-muted font-medium">Action</th>
              <th className="text-right py-1 px-1.5 text-xxs text-text-muted font-medium">Qty</th>
              <th className="text-right py-1 px-1.5 text-xxs text-text-muted font-medium">Price</th>
              <th className="text-center py-1 px-1.5 text-xxs text-text-muted font-medium">Type</th>
              <th className="text-center py-1 px-1.5 text-xxs text-text-muted font-medium">Status</th>
              <th className="text-left py-1 px-1.5 text-xxs text-text-muted font-medium">Strategy</th>
              <th className="text-right py-1 px-1.5 text-xxs text-text-muted font-medium">P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={9} className="py-8 text-center text-text-muted text-xs">
                  No orders match the current filters
                </td>
              </tr>
            ) : (
              filtered.map((entry) => <TradeRow key={entry.id} entry={entry} />)
            )}
          </tbody>
        </table>
      </div>

      {/* Stats footer */}
      <StatsFooter stats={stats} />
    </div>
  );
}

export default memo(TradeLogWidget);

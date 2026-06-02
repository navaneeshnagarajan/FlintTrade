/**
 * SessionStatsWidget — Current trading session statistics.
 *
 * Displays:
 *   - Trades executed today, orders placed / filled / rejected
 *   - Best and worst trade of the session (P&L in INR)
 *   - Win rate for today
 *   - Max intraday drawdown
 *   - Active time (time spent in positions), idle time
 *   - Average hold duration across completed trades
 *
 * Data is from sample records when disconnected; in live mode it reads
 * from the tradebook and positionbook endpoints.
 */

import { useMemo, useEffect, memo } from "react";
import { Clock } from "lucide-react";
import { FlintBaselineSparkline } from "@flinttrade/design-system";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SessionTrade {
  id: string;
  symbol: string;
  pnl: number;
  holdMinutes: number;
  isWin: boolean;
  entryTime: string;
  exitTime: string;
}

interface OrderSummary {
  placed: number;
  filled: number;
  rejected: number;
  pending: number;
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

export const SAMPLE_SESSION_TRADES: SessionTrade[] = [
  { id: "T001", symbol: "NIFTY 22200 CE", pnl:  3240, holdMinutes: 22, isWin: true,  entryTime: "09:18", exitTime: "09:40" },
  { id: "T002", symbol: "NIFTY 22100 PE", pnl: -1120, holdMinutes: 14, isWin: false, entryTime: "09:52", exitTime: "10:06" },
  { id: "T003", symbol: "BANKNIFTY FUT",  pnl:  5680, holdMinutes: 47, isWin: true,  entryTime: "10:14", exitTime: "11:01" },
  { id: "T004", symbol: "NIFTY 22000 CE", pnl: -890,  holdMinutes:  9, isWin: false, entryTime: "11:22", exitTime: "11:31" },
  { id: "T005", symbol: "NIFTY 22300 PE", pnl:  2150, holdMinutes: 31, isWin: true,  entryTime: "11:45", exitTime: "12:16" },
  { id: "T006", symbol: "NIFTY FUT",      pnl:  4410, holdMinutes: 58, isWin: true,  entryTime: "12:30", exitTime: "13:28" },
  { id: "T007", symbol: "NIFTY 21900 PE", pnl: -620,  holdMinutes:  6, isWin: false, entryTime: "13:45", exitTime: "13:51" },
];

export const SAMPLE_ORDER_SUMMARY: OrderSummary = {
  placed:   14,
  filled:   12,
  rejected:  1,
  pending:   1,
};

// ---------------------------------------------------------------------------
// Computations
// ---------------------------------------------------------------------------

interface SessionMetrics {
  totalTrades: number;
  winCount: number;
  lossCount: number;
  winRate: number;
  totalPnl: number;
  bestTrade: SessionTrade | null;
  worstTrade: SessionTrade | null;
  maxDrawdown: number;
  avgHoldMinutes: number;
  activeMinutes: number;
  sessionMinutes: number;   // 9:15 → current (or last trade exit)
}

function computeSessionMetrics(trades: SessionTrade[]): SessionMetrics {
  if (trades.length === 0) {
    return {
      totalTrades: 0, winCount: 0, lossCount: 0, winRate: 0,
      totalPnl: 0, bestTrade: null, worstTrade: null,
      maxDrawdown: 0, avgHoldMinutes: 0, activeMinutes: 0, sessionMinutes: 375,
    };
  }

  const winCount = trades.filter((t) => t.isWin).length;
  const lossCount = trades.length - winCount;
  const winRate = (winCount / trades.length) * 100;
  const totalPnl = trades.reduce((s, t) => s + t.pnl, 0);

  const bestTrade = trades.reduce((best, t) => t.pnl > (best?.pnl ?? -Infinity) ? t : best, trades[0]);
  const worstTrade = trades.reduce((worst, t) => t.pnl < (worst?.pnl ?? Infinity) ? t : worst, trades[0]);

  // Max drawdown from equity peak
  let peak = 0;
  let cum = 0;
  let maxDd = 0;
  for (const t of trades) {
    cum += t.pnl;
    if (cum > peak) peak = cum;
    const dd = peak - cum;
    if (dd > maxDd) maxDd = dd;
  }

  const avgHoldMinutes = trades.reduce((s, t) => s + t.holdMinutes, 0) / trades.length;
  const activeMinutes = trades.reduce((s, t) => s + t.holdMinutes, 0);

  // Approximate session duration (9:15 AM to last exit time)
  const lastExitStr = trades[trades.length - 1]?.exitTime ?? "09:15";
  const [h, m] = lastExitStr.split(":").map(Number);
  const sessionMinutes = Math.max(0, (h * 60 + m) - (9 * 60 + 15));

  return {
    totalTrades: trades.length,
    winCount, lossCount, winRate,
    totalPnl, bestTrade, worstTrade,
    maxDrawdown: maxDd, avgHoldMinutes,
    activeMinutes, sessionMinutes,
  };
}

function fmtPnl(v: number): string {
  const sign = v >= 0 ? "+" : "−";
  return `${sign}₹${Math.abs(v).toLocaleString("en-IN")}`;
}

function fmtMinutes(m: number): string {
  if (m < 60) return `${Math.round(m)}m`;
  return `${Math.floor(m / 60)}h ${Math.round(m % 60)}m`;
}

// ---------------------------------------------------------------------------
// Stat tile
// ---------------------------------------------------------------------------

interface StatTileProps {
  label: string;
  value: string;
  sub?: string;
  colour?: string;
}

function StatTile({ label, value, sub, colour = "text-text-primary" }: StatTileProps) {
  return (
    <div className="flex flex-col gap-0.5 bg-surface-hover rounded px-2.5 py-2">
      <span className="text-xxs text-text-muted">{label}</span>
      <span className={cn("text-xs font-semibold font-mono tabular-nums", colour)}>{value}</span>
      {sub && <span className="text-xxs text-text-muted">{sub}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mini equity curve
// ---------------------------------------------------------------------------

function MiniEquity({ trades }: { trades: SessionTrade[] }) {
  const equity = useMemo(() => {
    let cum = 0;
    return [0, ...trades.map((t) => { cum += t.pnl; return cum; })];
  }, [trades]);

  if (equity.length < 2) return null;

  const isProfit = equity[equity.length - 1] >= 0;

  return (
    <div className="space-y-1">
      <FlintBaselineSparkline
        points={equity}
        baseline={0}
        positive={isProfit}
        ariaLabel="Session equity curve"
        className="h-10 w-full"
      />
      {equity.length > 2 && (
        <p className="text-center text-xxs text-text-muted">{trades.length} trades</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Order summary bar
// ---------------------------------------------------------------------------

function OrderBar({ summary }: { summary: OrderSummary }) {
  const { placed, filled, rejected, pending } = summary;
  return (
    <div
      className="flex items-center gap-3 flex-wrap"
      aria-label={`Orders: ${placed} placed, ${filled} filled, ${rejected} rejected, ${pending} pending`}
    >
      {[
        { label: "Placed",   value: placed,   colour: "text-text-primary" },
        { label: "Filled",   value: filled,   colour: "text-profit" },
        { label: "Rejected", value: rejected, colour: "text-loss" },
        { label: "Pending",  value: pending,  colour: "text-warning" },
      ].map(({ label, value, colour }) => (
        <div key={label} className="flex items-center gap-1">
          <span className="text-xxs text-text-muted">{label}</span>
          <span className={cn("text-xs font-semibold font-mono", colour)}>{value}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function SessionStatsWidget() {
  const track = useTrackBehavior();
  // NOTE: We previously read `isConnected = useBrokerConnected()` to gate the
  // "Sample" badge on disconnect-only. Now the badge is unconditional (the
  // widget always renders sample data because no backend endpoint exists yet
  // — see header comment below), so the hook is no longer needed here.

  useEffect(() => {
    track("trade", "widget_view_session_stats");
  }, [track]);

  const metrics = useMemo(() => computeSessionMetrics(SAMPLE_SESSION_TRADES), []);
  const idleMinutes = Math.max(0, metrics.sessionMinutes - metrics.activeMinutes);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Session Stats widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Clock size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Session Stats</span>
        {/* Honest disclosure — `computeSessionMetrics(SAMPLE_SESSION_TRADES)`
            is the only data source today; no backend session-aggregation
            endpoint exists. The badge previously hid in `isConnected` mode,
            which masked the fact that we were still showing sample data
            even after a broker connection. Keep visible at all times. */}
        <span
          className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
          role="status"
          aria-label="Showing sample data; no live backend endpoint yet"
          title="No live data wired yet — showing sample session statistics so the widget is usable in explore mode."
        >
          Sample data
        </span>
        <div className="flex-1" />
        <span className={cn("text-sm font-bold font-mono tabular-nums", metrics.totalPnl >= 0 ? "text-profit" : "text-loss")}>
          {fmtPnl(metrics.totalPnl)}
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-3">

        {/* Equity curve */}
        <section aria-labelledby="ss-equity">
          <p id="ss-equity" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1">
            Session Equity
          </p>
          <MiniEquity trades={SAMPLE_SESSION_TRADES} />
        </section>

        {/* Orders */}
        <section aria-labelledby="ss-orders">
          <p id="ss-orders" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1">
            Orders
          </p>
          <OrderBar summary={SAMPLE_ORDER_SUMMARY} />
        </section>

        {/* Key stats grid */}
        <section aria-labelledby="ss-stats">
          <p id="ss-stats" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1">
            Stats
          </p>
          <div className="grid grid-cols-3 gap-1.5">
            <StatTile
              label="Trades"
              value={String(metrics.totalTrades)}
              sub={`${metrics.winCount}W / ${metrics.lossCount}L`}
            />
            <StatTile
              label="Win Rate"
              value={`${metrics.winRate.toFixed(0)}%`}
              colour={metrics.winRate >= 50 ? "text-profit" : "text-loss"}
            />
            <StatTile
              label="Max Drawdown"
              value={`₹${metrics.maxDrawdown.toLocaleString("en-IN")}`}
              colour="text-loss"
            />
          </div>
        </section>

        {/* Best / Worst trade */}
        <section aria-labelledby="ss-trades">
          <p id="ss-trades" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1">
            Best / Worst Trade
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            {metrics.bestTrade && (
              <div className="bg-profit/10 border border-profit/20 rounded px-2.5 py-2">
                <div className="text-xxs text-text-muted mb-0.5">Best</div>
                <div className="text-xs font-semibold text-profit font-mono">{fmtPnl(metrics.bestTrade.pnl)}</div>
                <div className="text-xxs text-text-secondary truncate">{metrics.bestTrade.symbol}</div>
                <div className="text-xxs text-text-muted">{metrics.bestTrade.entryTime} – {metrics.bestTrade.exitTime}</div>
              </div>
            )}
            {metrics.worstTrade && (
              <div className="bg-loss/10 border border-loss/20 rounded px-2.5 py-2">
                <div className="text-xxs text-text-muted mb-0.5">Worst</div>
                <div className="text-xs font-semibold text-loss font-mono">{fmtPnl(metrics.worstTrade.pnl)}</div>
                <div className="text-xxs text-text-secondary truncate">{metrics.worstTrade.symbol}</div>
                <div className="text-xxs text-text-muted">{metrics.worstTrade.entryTime} – {metrics.worstTrade.exitTime}</div>
              </div>
            )}
          </div>
        </section>

        {/* Time breakdown */}
        <section aria-labelledby="ss-time">
          <p id="ss-time" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1">
            Time Breakdown
          </p>
          <div className="grid grid-cols-3 gap-1.5">
            <StatTile
              label="Avg Hold"
              value={fmtMinutes(metrics.avgHoldMinutes)}
            />
            <StatTile
              label="Active"
              value={fmtMinutes(metrics.activeMinutes)}
              colour="text-profit"
            />
            <StatTile
              label="Idle"
              value={fmtMinutes(idleMinutes)}
              colour="text-text-muted"
            />
          </div>

          {/* Active/Idle progress bar */}
          {metrics.sessionMinutes > 0 && (
            <div className="mt-1.5">
              <div className="flex h-2 rounded-full overflow-hidden bg-surface-base" aria-label="Active vs idle time bar">
                <div
                  className="bg-profit/60"
                  style={{ width: `${(metrics.activeMinutes / metrics.sessionMinutes) * 100}%` }}
                />
                <div className="bg-surface-hover flex-1" />
              </div>
              <div className="flex justify-between text-xxs text-text-muted mt-0.5">
                <span>Active {Math.round((metrics.activeMinutes / metrics.sessionMinutes) * 100)}%</span>
                <span>Session {fmtMinutes(metrics.sessionMinutes)}</span>
              </div>
            </div>
          )}
        </section>

        {/* Trade log mini-table */}
        <section aria-labelledby="ss-log">
          <p id="ss-log" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1">
            Trade Log
          </p>
          <table className="w-full text-xs" aria-label="Today's trade log">
            <thead>
              <tr className="border-b border-border-subtle">
                <th className="text-left py-1 text-xxs text-text-muted font-medium">Symbol</th>
                <th className="text-center py-1 text-xxs text-text-muted font-medium">Time</th>
                <th className="text-right py-1 text-xxs text-text-muted font-medium">Hold</th>
                <th className="text-right py-1 text-xxs text-text-muted font-medium">P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {SAMPLE_SESSION_TRADES.map((t) => (
                <tr key={t.id} className="border-b border-border-subtle hover:bg-surface-hover transition-colors">
                  <td className="py-1 text-text-secondary truncate max-w-24" title={t.symbol}>{t.symbol}</td>
                  <td className="py-1 text-center font-mono text-text-muted text-xxs">{t.entryTime}</td>
                  <td className="py-1 text-right font-mono text-text-muted text-xxs">{t.holdMinutes}m</td>
                  <td className={cn("py-1 text-right font-mono tabular-nums font-medium", t.isWin ? "text-profit" : "text-loss")}>
                    {fmtPnl(t.pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}

export default memo(SessionStatsWidget);

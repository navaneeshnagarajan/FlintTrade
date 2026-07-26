/**
 * PerformanceTab — longer-horizon performance metrics (Trade Review tool).
 *
 * Union of the retired TradePerformance widget and the tool's old Analytics
 * tab (merge 2.12). Every metric now routes through the canonical
 * ``lib/journalAnalytics`` — the widget's local ``computeMetrics`` was a
 * near-verbatim fork of ``computeAnalytics`` with three divergences, all
 * resolved in the shared library's favour:
 *   - profit factor with zero losses is rendered "∞" (the fork returned a
 *     fabricated 99);
 *   - streaks and the equity curve are computed over CHRONOLOGICALLY sorted
 *     closed trades (the fork used raw array order, and the journal endpoint
 *     returns newest-first — so its equity curve ran backwards);
 *   - avg-loss sign: ``computeAnalytics`` reports the signed average; R:R and
 *     expectancy take the absolute value explicitly.
 *
 * Timeframe scope (the SessionStats ↔ TradePerformance merge ruling):
 *   - "YTD" (default) — the widget's year-to-date window, via its own query.
 *     The YTD end date is the IST trading day (the widget's
 *     ``toISOString().slice`` end date silently excluded the current session
 *     through the whole IST early morning).
 *   - "Range" — the tool's committed header date range (the old Analytics
 *     tab's scope), sharing the tool's main query.
 * Explore mode renders the tool's disclosed sample trades for both scopes and
 * never queries the backend.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  FlintRankedBarList,
  FlintSignedCategoricalBarChart,
  FlintThresholdLineChart,
} from "@flinttrade/design-system";
import { Trophy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatCurrencyCompact } from "@/lib/formatters";
import { istParts, istToday } from "@/lib/ist";
import {
  computeAllStreaks,
  computeAnalytics,
  getLongestLossStreak,
  getLongestWinStreak,
} from "@/lib/journalAnalytics";
import { getTradeJournal, type JournalTrade } from "@/services/ftApi";
import { useModeStore } from "@/stores/modeStore";
import { StatCard } from "./StatCard";

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Closed trades in chronological order. Only realised trades (a non-zero
 * numeric P&L leg) count — open/manual single-leg fills carry ``pnl: null``
 * and are excluded rather than counted as break-even wins. Never fabricates a
 * result. Mirrors the closed-trade filter inside ``computeAnalytics`` so the
 * equity curve and the metric tiles always describe the same trade set.
 */
export function closedChronological(rows: JournalTrade[]): JournalTrade[] {
  return rows
    .filter((r) => typeof r.pnl === "number" && r.pnl !== 0)
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
}

/** Cumulative equity series (starting at 0) over closed trades in order. */
export function computeEquitySeries(closed: JournalTrade[]): number[] {
  let cum = 0;
  return [0, ...closed.map((t) => { cum += t.pnl; return cum; })];
}

/**
 * Net P&L per calendar month, keyed ``YYYY-MM``.
 *
 * The month is sliced from the backend's written timestamp (its stated IST
 * session date), never re-derived through ``toISOString`` — re-zoning would
 * shift early-morning fills into the previous UTC month.
 */
export function computeMonthlyReturns(closed: JournalTrade[]): Record<string, number> {
  const monthly: Record<string, number> = {};
  for (const t of closed) {
    const key = typeof t.timestamp === "string" ? t.timestamp.slice(0, 7) : "";
    if (!key) continue;
    monthly[key] = (monthly[key] ?? 0) + t.pnl;
  }
  return monthly;
}

/**
 * YTD window (1 January → today) on the IST calendar, as ``YYYY-MM-DD``.
 *
 * The retired widget built the end date with ``toISOString().slice(0, 10)``,
 * which reads the UTC day — through the whole 00:00–05:29 IST window the YTD
 * query therefore ended on YESTERDAY and dropped the current session.
 */
export function ytdIstRange(): { start: string; end: string } {
  const { year } = istParts();
  return { start: `${year}-01-01`, end: istToday() };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// ---------------------------------------------------------------------------
// Equity curve
// ---------------------------------------------------------------------------

function formatAxisAmount(value: number) {
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1000) return `${sign}${(abs / 1000).toFixed(0)}k`;
  return `${sign}${abs.toFixed(0)}`;
}

function EquityCurve({ equity }: { equity: number[] }) {
  const values = equity.length > 0 ? equity : [0];
  const minValue = Math.min(...values, 0);
  const maxValue = Math.max(...values, 1);
  const isProfit = values[values.length - 1] >= 0;
  const yTicks = Array.from(new Set([minValue, 0, maxValue])).sort((a, b) => a - b);
  const points = values.map((value, index) => ({
    label: index === 0 ? "Start" : index === values.length - 1 ? "Now" : `${index}`,
    value,
  }));

  return (
    <FlintThresholdLineChart
      ariaLabel="Equity curve chart"
      points={points}
      minValue={minValue}
      maxValue={maxValue}
      thresholds={[
        { value: 0, color: "rgba(156,163,175,0.3)", dash: "3,2", label: "Flat" },
      ]}
      yTicks={yTicks}
      xLabelIndices={[0, values.length - 1]}
      yFormatter={formatAxisAmount}
      lineColor={isProfit ? "rgba(34,197,94,0.85)" : "rgba(239,68,68,0.85)"}
      fillColor={isProfit ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)"}
      width={480}
      height={100}
    />
  );
}

// ---------------------------------------------------------------------------
// Monthly returns heatmap
// ---------------------------------------------------------------------------

function MonthlyHeatmap({ returns }: { returns: Record<string, number> }) {
  const sortedKeys = Object.keys(returns).sort();
  const maxAbs = Math.max(...Object.values(returns).map(Math.abs), 1);

  if (sortedKeys.length === 0) {
    return <p className="text-xxs text-text-muted">No monthly data yet.</p>;
  }

  return (
    <div className="flex flex-wrap gap-1" aria-label="Monthly returns heatmap">
      {sortedKeys.map((key) => {
        const val = returns[key];
        const intensity = Math.min(Math.abs(val) / maxAbs, 1);
        const bg = val >= 0
          ? `rgba(34,197,94,${0.15 + intensity * 0.45})`
          : `rgba(239,68,68,${0.15 + intensity * 0.45})`;
        const [, month] = key.split("-");
        const monthName = MONTHS[(parseInt(month, 10) - 1) % 12];
        return (
          <div
            key={key}
            title={`${monthName}: ${val >= 0 ? "+" : ""}${val.toLocaleString("en-IN")}`}
            aria-label={`${monthName} ${val >= 0 ? "profit" : "loss"} ${Math.abs(val).toLocaleString("en-IN")}`}
            className="flex flex-col items-center justify-center rounded px-1.5 py-1 min-w-10"
            style={{ background: bg }}
          >
            <span className="text-xxs font-medium text-text-primary">{monthName}</span>
            <span className="text-xxs font-mono tabular-nums text-text-secondary">
              {val >= 0 ? "+" : ""}{val >= 1000 || val <= -1000
                ? `${(val / 1000).toFixed(1)}k`
                : val.toFixed(0)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export type PerformanceScope = "ytd" | "range";

export interface PerformanceTabProps {
  /** The tool's committed-range journal rows (sample rows in explore mode). */
  trades: JournalTrade[];
  /** Human-readable committed range, e.g. "2026-07-19 → 2026-07-25". */
  rangeLabel: string;
}

export function PerformanceTab({ trades, rangeLabel }: PerformanceTabProps) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const [scope, setScope] = useState<PerformanceScope>("ytd");

  const { start, end } = useMemo(() => ytdIstRange(), []);
  const ytdEnabled = !isExplore && scope === "ytd";
  const { data: ytdResp } = useQuery({
    queryKey: ["tradeJournal", "perf", start, end],
    queryFn: () => getTradeJournal(start, end),
    enabled: ytdEnabled,
    refetchInterval: ytdEnabled ? 30_000 : false,
  });

  // Explore renders the tool's disclosed sample for both scopes; live/practice
  // use the YTD query or the tool's committed-range rows. Never fabricated.
  const rows = useMemo<JournalTrade[]>(() => {
    if (isExplore) return trades;
    if (scope === "ytd") return ytdResp?.trades ?? [];
    return trades;
  }, [isExplore, scope, trades, ytdResp]);

  const analytics = useMemo(() => computeAnalytics(rows), [rows]);
  const closed = useMemo(() => closedChronological(rows), [rows]);
  const equity = useMemo(() => computeEquitySeries(closed), [closed]);
  const monthlyReturns = useMemo(() => computeMonthlyReturns(closed), [closed]);
  const streaks = useMemo(() => computeAllStreaks(rows), [rows]);
  const longestWin = useMemo(() => getLongestWinStreak(streaks), [streaks]);
  const longestLoss = useMemo(() => getLongestLossStreak(streaks), [streaks]);

  const avgLossAbs = Math.abs(analytics.avgLoss);
  const rr = avgLossAbs > 0 ? analytics.avgWin / avgLossAbs : 0;
  const expectancy =
    (analytics.winRate / 100) * analytics.avgWin -
    ((100 - analytics.winRate) / 100) * avgLossAbs;

  const streakColour =
    analytics.streakType === "win" ? "text-profit" : analytics.streakType === "loss" ? "text-loss" : "text-text-muted";
  const streakLabel =
    analytics.streakType === "win"
      ? `W${analytics.currentStreak}`
      : analytics.streakType === "loss"
        ? `L${analytics.currentStreak}`
        : "—";

  const dayOfWeekEntries = analytics.byDayOfWeek.map(({ day, pnl }) => ({
    label: day,
    value: pnl,
    color: pnl >= 0 ? "var(--color-profit, #22c55e)" : "var(--color-loss, #ef4444)",
  }));
  const symbolPnlEntries = analytics.bySymbol.map(({ symbol, pnl }) => ({
    label: symbol,
    value: pnl,
    color: pnl >= 0 ? "var(--color-profit, #22c55e)" : "var(--color-loss, #ef4444)",
  }));

  const hasData = closed.length > 0;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Performance metrics">

      {/* Scope row */}
      <div className="flex-none flex items-center gap-2 px-3 py-1.5 bg-surface-card border-b border-border-default">
        <Trophy size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Performance</span>
        <span className="text-xxs text-text-muted font-mono">
          {scope === "ytd" ? `${start} → ${end}` : rangeLabel}
        </span>
        <div className="flex-1" />
        <div className="flex gap-1" role="group" aria-label="Performance timeframe">
          {([
            { value: "range", label: "Range" },
            { value: "ytd", label: "YTD" },
          ] as const).map(({ value, label }) => (
            <Button
              key={value}
              variant="ghost"
              size="sm"
              aria-pressed={scope === value}
              className={`h-5 px-2 text-xxs ${
                scope === value
                  ? "bg-surface-elevated text-text-primary"
                  : "text-text-muted hover:text-text-primary"
              }`}
              onClick={() => setScope(value)}
            >
              {label}
            </Button>
          ))}
        </div>
      </div>

      {!isExplore && !hasData ? (
        <div
          className="flex-1 min-h-0 flex items-center justify-center px-4 text-center"
          aria-label="No performance data"
        >
          <p className="text-xs text-text-muted">
            {scope === "ytd"
              ? "No closed trades yet this year. Performance metrics appear once your journalled trades have realised P&L."
              : "No closed trades in the selected range. Performance metrics appear once your journalled trades have realised P&L."}
          </p>
        </div>
      ) : (
        <ScrollArea className="flex-1 px-3 py-2">
          <div className="space-y-3">

            {/* Equity curve */}
            <section aria-labelledby="perf-eq-label">
              <p id="perf-eq-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
                Equity Curve
              </p>
              <EquityCurve equity={equity} />
            </section>

            {/* Key metrics (union of the widget tiles and the Analytics tab KPI cards) */}
            <div className="grid grid-cols-5 gap-2">
              <StatCard
                label="Net P&L"
                value={formatCurrencyCompact(analytics.netPnl)}
                positive={analytics.netPnl >= 0}
              />
              <StatCard
                label="Trades"
                value={String(analytics.totalTrades)}
                sub={`${analytics.wins}W / ${analytics.losses}L`}
              />
              <StatCard
                label="Win Rate"
                value={`${analytics.winRate.toFixed(1)}%`}
                positive={analytics.winRate >= 50}
              />
              <StatCard
                label="Profit Factor"
                value={isFinite(analytics.profitFactor) ? analytics.profitFactor.toFixed(2) : "∞"}
                positive={analytics.profitFactor >= 1}
              />
              <StatCard
                label="Expectancy"
                value={formatCurrencyCompact(expectancy)}
                positive={expectancy >= 0}
              />
            </div>
            <div className="grid grid-cols-5 gap-2">
              <StatCard label="Avg Win" value={formatCurrencyCompact(analytics.avgWin)} positive={true} />
              <StatCard label="Avg Loss" value={formatCurrencyCompact(analytics.avgLoss)} positive={false} />
              <StatCard
                label="Avg R:R"
                value={rr.toFixed(2)}
                positive={rr >= 1}
              />
              <StatCard label="Best Trade" value={formatCurrencyCompact(analytics.bestTrade)} positive={true} />
              <StatCard label="Worst Trade" value={formatCurrencyCompact(analytics.worstTrade)} positive={false} />
            </div>

            {/* Streak tracker */}
            <section aria-labelledby="perf-streak-label">
              <p id="perf-streak-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
                Streak Tracker
              </p>
              <div className="flex items-center gap-3 flex-wrap">
                <div className="flex flex-col items-center bg-surface-hover rounded px-3 py-1.5">
                  <span className="text-xxs text-text-muted">Current</span>
                  <span className={`text-sm font-bold font-mono ${streakColour}`} aria-label={`Current streak ${streakLabel}`}>
                    {streakLabel}
                  </span>
                </div>
                <div className="flex flex-col items-center bg-surface-hover rounded px-3 py-1.5">
                  <span className="text-xxs text-text-muted">Best Win</span>
                  <span className="text-sm font-bold font-mono text-profit">
                    W{longestWin}
                  </span>
                </div>
                <div className="flex flex-col items-center bg-surface-hover rounded px-3 py-1.5">
                  <span className="text-xxs text-text-muted">Worst Loss</span>
                  <span className="text-sm font-bold font-mono text-loss">
                    L{longestLoss}
                  </span>
                </div>
              </div>
            </section>

            {/* Monthly returns heatmap */}
            <section aria-labelledby="perf-monthly-label">
              <p id="perf-monthly-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
                Monthly Returns
              </p>
              <MonthlyHeatmap returns={monthlyReturns} />
            </section>

            {/* P&L by day of week — signed ₹ chart with trade counts (union of the
                Analytics tab's signed chart and the widget's count distribution) */}
            <Card className="bg-surface-card border-border-default">
              <CardHeader className="p-3 pb-1">
                <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
                  P&L by Day of Week
                </CardTitle>
              </CardHeader>
              <CardContent className="p-3 pt-1">
                <FlintSignedCategoricalBarChart
                  ariaLabel="Trade review P&L by day of week"
                  entries={dayOfWeekEntries}
                  valueFormatter={formatCurrencyCompact}
                  className="text-text-primary"
                />
                <div className="mt-2 grid grid-cols-5 gap-1 text-center">
                  {analytics.byDayOfWeek.map(({ day, count }) => (
                    <div key={day} className="text-xxs text-text-muted">
                      {count}t
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* P&L by symbol */}
            {analytics.bySymbol.length > 0 && (
              <Card className="bg-surface-card border-border-default">
                <CardHeader className="p-3 pb-1">
                  <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
                    P&L by Symbol
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-3 pt-1">
                  <FlintRankedBarList
                    ariaLabel="Trade review P&L by symbol"
                    entries={symbolPnlEntries}
                    valueFormatter={formatCurrencyCompact}
                  />
                  <div className="mt-2 space-y-1">
                    {analytics.bySymbol.map(({ symbol, trades: tradeCount }) => (
                      <div key={symbol} className="flex justify-between gap-2 text-xs text-text-muted">
                        <span className="truncate font-mono text-text-secondary">{symbol}</span>
                        <span className="shrink-0">{tradeCount}t</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}

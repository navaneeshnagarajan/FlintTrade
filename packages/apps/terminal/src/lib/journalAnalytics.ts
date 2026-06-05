/**
 * journalAnalytics — Pure calculation functions for Trade Journal analytics.
 *
 * All functions are pure (no side effects, no React), making them independently testable.
 * They operate on JournalTrade[] arrays from the FlintTrade backend.
 */

import type { JournalTrade } from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TradeAnalytics {
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
  byDayOfWeek: DayOfWeekPnl[];
  bySymbol: SymbolPnl[];
  currentStreak: number;
  streakType: "win" | "loss" | "none";
}

export interface DayOfWeekPnl {
  day: string;
  pnl: number;
  count: number;
}

export interface SymbolPnl {
  symbol: string;
  pnl: number;
  trades: number;
}

export interface WeeklyWinRate {
  /** ISO week label, e.g. "2026-W13" */
  week: string;
  winRate: number;
  wins: number;
  losses: number;
  total: number;
}

export interface MonthlyWinRate {
  /** Month label, e.g. "2026-03" */
  month: string;
  winRate: number;
  wins: number;
  losses: number;
  total: number;
}

export interface DayPnl {
  /** ISO date string, e.g. "2026-03-25" */
  date: string;
  pnl: number;
  tradeCount: number;
}

export interface HoldingTimeStats {
  avgMinutes: number;
  medianMinutes: number;
  minMinutes: number;
  maxMinutes: number;
}

export interface StreakRecord {
  type: "win" | "loss";
  length: number;
}

export interface RiskRewardBucket {
  /** Label like "0-0.5", "0.5-1", "1-1.5", etc. */
  label: string;
  count: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getClosedTrades(trades: JournalTrade[]): JournalTrade[] {
  // A trade counts as "closed" only once it has a realised, non-zero P&L. Live
  // manual fills are journalled with pnl=null (no round-trip yet) — `null !== 0`
  // is true, so without the numeric guard those open legs were treated as closed
  // and, via `pnl <= 0`, miscounted as LOSSES, distorting win-rate/profit-factor
  // for connected users. Exclude any non-numeric (null/undefined) P&L.
  return trades.filter((t) => typeof t.pnl === "number" && t.pnl !== 0);
}

function sortChronological(trades: JournalTrade[]): JournalTrade[] {
  return [...trades].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );
}

/** ISO week number (Mon=1) for a Date. */
function getISOWeek(d: Date): number {
  const tmp = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  tmp.setUTCDate(tmp.getUTCDate() + 4 - (tmp.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(tmp.getUTCFullYear(), 0, 1));
  return Math.ceil(((tmp.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}

function getISOWeekLabel(d: Date): string {
  const week = getISOWeek(d);
  // The ISO week year may differ from calendar year near Jan/Dec boundary
  const tmp = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  tmp.setUTCDate(tmp.getUTCDate() + 4 - (tmp.getUTCDay() || 7));
  const year = tmp.getUTCFullYear();
  return `${year}-W${String(week).padStart(2, "0")}`;
}

function getMonthLabel(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

function getDateLabel(d: Date): string {
  return d.toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Core analytics (existing, extracted)
// ---------------------------------------------------------------------------

export function computeAnalytics(trades: JournalTrade[]): TradeAnalytics {
  const closed = getClosedTrades(trades);

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
  const worstTrade = closed.length ? Math.min(...closed.map((t) => t.pnl)) : 0;

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

  // Streak
  const sorted = sortChronological(closed);
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

// ---------------------------------------------------------------------------
// Enhanced analytics — win rate over time
// ---------------------------------------------------------------------------

export function computeWeeklyWinRate(trades: JournalTrade[]): WeeklyWinRate[] {
  const closed = sortChronological(getClosedTrades(trades));
  const weekMap = new Map<string, { wins: number; losses: number }>();

  for (const t of closed) {
    const d = new Date(t.timestamp);
    const week = getISOWeekLabel(d);
    const entry = weekMap.get(week) ?? { wins: 0, losses: 0 };
    if (t.pnl > 0) entry.wins++;
    else entry.losses++;
    weekMap.set(week, entry);
  }

  return Array.from(weekMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([week, { wins, losses }]) => {
      const total = wins + losses;
      return {
        week,
        winRate: total > 0 ? (wins / total) * 100 : 0,
        wins,
        losses,
        total,
      };
    });
}

export function computeMonthlyWinRate(trades: JournalTrade[]): MonthlyWinRate[] {
  const closed = sortChronological(getClosedTrades(trades));
  const monthMap = new Map<string, { wins: number; losses: number }>();

  for (const t of closed) {
    const d = new Date(t.timestamp);
    const month = getMonthLabel(d);
    const entry = monthMap.get(month) ?? { wins: 0, losses: 0 };
    if (t.pnl > 0) entry.wins++;
    else entry.losses++;
    monthMap.set(month, entry);
  }

  return Array.from(monthMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, { wins, losses }]) => {
      const total = wins + losses;
      return {
        month,
        winRate: total > 0 ? (wins / total) * 100 : 0,
        wins,
        losses,
        total,
      };
    });
}

// ---------------------------------------------------------------------------
// Average P&L per trade
// ---------------------------------------------------------------------------

export function computeAvgPnlPerTrade(trades: JournalTrade[]): number {
  const closed = getClosedTrades(trades);
  if (closed.length === 0) return 0;
  return closed.reduce((s, t) => s + t.pnl, 0) / closed.length;
}

// ---------------------------------------------------------------------------
// Best / worst trading days
// ---------------------------------------------------------------------------

export function computeDayPnl(trades: JournalTrade[]): DayPnl[] {
  const closed = getClosedTrades(trades);
  const dayMap = new Map<string, { pnl: number; count: number }>();

  for (const t of closed) {
    const d = new Date(t.timestamp);
    const dateKey = getDateLabel(d);
    const entry = dayMap.get(dateKey) ?? { pnl: 0, count: 0 };
    entry.pnl += t.pnl;
    entry.count += 1;
    dayMap.set(dateKey, entry);
  }

  return Array.from(dayMap.entries())
    .map(([date, { pnl, count }]) => ({ date, pnl, tradeCount: count }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function getBestDays(dayPnls: DayPnl[], count: number = 5): DayPnl[] {
  return [...dayPnls].sort((a, b) => b.pnl - a.pnl).slice(0, count);
}

export function getWorstDays(dayPnls: DayPnl[], count: number = 5): DayPnl[] {
  return [...dayPnls].sort((a, b) => a.pnl - b.pnl).slice(0, count);
}

// ---------------------------------------------------------------------------
// Most profitable instruments
// ---------------------------------------------------------------------------

export function computeInstrumentPnl(trades: JournalTrade[]): SymbolPnl[] {
  const closed = getClosedTrades(trades);
  const symMap: Record<string, { pnl: number; trades: number }> = {};

  for (const t of closed) {
    if (!symMap[t.symbol]) symMap[t.symbol] = { pnl: 0, trades: 0 };
    symMap[t.symbol].pnl += t.pnl;
    symMap[t.symbol].trades += 1;
  }

  return Object.entries(symMap)
    .map(([symbol, v]) => ({ symbol, ...v }))
    .sort((a, b) => b.pnl - a.pnl);
}

// ---------------------------------------------------------------------------
// Average holding time
// ---------------------------------------------------------------------------

/**
 * Computes holding time stats from trades that have both entry and exit prices.
 * Uses the heuristic of pairing BUY/SELL trades on the same symbol chronologically.
 * For trades with exit_price > 0, we estimate hold time from same-day trade pairs.
 *
 * Note: This is an approximation. The backend doesn't provide entry/exit timestamps
 * as separate fields — all trades have a single `timestamp`. We group by symbol+date
 * and compute time between first and last trade of each group.
 */
export function computeHoldingTime(trades: JournalTrade[]): HoldingTimeStats {
  const closed = getClosedTrades(trades);

  // Group trades by symbol + date to find round-trips
  const groups = new Map<string, number[]>();
  for (const t of closed) {
    const d = new Date(t.timestamp);
    const key = `${t.symbol}_${getDateLabel(d)}`;
    const times = groups.get(key) ?? [];
    times.push(d.getTime());
    groups.set(key, times);
  }

  const durations: number[] = [];
  for (const times of groups.values()) {
    if (times.length < 2) continue;
    times.sort((a, b) => a - b);
    const holdMs = times[times.length - 1] - times[0];
    const holdMin = holdMs / 60000;
    if (holdMin > 0) durations.push(holdMin);
  }

  if (durations.length === 0) {
    return { avgMinutes: 0, medianMinutes: 0, minMinutes: 0, maxMinutes: 0 };
  }

  durations.sort((a, b) => a - b);
  const avg = durations.reduce((s, d) => s + d, 0) / durations.length;
  const mid = Math.floor(durations.length / 2);
  const median =
    durations.length % 2 === 0
      ? (durations[mid - 1] + durations[mid]) / 2
      : durations[mid];

  return {
    avgMinutes: avg,
    medianMinutes: median,
    minMinutes: durations[0],
    maxMinutes: durations[durations.length - 1],
  };
}

// ---------------------------------------------------------------------------
// Streak tracking (all consecutive win/loss streaks)
// ---------------------------------------------------------------------------

export function computeAllStreaks(trades: JournalTrade[]): StreakRecord[] {
  const sorted = sortChronological(getClosedTrades(trades));
  if (sorted.length === 0) return [];

  const streaks: StreakRecord[] = [];
  let currentType: "win" | "loss" = sorted[0].pnl > 0 ? "win" : "loss";
  let currentLen = 1;

  for (let i = 1; i < sorted.length; i++) {
    const type = sorted[i].pnl > 0 ? "win" : "loss";
    if (type === currentType) {
      currentLen++;
    } else {
      streaks.push({ type: currentType, length: currentLen });
      currentType = type;
      currentLen = 1;
    }
  }
  streaks.push({ type: currentType, length: currentLen });

  return streaks;
}

export function getLongestWinStreak(streaks: StreakRecord[]): number {
  return streaks
    .filter((s) => s.type === "win")
    .reduce((max, s) => Math.max(max, s.length), 0);
}

export function getLongestLossStreak(streaks: StreakRecord[]): number {
  return streaks
    .filter((s) => s.type === "loss")
    .reduce((max, s) => Math.max(max, s.length), 0);
}

// ---------------------------------------------------------------------------
// Risk-reward ratio distribution
// ---------------------------------------------------------------------------

/**
 * Computes risk-reward ratio for each winning trade as:
 *   RR = abs(pnl) / avg_loss
 *
 * Where avg_loss is the average loss across all trades (absolute value).
 * Groups results into buckets for histogram display.
 */
export function computeRiskRewardDistribution(
  trades: JournalTrade[],
): RiskRewardBucket[] {
  const closed = getClosedTrades(trades);
  const losses = closed.filter((t) => t.pnl < 0);
  const avgLossAbs =
    losses.length > 0
      ? Math.abs(losses.reduce((s, t) => s + t.pnl, 0) / losses.length)
      : 0;

  if (avgLossAbs === 0) return [];

  const wins = closed.filter((t) => t.pnl > 0);
  const ratios = wins.map((t) => t.pnl / avgLossAbs);

  // Bucket: 0-0.5, 0.5-1, 1-1.5, 1.5-2, 2-2.5, 2.5-3, 3+
  const bucketDefs: Array<{ label: string; min: number; max: number }> = [
    { label: "0-0.5R", min: 0, max: 0.5 },
    { label: "0.5-1R", min: 0.5, max: 1 },
    { label: "1-1.5R", min: 1, max: 1.5 },
    { label: "1.5-2R", min: 1.5, max: 2 },
    { label: "2-2.5R", min: 2, max: 2.5 },
    { label: "2.5-3R", min: 2.5, max: 3 },
    { label: "3R+", min: 3, max: Infinity },
  ];

  return bucketDefs.map(({ label, min, max }) => ({
    label,
    count: ratios.filter((r) => r >= min && r < max).length,
  }));
}

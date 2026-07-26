import { formatNumber } from "@/lib/formatters";
import { fromIstParts, istParts, istToday, toIstIsoDate } from "@/lib/ist";
import { type JournalTrade } from "@/services/ftApi";
import { type TiltStatus } from "./types";

export const NOTES_KEY = "flinttrade_journal_notes";

export function formatPrice(value: number): string {
  return formatNumber(value, 2);
}

export function formatDate(ts: string): string {
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

export function formatTime(ts: string): string {
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

export function pnlColor(value: number): string {
  if (value > 0) return "text-profit";
  if (value < 0) return "text-loss";
  return "text-text-secondary";
}

/**
 * The IST trading day (Asia/Kolkata) of an instant, as ``YYYY-MM-DD``.
 *
 * Daily notes must key on the Indian trading day, not the machine's UTC date:
 * ``toISOString()`` only turns over at 05:30 IST, so through the whole IST
 * early morning it still reports yesterday and notes are filed under the wrong
 * day. Delegates to ``@/lib/ist`` so the terminal has one IST implementation
 * rather than one per tool.
 *
 * @param now - Instant to convert; defaults to now.
 * @returns The ISO date of the IST trading day containing that instant.
 */
export function istDayKey(now: Date = new Date()): string {
  return toIstIsoDate(now);
}

/**
 * Today's IST trading day as ``YYYY-MM-DD`` — the default end of the journal range.
 *
 * @returns The current IST trading day.
 */
export function todayISO(): string {
  return istToday();
}

/**
 * The IST day seven trading-window days back — the default start of the range.
 *
 * Inclusive of today, so the default window spans seven IST calendar days.
 * Stepping the IST day number (rather than subtracting 6 × 24 hrs from the
 * host clock) keeps the boundary on the Indian calendar wherever the operator
 * is.
 *
 * @returns The ISO date six IST days before today.
 */
export function sevenDaysAgoISO(): string {
  const { year, month, day } = istParts();
  return toIstIsoDate(fromIstParts(year, month, day - 6));
}

export function formatMinutes(mins: number): string {
  if (mins < 1) return "<1m";
  if (mins < 60) return `${Math.round(mins)}m`;
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

export function detectTilt(trades: JournalTrade[]): TiltStatus {
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

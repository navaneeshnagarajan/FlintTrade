import { formatNumber } from "@/lib/formatters";
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

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export function sevenDaysAgoISO(): string {
  const d = new Date();
  d.setDate(d.getDate() - 6);
  return d.toISOString().slice(0, 10);
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

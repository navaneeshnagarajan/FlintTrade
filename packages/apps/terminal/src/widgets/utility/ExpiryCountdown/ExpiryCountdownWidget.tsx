/**
 * ExpiryCountdownWidget — Countdown to nearest F&O expiry dates.
 *
 * Features:
 *   - Three rows: weekly, monthly, quarterly expiry
 *   - Live countdown: days, hours, minutes, seconds (updates every second)
 *   - Colour-coded urgency: >7d green, 3-7d amber, <3d red, <1d blinking
 *   - Shows actual expiry date and day-of-week name
 *   - Pure client-side date maths; no API needed
 */

import { useState, useEffect, useMemo, memo } from "react";
import { Timer } from "lucide-react";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ExpiryKind = "Weekly" | "Monthly" | "Quarterly";

interface ExpiryRow {
  kind: ExpiryKind;
  date: Date;
}

// ---------------------------------------------------------------------------
// Expiry date calculations (NSE F&O rules)
//   Weekly  : nearest Thursday (weekly options expiry)
//   Monthly : last Thursday of the current/next month
//   Quarterly: last Thursday of Mar / Jun / Sep / Dec
// ---------------------------------------------------------------------------

function lastThursdayOf(year: number, month: number): Date {
  // month is 0-indexed (JS Date)
  const lastDay = new Date(year, month + 1, 0);
  const dayOfWeek = lastDay.getDay(); // 0=Sun, 4=Thu
  const offset = (dayOfWeek >= 4 ? dayOfWeek - 4 : dayOfWeek + 3);
  const d = new Date(year, month, lastDay.getDate() - offset);
  d.setHours(15, 30, 0, 0); // NSE closes at 15:30 IST
  return d;
}

function nextThursday(from: Date): Date {
  const d = new Date(from);
  const day = d.getDay();
  const daysUntilThursday = (4 - day + 7) % 7 || 7;
  d.setDate(d.getDate() + daysUntilThursday);
  d.setHours(15, 30, 0, 0);
  return d;
}

function nextQuarterlyMonth(month: number): number {
  // Quarterly expiry months: Mar(2), Jun(5), Sep(8), Dec(11)
  const qtrs = [2, 5, 8, 11];
  return qtrs.find((m) => m > month) ?? 2; // wraps to March next year
}

function computeExpiries(now: Date): ExpiryRow[] {
  const y = now.getFullYear();
  const m = now.getMonth();

  // Weekly: next Thursday
  const weekly = nextThursday(now);

  // Monthly: last Thursday of current month; if already past, use next month
  let monthly = lastThursdayOf(y, m);
  if (monthly <= now) {
    const nextM = m === 11 ? 0 : m + 1;
    const nextY = m === 11 ? y + 1 : y;
    monthly = lastThursdayOf(nextY, nextM);
  }

  // Quarterly: last Thursday of next quarterly month
  let qtrMonth = nextQuarterlyMonth(m - 1); // -1 to allow current month
  let qtrYear = y;
  if (qtrMonth <= m) qtrYear += 1;
  let quarterly = lastThursdayOf(qtrYear, qtrMonth);
  if (quarterly <= now) {
    qtrMonth = nextQuarterlyMonth(qtrMonth);
    if (qtrMonth <= (qtrYear === y ? m : -1)) qtrYear += 1;
    quarterly = lastThursdayOf(qtrYear, qtrMonth);
  }

  return [
    { kind: "Weekly", date: weekly },
    { kind: "Monthly", date: monthly },
    { kind: "Quarterly", date: quarterly },
  ];
}

// ---------------------------------------------------------------------------
// Countdown helpers
// ---------------------------------------------------------------------------

interface Countdown {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
  totalMs: number;
}

function countdownTo(target: Date, now: Date): Countdown {
  const diff = Math.max(0, target.getTime() - now.getTime());
  const totalMs = diff;
  const days = Math.floor(diff / 86_400_000);
  const hours = Math.floor((diff % 86_400_000) / 3_600_000);
  const minutes = Math.floor((diff % 3_600_000) / 60_000);
  const seconds = Math.floor((diff % 60_000) / 1000);
  return { days, hours, minutes, seconds, totalMs };
}

function urgencyClass(days: number, blinkEnabled: boolean): string {
  if (days < 1) return blinkEnabled ? "text-loss animate-pulse" : "text-loss";
  if (days < 3) return "text-loss";
  if (days <= 7) return "text-warning";
  return "text-profit";
}

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function formatDate(d: Date): string {
  return `${DAY_NAMES[d.getDay()]} ${d.getDate()} ${MONTH_NAMES[d.getMonth()]}`;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

// ---------------------------------------------------------------------------
// Expiry row component
// ---------------------------------------------------------------------------

interface ExpiryRowItemProps {
  row: ExpiryRow;
  now: Date;
  blink: boolean;
}

function ExpiryRowItem({ row, now, blink }: ExpiryRowItemProps) {
  const cd = countdownTo(row.date, now);
  const colour = urgencyClass(cd.days, blink);

  const countdownStr =
    cd.days > 0
      ? `${cd.days}d ${pad2(cd.hours)}h ${pad2(cd.minutes)}m`
      : `${pad2(cd.hours)}h ${pad2(cd.minutes)}m ${pad2(cd.seconds)}s`;

  const kindColour =
    row.kind === "Weekly"
      ? "text-accent"
      : row.kind === "Monthly"
      ? "text-text-secondary"
      : "text-text-muted";

  return (
    <div
      className="flex items-center gap-2 py-2.5 border-b border-border-default last:border-0"
      role="listitem"
      aria-label={`${row.kind} expiry on ${formatDate(row.date)}`}
    >
      {/* Kind badge */}
      <div className="w-20 shrink-0">
        <span className={`text-xs font-semibold ${kindColour}`}>{row.kind}</span>
      </div>

      {/* Date */}
      <div className="flex-1 min-w-0">
        <div className="text-xs text-text-primary font-medium">{formatDate(row.date)}</div>
        <div className="text-xxs text-text-muted">NSE F&amp;O Expiry</div>
      </div>

      {/* Countdown */}
      <div className="text-right shrink-0">
        <div
          className={`text-sm font-mono tabular-nums font-bold ${colour}`}
          aria-live="polite"
          aria-atomic="true"
        >
          {countdownStr}
        </div>
        {cd.days < 1 && (
          <div className="text-xxs text-loss font-medium">Expires today</div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function ExpiryCountdownWidget() {
  const track = useTrackBehavior();
  const [now, setNow] = useState(() => new Date());
  const [blink, setBlink] = useState(false);

  useEffect(() => {
    track("trade", "expiry_countdown_opened");
    const ticker = setInterval(() => {
      setNow(new Date());
      setBlink((b) => !b);
    }, 1000);
    return () => clearInterval(ticker);
  }, [track]);

  const expiries = useMemo(() => computeExpiries(now), [now]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Options Expiry Countdown widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Timer size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Expiry Countdown</span>
        <div className="flex-1" />
        <span className="text-xxs text-text-muted tabular-nums">
          {now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })} IST
        </span>
      </div>

      {/* Expiry rows */}
      <div
        className="flex-1 min-h-0 overflow-y-auto px-3"
        role="list"
        aria-label="Expiry countdown list"
      >
        {expiries.map((row) => (
          <ExpiryRowItem key={row.kind} row={row} now={now} blink={blink} />
        ))}
      </div>

      {/* Legend */}
      <div className="flex-none px-3 py-2 border-t border-border-default">
        <div className="flex items-center gap-3 text-xxs text-text-muted">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-profit inline-block" />
            &gt; 7d
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-warning inline-block" />
            3–7d
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-loss inline-block" />
            &lt; 3d
          </span>
          <span className="flex items-center gap-1 animate-pulse">
            <span className="w-2 h-2 rounded-full bg-loss inline-block" />
            &lt; 1d
          </span>
        </div>
      </div>
    </div>
  );
}

export default memo(ExpiryCountdownWidget);

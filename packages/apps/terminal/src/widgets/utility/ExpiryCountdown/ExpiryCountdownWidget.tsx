/**
 * ExpiryCountdownWidget: countdown to the nearest F&O expiry dates.
 *
 * Features:
 *   - Underlying switch: NIFTY (NSE) or SENSEX (BSE)
 *   - Three rows: weekly, monthly, quarterly expiry
 *   - Live countdown: days, hours, minutes, seconds (updates every second)
 *   - Colour-coded urgency: >7d green, 3-7d amber, <3d red, <1d blinking
 *   - Shows the actual expiry date and weekday, e.g. "Expires Tue 25 Nov"
 *
 * Every date comes from the exchange's contract list behind ``getExpiry``,
 * the same list the option chain uses. Nothing here assumes an expiry weekday:
 * NSE and BSE contracts expire on different days, and a holiday moves an
 * expiry to whatever date the list carries. When the list cannot be loaded the
 * widget says so instead of guessing a date. All countdown arithmetic is done
 * in IST via ``@/lib/ist``, so an operator outside India sees the same
 * countdown as one in Mumbai.
 */

import { useState, useEffect, useMemo, memo } from "react";
import { Timer } from "lucide-react";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { fmtDuration, fmtIstClock, istParts, splitDuration } from "@/lib/ist";
import { expiryScheduleFromList, parseExpiryList } from "@/lib/optionExpiry";
import type { ListedExpiry } from "@/lib/optionExpiry";
import { getExpiry } from "@/services/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ExpiryKind = "Weekly" | "Monthly" | "Quarterly";

export interface ExpiryRow {
  kind: ExpiryKind;
  /** The expiry's closing instant, or null when the list does not carry one. */
  date: Date | null;
}

/** Underlyings the widget can count down to, with their option segment. */
export const EXPIRY_UNDERLYINGS = [
  { symbol: "NIFTY", exchange: "NFO", venue: "NSE" },
  { symbol: "SENSEX", exchange: "BFO", venue: "BSE" },
] as const;

type Underlying = (typeof EXPIRY_UNDERLYINGS)[number];

type ListState =
  | { status: "loading" }
  | { status: "ready"; expiries: string[] }
  | { status: "error" };

// ---------------------------------------------------------------------------
// Expiry rows (read off the listed contracts, never computed)
// ---------------------------------------------------------------------------

/**
 * The three expiry rows for a contract list at a given instant.
 *
 * @param expiries - Expiry labels as ``getExpiry`` returned them.
 * @param now - The current instant.
 * @returns Weekly, monthly and quarterly rows; a row's date is null when the
 *   list carries no such contract.
 */
export function computeExpiries(expiries: readonly string[], now: Date): ExpiryRow[] {
  const schedule = expiryScheduleFromList(expiries, now);
  const close = (entry: ListedExpiry | null) => entry?.close ?? null;
  return [
    { kind: "Weekly", date: close(schedule.weekly) },
    { kind: "Monthly", date: close(schedule.monthly) },
    { kind: "Quarterly", date: close(schedule.quarterly) },
  ];
}

// ---------------------------------------------------------------------------
// Countdown helpers
// ---------------------------------------------------------------------------

function urgencyClass(days: number, blinkEnabled: boolean): string {
  if (days < 1) return blinkEnabled ? "text-loss animate-pulse" : "text-loss";
  if (days < 3) return "text-loss";
  if (days <= 7) return "text-warning";
  return "text-profit";
}

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Render an expiry instant as its IST calendar date, e.g. "Tue 25 Nov".
 *
 * @param d - The expiry instant.
 * @returns Weekday, day and month as read off the IST wall clock.
 */
export function formatExpiryDate(d: Date): string {
  const { day, month, weekday } = istParts(d);
  return `${DAY_NAMES[weekday]} ${day} ${MONTH_NAMES[month]}`;
}

// ---------------------------------------------------------------------------
// Expiry row component
// ---------------------------------------------------------------------------

interface ExpiryRowItemProps {
  row: ExpiryRow;
  underlying: Underlying;
  now: Date;
  blink: boolean;
}

function ExpiryRowItem({ row, underlying, now, blink }: ExpiryRowItemProps) {
  const kindColour =
    row.kind === "Weekly"
      ? "text-accent"
      : row.kind === "Monthly"
      ? "text-text-secondary"
      : "text-text-muted";
  const subLabel = `${underlying.symbol} · ${underlying.venue} F&O`;

  if (!row.date) {
    return (
      <div
        className="flex items-center gap-2 py-2.5 border-b border-border-default last:border-0"
        role="listitem"
        aria-label={`${underlying.symbol} ${row.kind.toLowerCase()} expiry not in the contract list`}
      >
        <div className="w-20 shrink-0">
          <span className={`text-xs font-semibold ${kindColour}`}>{row.kind}</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-text-muted">Not listed</div>
          <div className="text-xxs text-text-muted">{subLabel}</div>
        </div>
      </div>
    );
  }

  const remainingMs = row.date.getTime() - now.getTime();
  const cd = splitDuration(remainingMs);
  const colour = urgencyClass(cd.days, blink);
  const countdownStr = fmtDuration(remainingMs, { withSeconds: true });
  const dateText = `Expires ${formatExpiryDate(row.date)}`;

  return (
    <div
      className="flex items-center gap-2 py-2.5 border-b border-border-default last:border-0"
      role="listitem"
      aria-label={`${underlying.symbol} ${row.kind.toLowerCase()} expiry: ${dateText}`}
    >
      {/* Kind badge */}
      <div className="w-20 shrink-0">
        <span className={`text-xs font-semibold ${kindColour}`}>{row.kind}</span>
      </div>

      {/* Date */}
      <div className="flex-1 min-w-0">
        <div className="text-xs text-text-primary font-medium">{dateText}</div>
        <div className="text-xxs text-text-muted">{subLabel}</div>
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
  const [underlying, setUnderlying] = useState<Underlying>(EXPIRY_UNDERLYINGS[0]);
  const [list, setList] = useState<ListState>({ status: "loading" });

  useEffect(() => {
    track("trade", "expiry_countdown_opened");
    const ticker = setInterval(() => {
      setNow(new Date());
      setBlink((b) => !b);
    }, 1000);
    return () => clearInterval(ticker);
  }, [track]);

  useEffect(() => {
    const controller = new AbortController();
    setList({ status: "loading" });
    getExpiry(underlying.symbol, underlying.exchange, "options", controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setList({ status: "ready", expiries: parseExpiryList(data) });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setList({ status: "error" });
      });
    return () => controller.abort();
  }, [underlying]);

  const expiries = useMemo(
    () => (list.status === "ready" ? computeExpiries(list.expiries, now) : []),
    [list, now],
  );
  const hasAnyDate = expiries.some((row) => row.date !== null);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Options Expiry Countdown widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Timer size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Expiry Countdown</span>
        <div className="flex items-center gap-0.5" role="group" aria-label="Underlying">
          {EXPIRY_UNDERLYINGS.map((option) => (
            <button
              key={option.symbol}
              type="button"
              aria-pressed={option.symbol === underlying.symbol}
              onClick={() => setUnderlying(option)}
              className={`px-1.5 py-0.5 text-xxs rounded border ${
                option.symbol === underlying.symbol
                  ? "bg-accent/15 text-accent border-accent/40"
                  : "text-text-muted border-transparent hover:text-text-primary"
              }`}
            >
              {option.symbol}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        <span className="text-xxs text-text-muted tabular-nums">
          {fmtIstClock(now)} IST
        </span>
      </div>

      {/* Expiry rows */}
      <div
        className="flex-1 min-h-0 overflow-y-auto px-3"
        role="list"
        aria-label="Expiry countdown list"
        aria-busy={list.status === "loading"}
      >
        {expiries.map((row) => (
          <ExpiryRowItem key={row.kind} row={row} underlying={underlying} now={now} blink={blink} />
        ))}
      </div>

      {/* Where the dates come from, or why there are none. */}
      <div className="flex-none px-3 py-1.5 border-t border-border-default">
        {list.status === "loading" && (
          <p className="text-xxs text-text-muted leading-snug" role="status">
            Loading {underlying.symbol} expiries…
          </p>
        )}
        {list.status === "error" && (
          <p className="text-xxs text-warning leading-snug" role="status">
            Couldn&apos;t load the {underlying.symbol} expiry list. No dates are shown until it loads.
          </p>
        )}
        {list.status === "ready" && (
          <p className="text-xxs text-text-muted leading-snug" role="status">
            {hasAnyDate
              ? `Dates from the ${underlying.venue} ${underlying.symbol} contract list.`
              : `No upcoming ${underlying.symbol} expiries in the contract list.`}
          </p>
        )}
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

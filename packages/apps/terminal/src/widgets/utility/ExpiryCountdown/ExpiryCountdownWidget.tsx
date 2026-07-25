/**
 * ExpiryCountdownWidget — Countdown to nearest F&O expiry dates.
 *
 * Features:
 *   - Three rows: weekly, monthly, quarterly expiry
 *   - Live countdown: days, hours, minutes, seconds (updates every second)
 *   - Colour-coded urgency: >7d green, 3-7d amber, <3d red, <1d blinking
 *   - Shows actual expiry date and day-of-week name
 *   - Pure client-side date maths, done entirely in IST via ``@/lib/ist``; no
 *     API needed. Every expiry instant is anchored to the NSE close in IST, so
 *     an operator running the terminal outside India sees the same countdown
 *     as one sitting in Mumbai.
 *
 * MAINTAINER ACTION — the expiry weekday needs confirming. The exchange rule
 * encoded by {@link NSE_EXPIRY_WEEKDAY} below is Thursday, which is what this
 * widget has always assumed, but NSE has revised the weekly-expiry weekday
 * since 2023 and SEBI/NSE may revise it again. Nothing in this repository
 * pins the current rule, so the constant records the assumption rather than a
 * verified fact: confirm it against the latest NSE circular and, when it
 * moves, change that one constant — the weekly, monthly and quarterly
 * calculations all derive from it.
 *
 * Until then the uncertainty is rendered, not just commented: the header
 * carries an amber "Assumed <day>" badge — the same affordance sibling widgets
 * use for unverified figures — and {@link EXPIRY_ASSUMPTION_NOTE} is printed
 * in full above the legend. Both are unconditional; a live broker connection
 * does not make the assumption true. The authoritative alternative is the
 * broker/symbol-master expiry list behind ``getExpiry`` in ``@/services/api``
 * (already used by the option-chain surfaces); wiring it here would need a
 * symbol/exchange input this widget does not currently take.
 */

import { useState, useEffect, useMemo, memo } from "react";
import { Timer } from "lucide-react";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import {
  fmtDuration,
  fmtIstClock,
  fromIstParts,
  istParts,
  lastIstWeekdayOfMonth,
  splitDuration,
} from "@/lib/ist";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ExpiryKind = "Weekly" | "Monthly" | "Quarterly";

interface ExpiryRow {
  kind: ExpiryKind;
  date: Date;
}

// ---------------------------------------------------------------------------
// Exchange rules
// ---------------------------------------------------------------------------

/**
 * Weekday on which NSE F&O contracts expire, as a JS weekday index
 * (0 = Sunday … 4 = Thursday … 6 = Saturday).
 *
 * Encodes the rule "NSE index and stock derivatives expire on Thursday". That
 * is the behaviour this widget has shipped since it was written and it is
 * preserved here deliberately — the value has been made explicit, NOT
 * re-derived. Last verified: 2026-07-25, and only as "this is what the widget
 * already assumed"; it has NOT been checked against a current NSE circular,
 * and NSE moved the weekly-expiry weekday at least once after 2023. A
 * maintainer must confirm it before it is relied on.
 *
 * Moving it is a one-line change: weekly, monthly and quarterly expiries are
 * all computed from this constant.
 */
export const NSE_EXPIRY_WEEKDAY = 4;

/** Hour of the NSE close in IST — the moment a contract actually expires. */
const NSE_CLOSE_HOUR = 15;

/** Minute of the NSE close in IST. */
const NSE_CLOSE_MINUTE = 30;

/** Months carrying a quarterly contract: March, June, September, December. */
const QUARTERLY_MONTHS: readonly number[] = [2, 5, 8, 11];

// ---------------------------------------------------------------------------
// Expiry date calculations (NSE F&O rules, all in IST)
//   Weekly   : the coming NSE_EXPIRY_WEEKDAY, today included until 15:30 IST
//   Monthly  : last NSE_EXPIRY_WEEKDAY of the current/next month
//   Quarterly: last NSE_EXPIRY_WEEKDAY of the next Mar / Jun / Sep / Dec
// ---------------------------------------------------------------------------

/**
 * The instant of the NSE close on a given IST calendar date.
 *
 * @param year - Full year in IST.
 * @param month - Month index in IST, 0 = January.
 * @param day - Day of the month in IST; out-of-range values roll over.
 * @returns The real instant of 15:30 IST on that date.
 */
function expiryInstant(year: number, month: number, day: number): Date {
  return fromIstParts(year, month, day, NSE_CLOSE_HOUR, NSE_CLOSE_MINUTE);
}

/**
 * The last {@link NSE_EXPIRY_WEEKDAY} of an IST calendar month, at the close.
 *
 * @param year - Full year in IST.
 * @param month - Month index in IST, 0 = January.
 * @returns The month's final expiry instant.
 */
function lastExpiryDayOf(year: number, month: number): Date {
  // The calendar arithmetic lives in @/lib/ist; this function only supplies the
  // exchange rule (which weekday, which close) on top of it.
  return lastIstWeekdayOfMonth(
    year,
    month,
    NSE_EXPIRY_WEEKDAY,
    NSE_CLOSE_HOUR,
    NSE_CLOSE_MINUTE,
  );
}

/**
 * The next weekly expiry, counting the current day until its close has passed.
 *
 * @param now - The current instant.
 * @returns The next weekly expiry instant, strictly in the future.
 */
function nextWeeklyExpiry(now: Date): Date {
  const { year, month, day, weekday } = istParts(now);
  const daysUntilExpiry = (NSE_EXPIRY_WEEKDAY - weekday + 7) % 7;
  const candidate = expiryInstant(year, month, day + daysUntilExpiry);
  // On expiry day itself the contract is live until 15:30 IST, so only roll a
  // week forward once that moment has genuinely passed. The old `|| 7` guard
  // rolled forward from midnight, hiding the expiring contract for the whole
  // of its final trading session.
  if (candidate.getTime() > now.getTime()) return candidate;
  return expiryInstant(year, month, day + daysUntilExpiry + 7);
}

/**
 * The next monthly expiry, counting the current month until its close has passed.
 *
 * @param now - The current instant.
 * @returns The next monthly expiry instant, strictly in the future.
 */
function nextMonthlyExpiry(now: Date): Date {
  const { year, month } = istParts(now);
  const candidate = lastExpiryDayOf(year, month);
  if (candidate.getTime() > now.getTime()) return candidate;
  return lastExpiryDayOf(month === 11 ? year + 1 : year, month === 11 ? 0 : month + 1);
}

/**
 * The next quarterly expiry.
 *
 * Walks forward month by month and returns the first quarter-end expiry still
 * in the future. The previous implementation added a year whenever the chosen
 * quarterly month was not strictly after the current one, which is exactly the
 * case in every quarter-end month — so in December it advertised December of
 * the following year, and likewise in March, June and September.
 *
 * @param now - The current instant.
 * @returns The next quarterly expiry instant, strictly in the future.
 */
function nextQuarterlyExpiry(now: Date): Date {
  const { year, month } = istParts(now);
  for (let step = 0; step <= 12; step += 1) {
    const absoluteMonth = month + step;
    const candidateMonth = absoluteMonth % 12;
    if (!QUARTERLY_MONTHS.includes(candidateMonth)) continue;
    const candidate = lastExpiryDayOf(year + Math.floor(absoluteMonth / 12), candidateMonth);
    if (candidate.getTime() > now.getTime()) return candidate;
  }
  // Unreachable: a quarter end falls at least every three months, so one of the
  // thirteen candidates above is always in the future. Kept as a total
  // fallback so the widget can never render undefined.
  return lastExpiryDayOf(year + 1, QUARTERLY_MONTHS[0]);
}

/**
 * The three expiry rows the widget renders, newest first.
 *
 * @param now - The current instant.
 * @returns Weekly, monthly and quarterly expiry instants, each in the future.
 */
export function computeExpiries(now: Date): ExpiryRow[] {
  return [
    { kind: "Weekly", date: nextWeeklyExpiry(now) },
    { kind: "Monthly", date: nextMonthlyExpiry(now) },
    { kind: "Quarterly", date: nextQuarterlyExpiry(now) },
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

/** The assumed expiry weekday's short name, derived from the one constant. */
export const EXPIRY_WEEKDAY_NAME = DAY_NAMES[NSE_EXPIRY_WEEKDAY];

/**
 * The caveat shown to the operator, in the widget and as the badge tooltip.
 *
 * The countdown arithmetic is exact, but it counts down to a weekday this
 * repository has NOT verified, so the widget must not present the date as
 * fact.
 */
export const EXPIRY_ASSUMPTION_NOTE =
  `Dates assume NSE F&O contracts expire on ${EXPIRY_WEEKDAY_NAME} — a configured `
  + "assumption, not a verified exchange rule. Confirm the expiry against your broker's "
  + "contract master or the current NSE circular before trading it.";

/**
 * Render an expiry instant as its IST calendar date, e.g. "Thu 31 Jul".
 *
 * @param d - The expiry instant.
 * @returns Weekday, day and month as read off the IST wall clock.
 */
function formatDate(d: Date): string {
  const { day, month, weekday } = istParts(d);
  return `${DAY_NAMES[weekday]} ${day} ${MONTH_NAMES[month]}`;
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
  const remainingMs = row.date.getTime() - now.getTime();
  const cd = splitDuration(remainingMs);
  const colour = urgencyClass(cd.days, blink);
  const countdownStr = fmtDuration(remainingMs, { withSeconds: true });

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
      aria-label={
        `${row.kind} expiry on ${formatDate(row.date)} `
        + `(assumed ${EXPIRY_WEEKDAY_NAME} expiry, not verified against the NSE calendar)`
      }
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
        {/* Honest disclosure — the dates below are computed from
            NSE_EXPIRY_WEEKDAY, an assumption this repository has never checked
            against a circular. Same amber affordance sibling widgets use for
            unverified figures, and deliberately unconditional: there is no
            connected state in which the assumption becomes a fact. */}
        <span
          className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded shrink-0"
          role="status"
          aria-label={EXPIRY_ASSUMPTION_NOTE}
          title={EXPIRY_ASSUMPTION_NOTE}
        >
          Assumed {EXPIRY_WEEKDAY_NAME}
        </span>
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
      >
        {expiries.map((row) => (
          <ExpiryRowItem key={row.kind} row={row} now={now} blink={blink} />
        ))}
      </div>

      {/* Expiry-weekday caveat — spelled out in full, because the badge alone
          cannot say which weekday is assumed or what to check it against. */}
      <div className="flex-none px-3 py-1.5 border-t border-border-default">
        <p className="text-xxs text-warning leading-snug">{EXPIRY_ASSUMPTION_NOTE}</p>
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

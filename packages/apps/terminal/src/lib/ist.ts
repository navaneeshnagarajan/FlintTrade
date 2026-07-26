/**
 * ist — the single IST (Asia/Kolkata) time and date module for the terminal.
 *
 * India Standard Time is a fixed UTC+05:30 offset with no daylight saving, so
 * every conversion here is plain epoch arithmetic: shift an instant by
 * {@link IST_OFFSET_MINUTES} and read it back with the **UTC** getters. The UTC
 * getters ignore the host's own zone, so the result is the Indian wall clock
 * whichever timezone the operator's machine is set to.
 *
 * Widgets that reason about the trading day MUST come through here. The two
 * idioms this module replaces are both silently wrong off-IST:
 *
 *   - browser-local maths — ``new Date(y, m, d)``, ``setHours(15, 30)`` — which
 *     pins 15:30 to the operator's own zone rather than the NSE close;
 *   - ``toISOString().slice(0, 10)`` — which yields the **UTC** calendar day.
 *     IST is never behind UTC, so the two calendars agree for most of the day
 *     and diverge in one window: UTC midnight falls at 05:30 IST, so from
 *     00:00 to 05:29 IST the UTC day is still YESTERDAY's date. A "today"
 *     derived that way therefore turns over 5½ hrs LATE — through the whole IST
 *     early morning it reports the previous day, and nothing it produces is
 *     ever a day ahead.
 *
 * Exchange-calendar policy (which weekday contracts expire on, which days are
 * holidays) deliberately does NOT live here — that is exchange rule-making, not
 * timezone arithmetic. Calendar primitives that take the weekday as an argument
 * (see {@link lastIstWeekdayOfMonth}) are fair game; the choice of weekday is
 * the caller's. See ``NSE_EXPIRY_WEEKDAY`` in ExpiryCountdownWidget, which still
 * needs maintainer confirmation against current NSE circulars.
 */

/** Minutes that IST runs ahead of UTC. Fixed: India observes no daylight saving. */
export const IST_OFFSET_MINUTES = 330;

const MS_PER_MINUTE = 60_000;
const MS_PER_SECOND = 1_000;
const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3_600;
const SECONDS_PER_DAY = 86_400;

const IST_OFFSET_MS = IST_OFFSET_MINUTES * MS_PER_MINUTE;

/** Break an instant into the fields of the IST wall clock. */
export interface IstParts {
  /** Full year, e.g. 2026. */
  year: number;
  /** Month index, 0 = January … 11 = December (JS ``Date`` convention). */
  month: number;
  /** Day of the month, 1–31. */
  day: number;
  /** Hour of the day, 0–23. */
  hour: number;
  /** Minute of the hour, 0–59. */
  minute: number;
  /** Second of the minute, 0–59. */
  second: number;
  /** Day of the week, 0 = Sunday … 6 = Saturday. */
  weekday: number;
}

/** Shift a real instant into IST wall-clock space (read it with the UTC getters). */
function shiftToIst(date: Date): Date {
  return new Date(date.getTime() + IST_OFFSET_MS);
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/**
 * The current instant shifted into IST wall-clock space.
 *
 * The returned Date's **UTC** getters (``getUTCFullYear``, ``getUTCHours``, …)
 * read the Asia/Kolkata wall clock wherever the browser is. Its epoch value is
 * deliberately offset by {@link IST_OFFSET_MINUTES}, so never subtract it from a
 * real instant — use ``new Date()`` for elapsed-time arithmetic and
 * {@link istParts} for calendar reads.
 *
 * @returns A Date whose UTC fields spell out the current IST wall clock.
 */
export function istNow(): Date {
  return shiftToIst(new Date());
}

/**
 * Break an instant into its IST wall-clock fields.
 *
 * @param date - Instant to convert; defaults to now.
 * @returns The year/month/day/hour/minute/second/weekday as seen in IST.
 */
export function istParts(date: Date = new Date()): IstParts {
  const shifted = shiftToIst(date);
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth(),
    day: shifted.getUTCDate(),
    hour: shifted.getUTCHours(),
    minute: shifted.getUTCMinutes(),
    second: shifted.getUTCSeconds(),
    weekday: shifted.getUTCDay(),
  };
}

/**
 * Minutes elapsed since IST midnight, with seconds carried as a fraction.
 *
 * The fractional tail keeps session progress bars smooth between whole minutes.
 *
 * @param date - Instant to convert; defaults to now.
 * @returns Minutes since 00:00 IST, in the half-open range [0, 1440).
 */
export function istMinutes(date: Date = new Date()): number {
  const { hour, minute, second } = istParts(date);
  return hour * 60 + minute + second / SECONDS_PER_MINUTE;
}

/**
 * The IST calendar day of an instant as ``YYYY-MM-DD``.
 *
 * Replaces ``toISOString().slice(0, 10)``, which returns the UTC calendar day.
 * UTC midnight is 05:30 IST, so that idiom reports YESTERDAY for every instant
 * between 00:00 and 05:29 IST — it turns over to the new day 5½ hrs late. It is
 * never a day ahead: IST leads UTC, so the error only ever runs backwards.
 *
 * @param date - Instant to convert.
 * @returns The ISO date of the IST trading day containing that instant.
 */
export function toIstIsoDate(date: Date): string {
  return shiftToIst(date).toISOString().slice(0, 10);
}

/**
 * Today's IST calendar day as ``YYYY-MM-DD``.
 *
 * @returns The current IST trading day, for comparison against ISO date keys.
 */
export function istToday(): string {
  return toIstIsoDate(new Date());
}

/**
 * The real instant at a given IST wall-clock date and time.
 *
 * The inverse of {@link istParts}. Day, hour and minute values outside their
 * natural range roll over exactly as ``Date.UTC`` does, so ``day + 7`` is a safe
 * way to step a week forward across a month boundary.
 *
 * @param year - Full year, e.g. 2026.
 * @param month - Month index, 0 = January … 11 = December.
 * @param day - Day of the month.
 * @param hour - Hour of the day in IST; defaults to midnight.
 * @param minute - Minute of the hour in IST; defaults to zero.
 * @param second - Second of the minute in IST; defaults to zero.
 * @returns A Date at the true instant of that IST wall-clock reading.
 */
export function fromIstParts(
  year: number,
  month: number,
  day: number,
  hour = 0,
  minute = 0,
  second = 0,
): Date {
  return new Date(Date.UTC(year, month, day, hour, minute, second) - IST_OFFSET_MS);
}

/**
 * The last occurrence of a given weekday in an IST calendar month.
 *
 * Pure calendar arithmetic — the caller says which weekday it wants, so no
 * exchange rule is encoded here. Contract calendars ("the monthly F&O expiry is
 * the last Thursday") are built on top of this by passing their own weekday
 * constant; that keeps the rule in one reviewable place and the date maths in
 * one tested place.
 *
 * Month indices outside 0–11 roll over exactly as ``Date.UTC`` does, so
 * ``month + 1`` is a safe way to step into January of the next year.
 *
 * @param year - Full year in IST.
 * @param month - Month index in IST, 0 = January … 11 = December.
 * @param weekday - Day of the week, 0 = Sunday … 6 = Saturday.
 * @param hour - Hour of the day in IST; defaults to midnight.
 * @param minute - Minute of the hour in IST; defaults to zero.
 * @returns The real instant of that IST wall-clock reading.
 */
export function lastIstWeekdayOfMonth(
  year: number,
  month: number,
  weekday: number,
  hour = 0,
  minute = 0,
): Date {
  // Day 0 of the following month is the last day of this one. Date.UTC is used
  // purely as zone-free calendar arithmetic on the day numbers — the result is
  // anchored back into IST by fromIstParts, so nothing here reads the host zone.
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const lastWeekday = new Date(Date.UTC(year, month, lastDay)).getUTCDay();
  const offset = (lastWeekday - weekday + 7) % 7;
  return fromIstParts(year, month, lastDay - offset, hour, minute);
}

/**
 * The IST wall clock of an instant as ``HH:MM:SS``.
 *
 * The shared header-clock rendering: every widget that shows "… IST" in its
 * title bar formats it here rather than reaching for ``toLocaleTimeString``,
 * whose 24-hour midnight rendering varies with the host's ICU build.
 *
 * @param date - Instant to render; defaults to now.
 * @returns Zero-padded 24-hour IST time, without the "IST" suffix.
 */
export function fmtIstClock(date: Date = new Date()): string {
  const { hour, minute, second } = istParts(date);
  return `${pad2(hour)}:${pad2(minute)}:${pad2(second)}`;
}

/** A duration split into whole days, hours, minutes and seconds. */
export interface DurationParts {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
  /** The original duration, clamped at zero. */
  totalMs: number;
}

/**
 * Split a duration into whole days, hours, minutes and seconds.
 *
 * @param ms - Duration in milliseconds; negatives clamp to zero.
 * @returns The duration decomposed into calendar-free units.
 */
export function splitDuration(ms: number): DurationParts {
  const totalMs = Math.max(0, ms);
  const totalSec = Math.floor(totalMs / MS_PER_SECOND);
  return {
    days: Math.floor(totalSec / SECONDS_PER_DAY),
    hours: Math.floor((totalSec % SECONDS_PER_DAY) / SECONDS_PER_HOUR),
    minutes: Math.floor((totalSec % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE),
    seconds: totalSec % SECONDS_PER_MINUTE,
    totalMs,
  };
}

/** Options for {@link fmtDuration}. */
export interface DurationFormatOptions {
  /**
   * Keep the seconds field even once hours are in play.
   *
   * Expiry countdowns want the seconds ticking through the final session;
   * session clocks, which only ever count down a few hours, do not.
   */
  withSeconds?: boolean;
}

/**
 * Format a duration as a compact countdown string.
 *
 * Drops the leading unit as soon as it reaches zero, so the string never grows
 * past three fields: ``3d 04h 12m`` → ``4h 12m`` → ``12m 30s`` → ``30s``. With
 * ``withSeconds`` the sub-day form becomes ``04h 12m 30s`` instead.
 *
 * @param ms - Duration in milliseconds; negatives render as ``0s``.
 * @param options - Formatting options; see {@link DurationFormatOptions}.
 * @returns The formatted countdown.
 */
export function fmtDuration(ms: number, options: DurationFormatOptions = {}): string {
  const { days, hours, minutes, seconds } = splitDuration(ms);
  if (days > 0) return `${days}d ${pad2(hours)}h ${pad2(minutes)}m`;
  if (options.withSeconds) return `${pad2(hours)}h ${pad2(minutes)}m ${pad2(seconds)}s`;
  if (hours > 0) return `${hours}h ${pad2(minutes)}m`;
  if (minutes > 0) return `${minutes}m ${pad2(seconds)}s`;
  return `${seconds}s`;
}

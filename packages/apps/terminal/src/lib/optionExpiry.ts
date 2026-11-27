/**
 * Shared option-expiry helpers for Option Chain and OI Chart.
 *
 * Both surfaces must parse `/expiry` the same way and pick the same default
 * (the nearest listed expiry) so Explore and live never disagree about the
 * contract they are showing.
 *
 * The expiry calendar itself is never computed here: which weekday a contract
 * expires on, and how a holiday moves it, is whatever the exchange's contract
 * list says. These helpers only read dates off that list.
 */

import { fromIstParts, toIstIsoDate } from "@/lib/ist";
import { parseExpiryEpoch } from "@/lib/optionSymbols";

/** Opaque identity for a symbol/exchange under one market-data authority. */
export function optionExpiryIdentity(
  dataScope: string,
  symbol: string,
  exchange: string,
): string {
  return `${dataScope}:${symbol}:${exchange}`;
}

/** Normalise a `getExpiry` payload into trimmed, non-blank expiry strings. */
export function parseExpiryList(data: unknown): string[] {
  const rawList = Array.isArray(data)
    ? data
    : ((data as { expiry?: unknown[] } | null | undefined)?.expiry ?? []);
  return rawList.flatMap((value) => {
    if (typeof value !== "string") return [];
    const expiry = value.trim();
    return expiry ? [expiry] : [];
  });
}

/**
 * Prefer the shared selection when it is still listed; otherwise the nearest
 * listed expiry (first in the broker/sample list).
 */
export function pickListedExpiry(
  expiries: readonly string[],
  preferred: string | null | undefined,
): string | null {
  const candidate = typeof preferred === "string" ? preferred.trim() : "";
  if (candidate && expiries.includes(candidate)) return candidate;
  return expiries[0] ?? null;
}

/**
 * The derivatives segment that lists option contracts for an underlying's
 * exchange, or null when the exchange has no option list.
 *
 * Charts and widgets are handed the underlying's own exchange (``NSE_INDEX``,
 * ``BSE``…); the expiry list lives on the derivatives segment.
 */
export function derivativesExchangeFor(exchange: string): string | null {
  const key = exchange.trim().toUpperCase();
  if (key === "NFO" || key === "NSE" || key === "NSE_INDEX") return "NFO";
  if (key === "BFO" || key === "BSE" || key === "BSE_INDEX") return "BFO";
  if (key === "MCX") return "MCX";
  return null;
}

/** Hour and minute (IST) at which an expiring contract stops trading. */
const EXPIRY_CLOSE_HOUR = 15;
const EXPIRY_CLOSE_MINUTE = 30;

/** One listed expiry, read off the contract list. */
export interface ListedExpiry {
  /** The label exactly as the list carried it. */
  readonly label: string;
  /** The expiry's IST calendar date as ``YYYY-MM-DD``. */
  readonly iso: string;
  /** IST year of the expiry date. */
  readonly year: number;
  /** IST month index of the expiry date, 0 = January. */
  readonly month: number;
  /** The instant the expiring contract stops trading (15:30 IST). */
  readonly close: Date;
}

/**
 * Parse, de-duplicate and sort a listed-expiry payload, oldest first.
 * Labels that are not real calendar dates are dropped.
 */
export function listedExpiries(labels: readonly string[]): ListedExpiry[] {
  const byIso = new Map<string, ListedExpiry>();
  for (const label of labels) {
    const epoch = parseExpiryEpoch(label);
    if (epoch === null) continue;
    const day = new Date(epoch);
    const year = day.getUTCFullYear();
    const month = day.getUTCMonth();
    const close = fromIstParts(year, month, day.getUTCDate(), EXPIRY_CLOSE_HOUR, EXPIRY_CLOSE_MINUTE);
    const iso = toIstIsoDate(close);
    if (!byIso.has(iso)) byIso.set(iso, { label, iso, year, month, close });
  }
  return [...byIso.values()].sort((a, b) => a.close.getTime() - b.close.getTime());
}

/**
 * The nearest listed expiry whose IST date is today or later. The expiring
 * contract is kept for the whole of its own expiry day, so a chart can still
 * show that session's open interest after the close.
 */
export function nearestListedExpiry(
  labels: readonly string[],
  now: Date = new Date(),
): ListedExpiry | null {
  const today = toIstIsoDate(now);
  return listedExpiries(labels).find((entry) => entry.iso >= today) ?? null;
}

/** Months that carry a quarterly contract: March, June, September, December. */
const QUARTERLY_MONTHS: ReadonlySet<number> = new Set([2, 5, 8, 11]);

/** The weekly, monthly and quarterly contracts read off one expiry list. */
export interface ListedExpirySchedule {
  readonly weekly: ListedExpiry | null;
  readonly monthly: ListedExpiry | null;
  readonly quarterly: ListedExpiry | null;
}

/**
 * Weekly, monthly and quarterly expiries from a contract list.
 *
 * - Weekly: the nearest contract still trading (today's until its close).
 * - Monthly: the last listed contract of the nearest calendar month.
 * - Quarterly: the last listed contract of the nearest March, June,
 *   September or December.
 *
 * A month only counts once the list carries a later month too, so a list that
 * stops part-way through a month can never pass off a weekly as the monthly.
 * Holiday-shifted contracts need no special case: the list already carries
 * the shifted date.
 */
export function expiryScheduleFromList(
  labels: readonly string[],
  now: Date = new Date(),
): ListedExpirySchedule {
  const upcoming = listedExpiries(labels).filter((entry) => entry.close.getTime() > now.getTime());
  const monthKey = (entry: ListedExpiry) => entry.year * 12 + entry.month;
  const lastOfMonth = (key: number): ListedExpiry | null => {
    const inMonth = upcoming.filter((entry) => monthKey(entry) === key);
    const listsLaterMonth = upcoming.some((entry) => monthKey(entry) > key);
    return inMonth.length > 0 && listsLaterMonth ? inMonth[inMonth.length - 1] : null;
  };
  const months = [...new Set(upcoming.map(monthKey))];
  const monthly = months.length > 0 ? lastOfMonth(months[0]) : null;
  const quarterKey = months.find((key) => QUARTERLY_MONTHS.has(key % 12));
  const quarterly = quarterKey === undefined ? null : lastOfMonth(quarterKey);
  return { weekly: upcoming[0] ?? null, monthly, quarterly };
}

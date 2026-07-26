export type OptionType = "CE" | "PE";

const COMPACT_EXPIRY_RE = /^(\d{1,2})([A-Z]{3})(\d{2}|\d{4})$/i;
const DASHED_EXPIRY_RE = /^(\d{1,2})-([A-Z]{3})-(\d{2}|\d{4})$/i;
const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})/;

function compactExpiry(day: string | number, month: string, year: string | number): string {
  const dd = String(day).padStart(2, "0");
  const mon = String(month).slice(0, 3).toUpperCase();
  const yy = String(year).slice(-2);
  return `${dd}${mon}${yy}`;
}

function compactExpiryFromDate(date: Date): string {
  const dd = String(date.getUTCDate()).padStart(2, "0");
  const mon = date.toLocaleString("en-US", { month: "short", timeZone: "UTC" }).toUpperCase();
  const yy = String(date.getUTCFullYear()).slice(-2);
  return `${dd}${mon}${yy}`;
}

export function normaliseExpiryForOptionSymbol(expiry: string): string {
  const trimmed = expiry.trim();
  if (!trimmed) return "";

  const compact = COMPACT_EXPIRY_RE.exec(trimmed);
  if (compact) {
    return compactExpiry(compact[1], compact[2], compact[3]);
  }

  const dashed = DASHED_EXPIRY_RE.exec(trimmed);
  if (dashed) {
    return compactExpiry(dashed[1], dashed[2], dashed[3]);
  }

  const iso = ISO_DATE_RE.exec(trimmed);
  if (iso) {
    return compactExpiryFromDate(new Date(Date.UTC(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]))));
  }

  const date = new Date(trimmed);
  if (isNaN(date.getTime())) return trimmed.toUpperCase();
  return compactExpiryFromDate(date);
}

const EXPIRY_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/**
 * Parse an expiry label ("2026-07-30", "30JUL26", "30-JUL-26") to a UTC epoch,
 * or null when it is not a real calendar date.
 */
function expiryEpoch(expiry: string): number | null {
  const value = expiry.trim().toUpperCase();
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const market = /^(\d{2})-?([A-Z]{3})-?(\d{2}|\d{4})$/.exec(value);
  const year = iso ? Number(iso[1]) : market ? Number(market[3]) + (market[3].length === 2 ? 2000 : 0) : NaN;
  const month = iso ? Number(iso[2]) - 1 : market ? EXPIRY_MONTHS.indexOf(market[2]) : NaN;
  const day = iso ? Number(iso[3]) : market ? Number(market[1]) : NaN;
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day) || month < 0) return null;
  const timestamp = Date.UTC(year, month, day);
  const parsed = new Date(timestamp);
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month && parsed.getUTCDate() === day
    ? timestamp
    : null;
}

/**
 * Pick the nearest expiry that is still tradable on the IST trading calendar
 * (future dates, plus today's expiry until the 15:30 IST close), or null when
 * the list carries none.
 *
 * Shared by every widget that must choose an expiry for the operator instead of
 * leaving the choice to a server-side default: an unspecified expiry is filled
 * in by the backend with a hard-coded label, which silently renders a stale
 * contract as if it were the current one.
 */
export function selectFutureExpiry(expiries: readonly string[], now = new Date()): string | null {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const part = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((item) => item.type === type)?.value);
  const today = Date.UTC(part("year"), part("month") - 1, part("day"));
  // The front contract stays tradable through its own expiry session; dropping
  // it at midnight would jump every dependent widget to the next expiry for
  // the whole of expiry day.
  const beforeTradingClose = part("hour") * 60 + part("minute") < 15 * 60 + 30;
  return expiries
    .flatMap((expiry) => {
      const timestamp = expiryEpoch(expiry);
      const tradable =
        timestamp !== null && (timestamp > today || (timestamp === today && beforeTradingClose));
      return tradable ? [{ expiry, timestamp }] : [];
    })
    .sort((left, right) => left.timestamp - right.timestamp)[0]?.expiry ?? null;
}

export function buildCompactOptionSymbol(
  underlying: string,
  expiry: string,
  strike: number | string,
  optionType: OptionType,
): string | null {
  const base = underlying.trim().toUpperCase();
  const exp = normaliseExpiryForOptionSymbol(expiry);
  const cleanStrike = String(strike).trim();
  if (!base || !exp || !cleanStrike || cleanStrike === "0") return null;

  const strikeNumber = Number(cleanStrike);
  const strikeText = Number.isFinite(strikeNumber) ? String(strikeNumber) : cleanStrike.toUpperCase();
  return `${base}${exp}${strikeText}${optionType}`;
}

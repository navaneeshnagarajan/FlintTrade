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

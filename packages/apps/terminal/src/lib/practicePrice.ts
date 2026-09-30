/**
 * Practice fill copy shared by the Order Pad, Settings → Practice Mode,
 * and the Positions book. The age wording matches the server.
 */

/** Render a stored-close age as days, else hours, else minutes. */
export function formatPriceAge(ageS: number): string {
  const seconds = Math.max(0, Math.floor(ageS));
  if (seconds >= 86_400) {
    const days = Math.floor(seconds / 86_400);
    return `${days} ${days === 1 ? "day" : "days"} old`;
  }
  if (seconds >= 3_600) {
    const hours = Math.floor(seconds / 3_600);
    return `${hours} ${hours === 1 ? "hour" : "hours"} old`;
  }
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min old`;
}

/** Legacy engine refusal. It must never be shown; the price rule replaces it. */
export const RAW_MISSING_LTP_MESSAGE =
  "A market fill needs a positive live price; no LTP was available";

/** Plain refusal when a Practice market order has nothing to fill against. */
export function practicePriceUnavailable(symbol: string): string {
  const name = symbol.trim().toUpperCase() || "this symbol";
  return `No price for ${name} right now. Practice needs a live price or a recent close.`;
}

/**
 * Replace the raw missing-LTP 400 with the price rule's locked refusal.
 * A last-close fill is a success payload, not this error.
 */
export function visiblePracticeRefusal(message: string, symbol = ""): string {
  if (message === RAW_MISSING_LTP_MESSAGE || message.includes("no LTP was available")) {
    return practicePriceUnavailable(symbol);
  }
  return message;
}

/** Same sentence the Practice fill uses for a stored close. */
export function lastCloseFillLabel(price: number, ageS: number): string {
  return `Simulated at last close ₹${price.toFixed(2)} (${formatPriceAge(ageS)})`;
}

/**
 * Short tag beside a Positions LTP. Days, else hours, else minutes.
 * The full sentence stays on the fill. The tag tooltip names the source.
 */
export function lastCloseRowTag(ageS: number): string {
  const seconds = Math.max(0, Math.floor(ageS));
  if (seconds >= 86_400) {
    return `Last close · ${Math.floor(seconds / 86_400)}d`;
  }
  if (seconds >= 3_600) {
    return `Last close · ${Math.floor(seconds / 3_600)}h`;
  }
  return `Last close · ${Math.floor(seconds / 60)}m`;
}

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * Operator sentence for a place response.
 *
 * A last-close fill is rebuilt from `price` and `price_age_s` so the screen
 * shows the current age wording even when `message` is the generic paper line.
 */
export function visiblePracticeFill(record: {
  message?: unknown;
  price?: unknown;
  price_source?: unknown;
  priceSource?: unknown;
  price_age_s?: unknown;
  priceAgeS?: unknown;
}): string {
  const source = record.price_source ?? record.priceSource;
  const age = finiteNumber(record.price_age_s ?? record.priceAgeS);
  const price = finiteNumber(record.price);
  if (source === "last_close" && age !== null && price !== null && price > 0) {
    return lastCloseFillLabel(price, age);
  }
  return typeof record.message === "string" ? record.message.trim() : "";
}

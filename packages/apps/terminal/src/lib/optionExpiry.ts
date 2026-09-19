/**
 * Shared option-expiry helpers for Option Chain and OI Chart.
 *
 * Both surfaces must parse `/expiry` the same way and pick the same default
 * (the nearest listed expiry) so Explore and live never disagree about the
 * contract they are showing.
 */

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

/**
 * formatters.ts
 *
 * Shared number/currency formatters for the Invest route.
 * Colocated with the invest module — not global utilities.
 */

const INR_FORMATTER = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export function formatINR(value: number): string {
  return INR_FORMATTER.format(value);
}

export function formatINRCompact(value: number): string {
  if (Math.abs(value) >= 1_00_00_000) {
    return `₹${(value / 1_00_00_000).toFixed(2)}Cr`;
  }
  if (Math.abs(value) >= 1_00_000) {
    return `₹${(value / 1_00_000).toFixed(2)}L`;
  }
  return formatINR(value);
}

export function formatPercent(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

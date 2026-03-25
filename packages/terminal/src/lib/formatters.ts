/**
 * formatters.ts
 *
 * Shared formatting utilities for Indian number conventions.
 *
 * All formatters use the "en-IN" locale so numbers follow the Indian
 * grouping system: 1,23,456 (not 1,234,56).  Functions are pure and
 * synchronous — safe to call in render loops.
 *
 * Thresholds:
 *   >= 1,00,00,000  →  crore  (Cr)
 *   >= 1,00,000     →  lakh   (L)
 *   everything else →  full number with ₹ symbol
 */

// ---------------------------------------------------------------------------
// Shared Intl instances (created once, reused)
// ---------------------------------------------------------------------------

const INR_DECIMAL = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const INR_NO_DECIMAL = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const INR_FULL = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

// ---------------------------------------------------------------------------
// formatNumber
// ---------------------------------------------------------------------------

/**
 * Format a plain number with Indian comma grouping.
 *
 * Produces strings like "1,23,456.78".  Returns "—" for null / undefined /
 * NaN inputs so callers never render a raw empty string.
 *
 * @param value            - The number to format
 * @param decimalPlaces    - How many fraction digits to show (default: 2)
 */
export function formatNumber(
  value: number | null | undefined,
  decimalPlaces = 2,
): string {
  if (value == null || !isFinite(value)) return "—";
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: decimalPlaces,
    maximumFractionDigits: decimalPlaces,
  }).format(value);
}

// ---------------------------------------------------------------------------
// formatCurrency
// ---------------------------------------------------------------------------

/**
 * Format a rupee value with the ₹ symbol and 2 decimal places.
 *
 * Examples:
 *   1234.5   →  "₹1,234.50"
 *   123456   →  "₹1,23,456.00"
 *   -5000    →  "-₹5,000.00"
 *   null     →  "₹0.00"
 *
 * @param value - Rupee amount
 */
export function formatCurrency(value: number | null | undefined): string {
  const safe = value ?? 0;
  if (!isFinite(safe)) return "₹0.00";
  const sign = safe < 0 ? "-" : "";
  return `${sign}₹${INR_DECIMAL.format(Math.abs(safe))}`;
}

// ---------------------------------------------------------------------------
// formatCurrencyCompact
// ---------------------------------------------------------------------------

/**
 * Compact rupee formatting for dashboard tiles and summaries.
 *
 * Thresholds (checked on Math.abs):
 *   >= 1 crore   →  "₹2.50Cr"
 *   >= 1 lakh    →  "₹3.75L"
 *   else         →  "₹1,234" (integer, no decimal)
 *
 * @param value - Rupee amount (may be negative)
 */
export function formatCurrencyCompact(value: number | null | undefined): string {
  const safe = value ?? 0;
  if (!isFinite(safe)) return "₹0";
  const abs = Math.abs(safe);
  const sign = safe < 0 ? "-" : "";

  if (abs >= 1_00_00_000) {
    return `${sign}₹${(abs / 1_00_00_000).toFixed(2)}Cr`;
  }
  if (abs >= 1_00_000) {
    return `${sign}₹${(abs / 1_00_000).toFixed(2)}L`;
  }
  return `${sign}₹${INR_NO_DECIMAL.format(abs)}`;
}

// ---------------------------------------------------------------------------
// formatPnl
// ---------------------------------------------------------------------------

/**
 * Format a P&L value with a leading sign and ₹ symbol.
 *
 * Always shows "+" for positive values, "−" for negative.
 *   500   →  "+₹500.00"
 *   -500  →  "-₹500.00"
 *   0     →  "+₹0.00"
 *
 * @param value - P&L amount
 */
export function formatPnl(value: number | null | undefined): string {
  const safe = value ?? 0;
  if (!isFinite(safe)) return "+₹0.00";
  const sign = safe >= 0 ? "+" : "-";
  return `${sign}₹${INR_DECIMAL.format(Math.abs(safe))}`;
}

// ---------------------------------------------------------------------------
// formatPercent
// ---------------------------------------------------------------------------

/**
 * Format a percentage value with a leading sign.
 *
 *   12.5   →  "+12.50%"
 *   -3.2   →  "-3.20%"
 *   0      →  "+0.00%"
 *   null   →  "0.00%"
 *
 * @param value - Percentage value (e.g. 12.5 means 12.5%)
 */
export function formatPercent(value: number | null | undefined): string {
  const safe = value ?? 0;
  if (!isFinite(safe)) return "0.00%";
  const sign = safe >= 0 ? "+" : "";
  return `${sign}${safe.toFixed(2)}%`;
}

// ---------------------------------------------------------------------------
// formatIndianNumber  (shared utility for DataNumber / DataDirection)
// ---------------------------------------------------------------------------

/**
 * Format a number with the Indian comma grouping (en-IN locale).
 *
 * For "percent" and "currency" formats: always 2 decimal places.
 * For "number" format: decimals shown only when present.
 * Sign is stripped — callers are responsible for prepending +/−.
 *
 * @param value  - Absolute numeric value (pass Math.abs() result if needed)
 * @param format - "number" | "currency" | "percent"
 */
export function formatIndianNumber(
  value: number,
  format: "number" | "currency" | "percent",
): string {
  const hasFraction = value % 1 !== 0;
  const fractionDigits =
    format !== "number" || hasFraction ? 2 : 0;

  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

// ---------------------------------------------------------------------------
// formatINR  (alias matching the InvestRoute inline helper)
// ---------------------------------------------------------------------------

/**
 * Full rupee amount using the browser's built-in currency style.
 * Produces locale-aware output like "₹1,23,456".
 *
 * @param value - Rupee amount (integer precision, no decimals shown)
 */
export function formatINR(value: number): string {
  return INR_FULL.format(value);
}

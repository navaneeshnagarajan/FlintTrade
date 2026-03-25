import { cn } from "@/lib/utils";

interface DataNumberProps {
  value: number | null | undefined;
  tier?: "hero" | "primary" | "cell";
  prefix?: string;
  suffix?: string;
  format?: "number" | "currency" | "percent";
  className?: string;
}

const TIER_CLASSES = {
  hero: "text-4xl font-bold",
  primary: "text-xl font-semibold",
  cell: "text-[13px] font-medium",
} as const;

/**
 * Formats a number using the Indian numbering locale (en-IN).
 * Returns null when the value is null/undefined so callers can render "—".
 */
function formatIndian(
  value: number,
  format: NonNullable<DataNumberProps["format"]>
): string {
  if (format === "percent") {
    return new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  }

  if (format === "currency") {
    return new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  }

  // "number" — plain integer-ish formatting; use fractions only when present
  const hasDecimals = value % 1 !== 0;
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: hasDecimals ? 2 : 0,
    maximumFractionDigits: hasDecimals ? 2 : 0,
  }).format(value);
}

/**
 * Three-tier numeric display component.
 *
 * Tiers:
 *  - hero    — 36px / bold   (headline P&L, fund value)
 *  - primary — 20px / semibold (widget stat)
 *  - cell    — 13px / medium   (table cell, default)
 *
 * Always uses JetBrains Mono + tabular-nums for alignment.
 * Renders "—" (em-dash) for null/undefined values.
 * Formats numbers with the Indian locale (1,23,456).
 */
export function DataNumber({
  value,
  tier = "cell",
  prefix,
  suffix,
  format = "number",
  className,
}: DataNumberProps) {
  if (value == null) {
    return (
      <span
        role="text"
        aria-label="—"
        className={cn(
          "font-mono tabular-nums text-text-muted",
          TIER_CLASSES[tier],
          className
        )}
      >
        —
      </span>
    );
  }

  const formatted = formatIndian(value, format);
  const displayPrefix = format === "currency" ? (prefix ?? "₹") : (prefix ?? "");
  const displaySuffix = format === "percent" ? (suffix ?? "%") : (suffix ?? "");
  const ariaLabel = `${displayPrefix}${formatted}${displaySuffix}`;

  return (
    <span
      role="text"
      aria-label={ariaLabel}
      className={cn(
        "font-mono tabular-nums",
        TIER_CLASSES[tier],
        className
      )}
    >
      {displayPrefix}
      {formatted}
      {displaySuffix}
    </span>
  );
}

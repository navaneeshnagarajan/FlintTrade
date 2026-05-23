import { cn } from "@/lib/utils";
import { formatIndianNumber } from "@/lib/formatters";

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
        role="img"
        aria-label="No data available"
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

  const formatted = formatIndianNumber(value, format);
  const displayPrefix = format === "currency" ? (prefix ?? "₹") : (prefix ?? "");
  const displaySuffix = format === "percent" ? (suffix ?? "%") : (suffix ?? "");
  const ariaLabel = `${displayPrefix}${formatted}${displaySuffix}`;

  return (
    <span
      role="img"
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

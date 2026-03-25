import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

interface DataDirectionProps {
  value: number | null | undefined;
  format?: "currency" | "percent" | "number";
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZE_ICON: Record<NonNullable<DataDirectionProps["size"]>, number> = {
  sm: 12,
  md: 14,
  lg: 16,
};

const SIZE_TEXT: Record<NonNullable<DataDirectionProps["size"]>, string> = {
  sm: "text-[11px]",
  md: "text-[13px]",
  lg: "text-sm",
};

/**
 * Formats a number using the Indian numbering locale (en-IN).
 * Always renders 2 decimal places for currency and percent; integer-aware for number.
 */
function formatIndian(
  value: number,
  format: NonNullable<DataDirectionProps["format"]>
): string {
  const hasFraction = value % 1 !== 0;
  const fractionDigits = format !== "number" || hasFraction ? 2 : 0;

  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(Math.abs(value));
}

/**
 * Profit/loss direction indicator.
 *
 * Always renders: icon + color + sign + background tint.
 * NEVER uses color alone — every directional signal carries icon, sign,
 * and a subtle background tint to remain accessible.
 *
 * Renders "—" (em-dash) for null/undefined values.
 */
export function DataDirection({
  value,
  format = "number",
  size = "md",
  className,
}: DataDirectionProps) {
  if (value == null) {
    return (
      <span
        role="text"
        aria-label="—"
        className={cn(
          "inline-flex items-center gap-1 rounded px-1.5 py-0.5",
          "text-text-muted bg-surface-elevated font-mono tabular-nums",
          SIZE_TEXT[size],
          className
        )}
      >
        —
      </span>
    );
  }

  const isPositive = value > 0;
  const isNegative = value < 0;
  const isZero = value === 0;

  const formatted = formatIndian(value, format);
  const prefix = format === "currency" ? "₹" : "";
  const suffix = format === "percent" ? "%" : "";
  const sign = isPositive ? "+" : isNegative ? "-" : "";

  // Color and background classes
  const textClass = isPositive
    ? "text-bullish-text"
    : isNegative
      ? "text-bearish-text"
      : "text-text-secondary";

  const bgClass = isPositive
    ? "bg-bullish-bg"
    : isNegative
      ? "bg-bearish-bg"
      : "bg-neutral-bg";

  // Icon selection
  const Icon = isPositive ? TrendingUp : isNegative ? TrendingDown : Minus;
  const iconSize = SIZE_ICON[size];

  // Accessible label
  const ariaLabel = isZero
    ? `${prefix}${formatted}${suffix} neutral`
    : `${sign}${prefix}${formatted}${suffix} ${isPositive ? "profit" : "loss"}`;

  return (
    <span
      role="text"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5",
        "font-mono tabular-nums",
        bgClass,
        textClass,
        SIZE_TEXT[size],
        className
      )}
    >
      <Icon size={iconSize} aria-hidden="true" />
      <span>
        {sign}
        {prefix}
        {formatted}
        {suffix}
      </span>
    </span>
  );
}

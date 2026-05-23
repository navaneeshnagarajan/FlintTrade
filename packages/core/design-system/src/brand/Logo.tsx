/**
 * FlintTrade Logo component — SVG icon, wordmark, and full logo variants.
 *
 * Icon: Sharp geometric flint/spark motif — angular "F" letterform with a
 *   faceted diamond spark at top-right, suggesting struck flint catching fire.
 *   The spark uses the brand green (#22c55e).
 *
 * Wordmark: "FlintTrade" as SVG text in Geist font, weight 700.
 *
 * Exports:
 *   LogoIcon      — icon only
 *   LogoWordmark  — text only
 *   Logo          — icon + wordmark combined (default export too for lazy loading)
 *
 * Props (all three components):
 *   size    — "sm" | "md" | "lg"  (default "md")
 *   variant — "light" | "dark" | "auto"  (default "auto")
 *   className
 *
 * variant behaviour:
 *   "dark"  — white text/icon (for dark backgrounds)
 *   "light" — black text/icon (for light backgrounds)
 *   "auto"  — inherits currentColor from parent; works on any background
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type LogoSize = "sm" | "md" | "lg";
export type LogoVariant = "light" | "dark" | "auto";

export const SIZE_PX: Record<LogoSize, number> = {
  sm: 16,
  md: 24,
  lg: 36,
};

function resolveColor(variant: LogoVariant): string {
  if (variant === "dark") return "#ffffff";
  if (variant === "light") return "#0a0a0f";
  return "currentColor";
}

// ---------------------------------------------------------------------------
// LogoIcon
// ---------------------------------------------------------------------------

export interface LogoIconProps {
  /** Visual size preset. Default: "md" (24px). */
  size?: LogoSize | number;
  /** Colour variant. Default: "auto" (inherits currentColor). */
  variant?: LogoVariant;
  className?: string;
  "aria-hidden"?: boolean | "true" | "false";
}

/**
 * LogoIcon — the standalone FlintTrade mark.
 *
 * Geometry (32×32 viewBox):
 *   - Left vertical bar:  the stem of the F
 *   - Top bar:            horizontal cap of the F
 *   - Mid bar:            middle arm of the F
 *   - Spark diamond:      faceted angular diamond at top-right, erupting upward
 *     like struck flint. Built from sharp polygons, zero curves.
 */
export function LogoIcon({
  size = "md",
  variant = "auto",
  className,
  "aria-hidden": ariaHidden,
}: LogoIconProps) {
  const px = typeof size === "number" ? size : SIZE_PX[size];
  const fill = resolveColor(variant);

  return (
    <svg
      viewBox="0 0 32 32"
      width={px}
      height={px}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label={ariaHidden ? undefined : "FlintTrade icon"}
      aria-hidden={ariaHidden}
      role={ariaHidden ? "presentation" : "img"}
    >
      {/* F letterform — left vertical bar */}
      <rect x="3" y="3" width="5" height="26" rx="1" fill={fill} />

      {/* F letterform — top horizontal bar */}
      <rect x="3" y="3" width="20" height="5" rx="1" fill={fill} />

      {/* F letterform — middle horizontal bar */}
      <rect x="3" y="13" width="14" height="5" rx="1" fill={fill} />

      {/*
       * Spark / flint diamond — sharp geometric facets, top-right corner.
       *
       * The shape is intentionally angular (no arcs): it reads as a faceted
       * flint stone or struck spark at every size from 16px upward.
       *
       * Points (clockwise from top apex):
       *   (24, 1)  — top point (the "spark tip")
       *   (29, 6)  — right point
       *   (24, 11) — bottom point
       *   (21, 7)  — inner-left notch (creates the facet)
       *   (24, 5)  — inner-top notch
       *   (21, 3)  — inner-left top (closes the left facet)
       */}
      <polygon
        points="24,1 29,6 24,11 21,7 24,5 21,3"
        fill="#22c55e"
      />

      {/*
       * Secondary spark sliver — a thin angular highlight above the diamond
       * that suggests a flying spark/ember. Adds visual energy at larger sizes.
       */}
      <polygon
        points="25,0 28,3 26,3 24,1"
        fill="#4ade80"
        opacity="0.75"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// LogoWordmark
// ---------------------------------------------------------------------------

export interface LogoWordmarkProps {
  /** Visual size preset. Default: "md" (24px cap-height). */
  size?: LogoSize | number;
  /** Colour variant. Default: "auto" (inherits currentColor). */
  variant?: LogoVariant;
  className?: string;
  /** When true, removes role/aria-label (use when embedded inside a labelled Logo container). */
  decorative?: boolean;
}

/**
 * LogoWordmark — "FlintTrade" text in Geist, weight 700.
 *
 * The viewBox is sized to the text bounding box so scaling is predictable.
 * Width is derived from the height via the ~5.5:1 aspect ratio of the wordmark.
 */
export function LogoWordmark({
  size = "md",
  variant = "auto",
  className,
}: LogoWordmarkProps) {
  const px = typeof size === "number" ? size : SIZE_PX[size];
  // "FlintTrade" at 700 weight, -0.5 tracking, ~22px over 24px viewBox ≈ 5.5:1
  const aspectRatio = 5.5;
  const width = Math.round(px * aspectRatio);
  const fill = resolveColor(variant);

  return (
    <svg
      viewBox="0 0 132 24"
      width={width}
      height={px}
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="FlintTrade wordmark"
      role="img"
    >
      <text
        x="0"
        y="19"
        fontFamily="Geist, system-ui, sans-serif"
        fontWeight={700}
        fontSize="22"
        letterSpacing="-0.5"
        fill={fill}
      >
        FlintTrade
      </text>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Logo — combined icon + wordmark
// ---------------------------------------------------------------------------

export interface LogoProps {
  /** "full" = icon + wordmark, "icon" = icon only, "wordmark" = wordmark only */
  variant?: "full" | "icon" | "wordmark";
  /** Colour scheme. Default: "auto". */
  colorVariant?: LogoVariant;
  /** Visual size preset. Default: "md". */
  size?: LogoSize | number;
  className?: string;
}

/**
 * Logo — primary brand component.
 *
 * - variant="full"      → icon + wordmark side by side (8px gap)
 * - variant="icon"      → icon only
 * - variant="wordmark"  → wordmark only
 */
export function Logo({
  variant = "full",
  colorVariant = "auto",
  size = "md",
  className,
}: LogoProps) {
  if (variant === "icon") {
    return (
      <LogoIcon
        size={size}
        variant={colorVariant}
        className={className}
      />
    );
  }

  if (variant === "wordmark") {
    return (
      <LogoWordmark
        size={size}
        variant={colorVariant}
        className={className}
      />
    );
  }

  // "full" — icon + wordmark
  const px = typeof size === "number" ? size : SIZE_PX[size];
  const gap = Math.max(4, Math.round(px / 3));

  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap,
        lineHeight: 1,
      }}
      aria-label="FlintTrade"
      role="img"
    >
      <LogoIcon size={size} variant={colorVariant} aria-hidden />
      <LogoWordmark size={size} variant={colorVariant} />
    </span>
  );
}

// Default export for lazy loading
export default Logo;

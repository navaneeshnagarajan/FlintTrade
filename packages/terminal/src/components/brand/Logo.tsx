/**
 * FlintTrade Logo component — SVG icon, wordmark, and full logo variants.
 *
 * Icon: Geometric stylized "F" with an upward spark/flint motif in green.
 * Wordmark: "FlintTrade" text in Geist font, weight 700.
 * Full: Icon + wordmark side by side.
 *
 * Works on any background (F uses currentColor). Recognizable from 16px to 64px+.
 */

interface LogoProps {
  variant?: "full" | "icon" | "wordmark";
  /** Height in px (default 24) */
  size?: number;
  className?: string;
}

/**
 * Standalone icon — geometric "F" letterform with green spark accent.
 *
 * viewBox is 32x32. The F is built from:
 *   - Vertical bar (left stem)
 *   - Top horizontal bar
 *   - Middle horizontal bar
 *   - Angular spark/flint diamond at top-right, angled upward ~45 degrees
 */
export function LogoIcon({
  size = 24,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="FlintTrade icon"
    >
      {/* Vertical bar — left stem of F */}
      <rect x="4" y="4" width="5" height="24" rx="1.5" fill="currentColor" />
      {/* Top horizontal bar */}
      <rect x="4" y="4" width="18" height="5" rx="1.5" fill="currentColor" />
      {/* Middle horizontal bar */}
      <rect x="4" y="13" width="14" height="5" rx="1.5" fill="currentColor" />
      {/* Spark / flint — angular diamond pointing up-right at ~45 degrees */}
      <path
        d="M23 2 L27 6 L23 10 L21 8 L24 5 L21 4 Z"
        fill="#22c55e"
      />
    </svg>
  );
}

/**
 * Wordmark — "FlintTrade" as SVG text.
 *
 * Uses Geist font family with system-ui fallback. Weight 700, tight tracking.
 * Color is currentColor so it inherits from the parent.
 *
 * viewBox is sized so the text fits with comfortable margins.
 * The width is proportional to the height via the aspect ratio of the viewBox.
 */
export function LogoWordmark({
  size = 24,
  className,
}: {
  size?: number;
  className?: string;
}) {
  // Aspect ratio: text area is roughly 120 wide x 24 tall
  const aspectRatio = 120 / 24;
  const width = Math.round(size * aspectRatio);

  return (
    <svg
      viewBox="0 0 120 24"
      width={width}
      height={size}
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="FlintTrade wordmark"
    >
      <text
        x="0"
        y="19"
        fontFamily="Geist, system-ui, sans-serif"
        fontWeight={700}
        fontSize="22"
        letterSpacing="-0.5"
        fill="currentColor"
      >
        FlintTrade
      </text>
    </svg>
  );
}

/**
 * Primary Logo component — renders icon, wordmark, or both depending on variant.
 *
 * - "full" (default): icon + wordmark side by side with 8px gap
 * - "icon": icon only
 * - "wordmark": wordmark only
 */
export function Logo({ variant = "full", size = 24, className }: LogoProps) {
  if (variant === "icon") {
    return <LogoIcon size={size} className={className} />;
  }

  if (variant === "wordmark") {
    return <LogoWordmark size={size} className={className} />;
  }

  // "full" — icon + wordmark side by side
  return (
    <span
      className={className}
      style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
    >
      <LogoIcon size={size} />
      <LogoWordmark size={size} />
    </span>
  );
}

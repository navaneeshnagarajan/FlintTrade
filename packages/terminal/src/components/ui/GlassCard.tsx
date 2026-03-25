/**
 * GlassCard.tsx
 *
 * A Card variant with optional glassmorphism — backdrop-blur + transparent
 * background. When glass mode is inactive it renders as a standard
 * shadcn Card so it is a drop-in replacement in any context.
 *
 * Glass rendering uses inline styles (not Tailwind classes) because the blur
 * radius and transparency values are dynamic numbers from the theme store and
 * cannot be resolved at build time by Tailwind's static scanner.
 *
 * Usage:
 *   <GlassCard>…</GlassCard>                  // follows themeStore.glass.enabled
 *   <GlassCard glass>…</GlassCard>             // force glass on
 *   <GlassCard glass={false}>…</GlassCard>     // force glass off
 */

import * as React from "react";
import { useShallow } from "zustand/react/shallow";
import { cn } from "@/lib/utils";
import { useThemeStore } from "@/stores/themeStore";
import { getResolvedVariant } from "@/lib/cinematicThemes";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  /**
   * Override the glass mode.
   * - undefined (default) → false (solid card)
   * - true                → force glass on regardless of store
   * - false               → force glass off (solid card)
   */
  glass?: boolean; // default false
}

// ---------------------------------------------------------------------------
// Helper — hex color → rgba string
// ---------------------------------------------------------------------------

/** Read a CSS custom property from the document root. */
function readRootCssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function hexToRgba(hex: string, alpha: number): string {
  const cleaned = hex.startsWith("#") ? hex.slice(1) : hex;
  if (cleaned.length !== 6) {
    // Fall back to the theme card color so it adapts to light/dark mode
    const cardHex = readRootCssVar("--color-card", "#16161f");
    return hexToRgba(cardHex, alpha);
  }
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  if (isNaN(r) || isNaN(g) || isNaN(b)) {
    const cardHex = readRootCssVar("--color-card", "#16161f");
    return hexToRgba(cardHex, alpha);
  }
  return `rgba(${r},${g},${b},${alpha})`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GlassCard({
  children,
  className,
  glass,
  style,
  ...rest
}: GlassCardProps) {
  // Only used when glass={true} is explicitly passed — provides blur/transparency values.
  const glassStore = useThemeStore(useShallow((state) => state.glass));
  // Subscribe to stable source fields so the selector only re-renders when
  // the active theme ID or mode actually changes.
  const { activeThemeId, storeMode, customThemes } = useThemeStore(
    useShallow((state) => ({
      activeThemeId: state.activeThemeId,
      storeMode:     state.mode,
      customThemes:  state.customThemes,
    }))
  );

  // Resolve the active CinematicTheme and its variant
  const activeTheme = useThemeStore((state) => state.getActiveTheme());
  const resolvedMode = useThemeStore((state) => state.getResolvedMode());
  // Suppress unused-variable warnings for subscription fields
  void activeThemeId; void storeMode; void customThemes;

  const variant = getResolvedVariant(activeTheme, resolvedMode);

  // Resolve whether glass mode is active for this instance
  // Default is false (solid card); pass glass={true} to opt in to glassmorphism.
  const isGlass = glass !== undefined ? glass : false;

  if (!isGlass) {
    // Non-glass: standard Card appearance via Tailwind tokens
    return (
      <div
        data-slot="card"
        className={cn(
          "flex flex-col gap-4 rounded-lg border border-border-default bg-surface-card p-4 text-card-foreground shadow-sm",
          className,
        )}
        style={style}
        {...rest}
      >
        {children}
      </div>
    );
  }

  // Glass mode: compute dynamic values.
  // Priority: store explicit values > CSS vars > theme variant defaults.
  function readCssVar(name: string): string {
    if (typeof window === "undefined") return "";
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  const cssBlur = readCssVar("--glass-blur");
  const cssTint = readCssVar("--glass-tint");
  const cssBorderAlpha = readCssVar("--glass-border-alpha");

  const blurPx =
    glassStore.blur > 0
      ? glassStore.blur
      : cssBlur
      ? parseFloat(cssBlur)
      : variant.glass.blur;

  const transparencyPct =
    glassStore.transparency > 0
      ? glassStore.transparency
      : Math.round((1 - variant.glass.minOpacity) * 100);

  // transparency is 0–100; convert to 0–1 alpha.
  // We invert: 100% transparency = fully transparent (alpha 0), 0% = opaque.
  // Clamp minimum alpha to 0.60 so text-bearing glass surfaces remain readable
  // per WCAG contrast requirements. Prior floor was 0.05.
  const alpha = Math.max(0.60, 1 - transparencyPct / 100);

  // Use CSS var tint when present, otherwise fall back to theme variant
  const tintSource = cssTint || variant.colors.card;
  const borderAlpha = cssBorderAlpha ? parseFloat(cssBorderAlpha) : 0.4;

  const cardBg = hexToRgba(tintSource, alpha);
  const borderColor = hexToRgba(variant.colors.border, borderAlpha);
  const hoverBg = hexToRgba(variant.colors.cardHover, alpha + 0.05 > 1 ? 1 : alpha + 0.05);

  const glassStyle: React.CSSProperties = {
    backdropFilter: `blur(${blurPx}px)`,
    WebkitBackdropFilter: `blur(${blurPx}px)`,
    background: cardBg,
    border: `1px solid ${borderColor}`,
    // Transition for hover
    transition: "background 0.15s ease",
    ...style,
  };

  return (
    <div
      data-slot="card"
      data-glass="true"
      className={cn(
        "flex flex-col gap-4 rounded-lg p-4 text-card-foreground shadow-sm",
        "hover:brightness-110",
        className,
      )}
      style={glassStyle}
      onMouseEnter={(e) => {
        const el = e.currentTarget;
        el.style.background = hoverBg;
        rest.onMouseEnter?.(e);
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget;
        el.style.background = cardBg;
        rest.onMouseLeave?.(e);
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

export default GlassCard;

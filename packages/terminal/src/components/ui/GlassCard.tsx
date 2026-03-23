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

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  /**
   * Override the glass mode.
   * - undefined (default) → reads themeStore.glass.enabled
   * - true                → force glass on regardless of store
   * - false               → force glass off regardless of store
   */
  glass?: boolean;
}

// ---------------------------------------------------------------------------
// Helper — hex color → rgba string
// ---------------------------------------------------------------------------

function hexToRgba(hex: string, alpha: number): string {
  const cleaned = hex.startsWith("#") ? hex.slice(1) : hex;
  if (cleaned.length !== 6) return `rgba(22,22,31,${alpha})`;
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  if (isNaN(r) || isNaN(g) || isNaN(b)) return `rgba(22,22,31,${alpha})`;
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
  const glassStore = useThemeStore(useShallow((state) => state.glass));
  // getActiveTheme() returns a new object on every invocation; subscribe to
  // the stable source fields so the selector only re-renders when the active
  // theme ID or custom themes list actually changes.
  const activeTheme = useThemeStore(
    useShallow((state) => state.getActiveTheme())
  );

  // Resolve whether glass mode is active for this instance
  const isGlass = glass !== undefined ? glass : glassStore.enabled;

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

  // Glass mode: compute dynamic values from store + active theme
  const blurPx = glassStore.blur > 0 ? glassStore.blur : activeTheme.effects.blur;
  const transparencyPct =
    glassStore.transparency > 0
      ? glassStore.transparency
      : activeTheme.effects.transparency;

  // transparency is 0–100; convert to 0–1 alpha.
  // We invert: 100% transparency = fully transparent (alpha 0), 0% = opaque.
  // Clamp to a sensible glass range: keep minimum alpha of 0.05 so the card
  // surface is always visible.
  const alpha = Math.max(0.05, 1 - transparencyPct / 100);

  const cardBg = hexToRgba(activeTheme.colors.card, alpha);
  const borderColor = hexToRgba(activeTheme.colors.border, 0.4);
  const hoverBg = hexToRgba(activeTheme.colors.cardHover, alpha + 0.05 > 1 ? 1 : alpha + 0.05);

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

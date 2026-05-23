/**
 * useTremorTheme.ts
 *
 * Hook for Tremor charts. Reads CSS custom properties written by
 * themeStore.applyTheme() and returns a 6-color palette array.
 *
 * Tremor's `colors` prop accepts named Tailwind colors OR hex strings
 * (via the `customColors` workaround). We return raw hex/hsl CSS var
 * values so they work as inline color overrides.
 *
 * CSS vars consumed:
 *   --color-accent    primary accent
 *   --color-profit    green profit
 *   --color-loss      red loss
 *   --color-warning   amber warning
 *   --color-text      primary text (used as a muted neutral)
 *   --color-border    border (used as the dimmest shade)
 *
 * Returns 6 colors in order: [accent, profit, loss, warning, text, border]
 * which maps neatly to Tremor's first 6 series slots.
 *
 * Memoised on (activeThemeId + resolvedMode).
 */

import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { useThemeStore } from "@/stores/themeStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function cssVar(name: string, fallback = ""): string {
  if (typeof window === "undefined") return fallback;
  return (
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
    fallback
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Returns a 6-element hex color array for Tremor chart `colors` props.
 * Order: accent, profit, loss, warning, accentMuted, neutral
 */
export function useTremorTheme(): string[] {
  const { activeThemeId, resolvedMode } = useThemeStore(
    useShallow((s) => ({
      activeThemeId: s.activeThemeId,
      resolvedMode: s.getResolvedMode(),
    })),
  );

  return useMemo(() => {
    const accent = cssVar("--color-accent", "#6366f1");
    const profit = cssVar("--color-profit", "#22c55e");
    const loss = cssVar("--color-loss", "#ef4444");
    const warning = cssVar("--color-warning", "#f59e0b");
    // Muted accent: complementary to the primary accent
    const accentMuted = cssVar("--color-accent-muted", "#818cf8");
    const neutral = cssVar("--color-text-secondary", "#6b6b78");

    return [accent, profit, loss, warning, accentMuted, neutral];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThemeId, resolvedMode]);
}

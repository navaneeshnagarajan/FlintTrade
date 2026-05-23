/**
 * useGlideTheme.ts
 *
 * Hook for Glide Data Grid. Reads CSS custom properties written by
 * themeStore.applyTheme() and returns a Partial<Theme> object for the
 * DataEditor `theme` prop.
 *
 * CSS vars consumed:
 *   --color-base         page / canvas background
 *   --color-card         card / panel surface
 *   --color-hover        hover surface
 *   --color-border       default border
 *   --color-text         primary text
 *   --color-text-secondary  secondary / subdued text
 *   --color-text-muted   muted label text
 *   --color-accent       primary accent (selection highlight)
 *
 * Memoised on (activeThemeId + resolvedMode).
 */

import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { useThemeStore } from "@/stores/themeStore";
import type { Theme } from "@glideapps/glide-data-grid";

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

export function useGlideTheme(): Partial<Theme> {
  const { activeThemeId, resolvedMode } = useThemeStore(
    useShallow((s) => ({
      activeThemeId: s.activeThemeId,
      resolvedMode: s.getResolvedMode(),
    })),
  );

  return useMemo(() => {
    const base = cssVar("--color-base", "#0a0a0f");
    const card = cssVar("--color-card", "#16161f");
    const hover = cssVar("--color-hover", "#24242e");
    const border = cssVar("--color-border", "#2a2a3a");
    const text = cssVar("--color-text", "#e4e4e7");
    const textSecondary = cssVar("--color-text-secondary", "#8b8b95");
    const textMuted = cssVar("--color-text-muted", "#6b6b78");
    const accent = cssVar("--color-accent", "#6366f1");

    return {
      bgCell: base,
      bgCellMedium: card,
      bgHeader: card,
      bgHeaderHasFocus: hover,
      bgHeaderHovered: hover,
      textDark: text,
      textMedium: textSecondary,
      textLight: textMuted,
      textHeader: textSecondary,
      accentColor: accent,
      accentFg: "#ffffff",
      borderColor: border,
      fontFamily: "JetBrains Mono, monospace",
      baseFontStyle: "11px",
      headerFontStyle: "500 10px",
      editorFontSize: "11px",
    } satisfies Partial<Theme>;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThemeId, resolvedMode]);
}

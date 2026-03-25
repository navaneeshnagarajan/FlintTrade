/**
 * useDockviewTheme.ts
 *
 * Hook for Dockview panels. Reads CSS custom properties written by
 * themeStore.applyTheme() and returns a Record<string, string> of
 * Dockview CSS custom property overrides.
 *
 * These overrides are intended to be applied as inline style on the
 * DockviewReact container element (or a parent wrapper), so Dockview's
 * own CSS variables are overridden at the correct cascade level.
 *
 * CSS vars consumed:
 *   --color-base     page background
 *   --color-card     panel / tab surface
 *   --color-hover    hover surface
 *   --color-border   separator / border
 *   --color-accent   active tab indicator
 *   --color-text     primary text
 *   --color-text-secondary  tab label text
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

export function useDockviewTheme(): Record<string, string> {
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
    const accent = cssVar("--color-accent", "#6366f1");
    const text = cssVar("--color-text", "#e4e4e7");
    const textSecondary = cssVar("--color-text-secondary", "#8b8b95");

    // Dockview CSS custom properties (dockview-react theme overrides)
    return {
      "--dv-background-color": base,
      "--dv-pane-background-color": card,
      "--dv-header-background-color": card,
      "--dv-active-group-visible-panel-header-color": card,
      "--dv-active-group-hovered-panel-header-color": hover,
      "--dv-inactive-group-visible-panel-header-color": base,
      "--dv-tab-divider-color": border,
      "--dv-separator-border": border,
      "--dv-group-view-background-color": base,
      "--dv-active-tab-background-color": hover,
      "--dv-inactive-tab-background-color": base,
      "--dv-active-tab-color": text,
      "--dv-inactive-tab-color": textSecondary,
      "--dv-tab-close-icon": textSecondary,
      "--dv-drag-over-background-color": `${accent}20`,
      "--dv-drag-over-border-color": accent,
      "--dv-floating-box-shadow": `0 8px 32px ${border}`,
      "--dv-active-sash-color": accent,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThemeId, resolvedMode]);
}

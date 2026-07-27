/**
 * useFlexLayoutTheme.ts
 *
 * Hook for the FlexLayout workspace host. Reads CSS custom properties
 * written by themeStore.applyTheme() and returns a Record<string, string>
 * of FlexLayout CSS custom property overrides.
 *
 * FlexLayout scopes its variables to `.flexlayout__layout`, so these
 * overrides are applied as inline style on the element WRAPPING the
 * `<Layout>` component — inline style on an ancestor wins over the theme
 * stylesheet's class-scoped defaults at the same specificity because the
 * variables inherit down into `.flexlayout__layout`.
 *
 * CSS vars consumed (FlintTrade theme tokens):
 *   --color-base     page background
 *   --color-card     panel / tab surface
 *   --color-surface-hover / --color-card-hover    hover surface
 *   --color-border   separator / border
 *   --color-accent   active tab indicator / drag affordance
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

export function useFlexLayoutTheme(): Record<string, string> {
  const { activeThemeId, resolvedMode } = useThemeStore(
    useShallow((s) => ({
      activeThemeId: s.activeThemeId,
      resolvedMode: s.getResolvedMode(),
    })),
  );

  return useMemo(() => {
    const base = cssVar("--color-base", "#0a0a0f");
    const card = cssVar("--color-card", "#16161f");
    const hover = cssVar("--color-surface-hover", cssVar("--color-card-hover", "#24242e"));
    const border = cssVar("--color-border", "#2a2a3a");
    const accent = cssVar("--color-accent", "#6366f1");
    const text = cssVar("--color-text", "#e4e4e7");
    const textSecondary = cssVar("--color-text-secondary", "#8b8b95");

    // FlexLayout CSS custom properties (see style/_themes.scss upstream).
    // The numbered scale (--color-1..6) drives most derived surfaces, so
    // pinning it to FlintTrade tokens keeps the whole chrome on-theme.
    return {
      "--color-text": text,
      "--color-background": base,
      "--color-base": base,
      "--color-1": card,
      "--color-2": card,
      "--color-3": hover,
      "--color-4": border,
      "--color-5": hover,
      "--color-6": border,

      "--font-family": "inherit",
      "--font-size": "inherit",
      "--splitter-size": "4px",
      "--splitter-active-size": "8px",

      // Tabsets and tabs
      "--color-tabset-background": card,
      "--color-tabset-background-selected": card,
      "--color-tabset-background-maximized": card,
      "--color-tabset-divider-line": border,
      "--color-tab-selected": text,
      "--color-tab-selected-background": hover,
      "--color-tab-unselected": textSecondary,
      "--color-tab-unselected-background": "transparent",

      // Borders (unused in Phase 1 — kept on-theme for when they arrive)
      "--color-border-background": base,
      "--color-border-divider-line": border,
      "--color-border-tab-selected": text,
      "--color-border-tab-selected-background": hover,
      "--color-border-tab-unselected": textSecondary,
      "--color-border-tab-unselected-background": card,

      // Splitters
      "--color-splitter": border,
      "--color-splitter-hover": accent,
      "--color-splitter-drag": accent,

      // Drag affordances
      "--color-drag1": accent,
      "--color-drag2": accent,
      "--color-drag1-background": `${accent}20`,
      "--color-drag2-background": `${accent}20`,
      "--color-drag-rect-border": accent,
      "--color-drag-rect-background": card,
      "--color-drag-rect": text,

      // Overflow / popup menu
      "--color-popup-border": border,
      "--color-popup-unselected": text,
      "--color-popup-unselected-background": card,
      "--color-popup-selected": text,
      "--color-popup-selected-background": hover,

      // Icons, edge indicators, focus
      "--color-icon": textSecondary,
      "--color-overflow": textSecondary,
      "--color-edge-marker": border,
      "--color-edge-icon": textSecondary,
      "--color-focus": accent,
      "--color-toolbar-button-hover": hover,
      "--color-float-window-header-background": card,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThemeId, resolvedMode]);
}

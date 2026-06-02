/**
 * usePlotlyTheme.ts
 *
 * Hook for Plotly.js. Reads CSS custom properties written by
 * themeStore.applyTheme() and returns a Partial<Plotly.Layout> object
 * suitable for merging into every Plotly chart's layout prop.
 *
 * CSS vars consumed:
 *   --chart-bg      chart background (transparent is fine for Plotly)
 *   --chart-grid    grid line color
 *   --chart-text    axis label color
 *   --color-accent  primary accent color (used in colorway[0])
 *   --color-profit  green profit color
 *   --color-loss    red loss color
 *
 * Memoised on (activeThemeId + resolvedMode).
 */

import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { createFlintPlotlyTheme } from "@flinttrade/design-system";
import { useThemeStore } from "@/stores/themeStore";
import type { Layout } from "plotly.js";

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
// Return type
// ---------------------------------------------------------------------------

export interface PlotlyTheme {
  paper_bgcolor: string;
  plot_bgcolor: string;
  font: {
    family: string;
    color: string;
    size: number;
  };
  xaxis: {
    gridcolor: string;
    linecolor: string;
    zerolinecolor: string;
  };
  yaxis: {
    gridcolor: string;
    linecolor: string;
    zerolinecolor: string;
  };
  legend: {
    bgcolor: string;
    font: { size: number };
  };
  colorway: string[];
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function usePlotlyTheme(): Partial<Layout> {
  const { activeThemeId, resolvedMode } = useThemeStore(
    useShallow((s) => ({
      activeThemeId: s.activeThemeId,
      resolvedMode: s.getResolvedMode(),
    })),
  );

  return useMemo(() => {
    const grid = cssVar("--chart-grid", "#1e1e2e");
    const text = cssVar("--chart-text", "#a0a0b0");
    const accent = cssVar("--color-accent", "#6366f1");
    const profit = cssVar("--color-profit", "#22c55e");
    const loss = cssVar("--color-loss", "#ef4444");
    const warning = cssVar("--color-warning", "#f59e0b");
    const border = cssVar("--color-border", "#2a2a3a");

    return createFlintPlotlyTheme({
      grid,
      text,
      accent,
      profit,
      loss,
      warning,
      border,
    }) as Partial<Layout>;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThemeId, resolvedMode]);
}

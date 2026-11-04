/**
 * useChartTheme.ts
 *
 * Hook for Lightweight Charts v5. Reads CSS custom properties written by
 * themeStore.applyTheme() and returns a DeepPartial<ChartOptions> object
 * suitable for passing to chart.applyOptions() or createChart().
 *
 * CSS vars consumed:
 *   --chart-bg        page / chart canvas background
 *   --chart-grid      grid line color
 *   --chart-text      axis label / legend text color
 *   --chart-up        bullish candle / rising price color
 *   --chart-down      bearish candle / falling price color
 *
 * Memoised on the store's completed CSS publication, including live system
 * changes. Selection alone is too early: CSS may still hold the old palette.
 */

import { useMemo } from "react";

import {
  createFlintLightweightChartTheme,
  type FlintLightweightChartTheme,
} from "@flinttrade/design-system";
import { useThemeStore } from "@/stores/themeStore";
import type { DeepPartial, ChartOptions } from "lightweight-charts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function cssVar(name: string, fallback = "", element?: Element): string {
  if (typeof window === "undefined") return fallback;
  return (
    getComputedStyle(element ?? document.documentElement).getPropertyValue(name).trim() ||
    fallback
  );
}

// ---------------------------------------------------------------------------
// Return type
// ---------------------------------------------------------------------------

export type LightweightChartTheme = FlintLightweightChartTheme &
  DeepPartial<ChartOptions>;

/** Resolve the actual canvas ancestry after mount. Workspace tokens must not
 * leak onto documentElement (welcome/reveal have a separate palette owner). */
export function readLightweightChartTheme(element?: Element): LightweightChartTheme {
  const value = (name: string, fallback: string) => cssVar(name, fallback, element);
  const theme = createFlintLightweightChartTheme({
    background: value("--chart-bg", "#0a0a0f"),
    grid: value("--chart-grid", "#1e1e2e"),
    text: value("--chart-text", "#a0a0b0"),
    up: value("--chart-up", "#22c55e"),
    down: value("--chart-down", "#ef4444"),
    border: value("--color-border", "#2a2a3a"),
    accent: value("--color-accent", "#38bdf8"),
    muted: value("--color-text-muted", "#6b6b78"),
  });
  theme.layout.fontFamily = value("--chart-font-family", theme.layout.fontFamily);
  return theme as LightweightChartTheme;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useLightweightChartTheme(): LightweightChartTheme {
  const appliedThemeRevision = useThemeStore((s) => s.appliedThemeRevision);

  return useMemo(() => {
    return readLightweightChartTheme();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedThemeRevision]);
}

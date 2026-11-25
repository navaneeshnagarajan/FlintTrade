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

export type LightweightChartTheme = FlintLightweightChartTheme &
  DeepPartial<ChartOptions>;

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useLightweightChartTheme(): LightweightChartTheme {
  const appliedThemeRevision = useThemeStore((s) => s.appliedThemeRevision);

  return useMemo(() => {
    const bg = cssVar("--chart-bg", "#0a0a0f");
    const grid = cssVar("--chart-grid", "#1e1e2e");
    const text = cssVar("--chart-text", "#a0a0b0");
    const up = cssVar("--chart-up", "#22c55e");
    const down = cssVar("--chart-down", "#ef4444");
    const border = cssVar("--color-border", "#2a2a3a");
    const accent = cssVar("--color-accent", "#38bdf8");
    const muted = cssVar("--color-text-muted", "#6b6b78");

    return createFlintLightweightChartTheme({
      background: bg,
      grid,
      text,
      border,
      up,
      down,
      accent,
      muted,
    }) as LightweightChartTheme;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedThemeRevision]);
}

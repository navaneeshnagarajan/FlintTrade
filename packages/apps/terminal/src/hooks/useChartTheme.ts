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
 * Memoised on (activeThemeId + resolvedMode) so the chart only receives a
 * new options object when the theme actually changes.
 */

import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { useThemeStore } from "@/stores/themeStore";
import type { DeepPartial, ChartOptions, CrosshairMode } from "lightweight-charts";

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

export interface LightweightChartTheme {
  layout: {
    background: { color: string };
    textColor: string;
    fontFamily: string;
    fontSize: number;
  };
  grid: {
    vertLines: { color: string };
    horzLines: { color: string };
  };
  crosshair: { mode: CrosshairMode };
  rightPriceScale: { borderColor: string };
  timeScale: {
    borderColor: string;
    timeVisible: boolean;
    secondsVisible: boolean;
  };
  /** Colors for candlestick series — apply to series options, not chart options */
  candle: {
    upColor: string;
    downColor: string;
    borderUpColor: string;
    borderDownColor: string;
    wickUpColor: string;
    wickDownColor: string;
  };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useLightweightChartTheme(): DeepPartial<ChartOptions> & {
  candle: LightweightChartTheme["candle"];
} {
  const { activeThemeId, resolvedMode } = useThemeStore(
    useShallow((s) => ({
      activeThemeId: s.activeThemeId,
      resolvedMode: s.getResolvedMode(),
    })),
  );

  return useMemo(() => {
    const bg = cssVar("--chart-bg", "#0a0a0f");
    const grid = cssVar("--chart-grid", "#1e1e2e");
    const text = cssVar("--chart-text", "#a0a0b0");
    const up = cssVar("--chart-up", "#22c55e");
    const down = cssVar("--chart-down", "#ef4444");
    const border = cssVar("--color-border", "#2a2a3a");

    return {
      layout: {
        background: { color: bg },
        textColor: text,
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: grid },
        horzLines: { color: grid },
      },
      crosshair: { mode: 0 as CrosshairMode },
      rightPriceScale: { borderColor: border },
      timeScale: {
        borderColor: border,
        timeVisible: true,
        secondsVisible: false,
      },
      candle: {
        upColor: up,
        downColor: down,
        borderUpColor: up,
        borderDownColor: down,
        wickUpColor: up,
        wickDownColor: down,
      },
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThemeId, resolvedMode]);
}

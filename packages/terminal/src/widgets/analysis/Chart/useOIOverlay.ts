/**
 * useOIOverlay — Open Interest histogram overlay for ChartWidget.
 *
 * Renders OI data as a histogram series on a dedicated price scale ("oi")
 * below the main price chart. Fetches from the FT backend OI profile endpoint.
 *
 * Design:
 *  - Visibility is controlled by the `isVisible` param, driven by
 *    `indicators.showOI` in ChartWidget.tsx — no internal toggle state.
 *  - A single ISeriesApi<"Histogram"> is held in a stable ref.
 *  - When isVisible flips on, the series is created and data is fetched.
 *  - When isVisible flips off, the series is removed.
 *  - When symbol/exchange changes while visible, data is re-fetched.
 *
 * LWC v5 separate pane approach:
 *  - priceScaleId: "oi"  → own right-hand scale, does not overlap candles.
 *  - scaleMargins top: 0.75, bottom: 0 → renders in the bottom 25 % of the
 *    chart area, similar to the volume pane.
 */

import { useEffect, useRef, useCallback } from "react";
import { HistogramSeries } from "lightweight-charts";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import { getFtOIProfile } from "@/services/ftApi";
import type { OIProfileData } from "@/types/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UseOIOverlayParams {
  chartRef: React.MutableRefObject<IChartApi | null>;
  symbol: string;
  exchange: string;
  isVisible: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Last Thursday of the current month as YYYY-MM-DD — nearest NFO expiry. */
function getNearestExpiry(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  // Last day of the current month
  const lastDay = new Date(year, month + 1, 0);
  const dayOfWeek = lastDay.getDay(); // 0=Sun … 6=Sat, 4=Thu
  // How many days to subtract to reach the last Thursday
  const diff = dayOfWeek >= 4 ? dayOfWeek - 4 : dayOfWeek + 3;
  const lastThursday = new Date(year, month + 1, -(diff));

  if (now > lastThursday) {
    // Step to the last Thursday of the next month
    const nextLast = new Date(year, month + 2, 0);
    const nDow = nextLast.getDay();
    const nDiff = nDow >= 4 ? nDow - 4 : nDow + 3;
    return new Date(year, month + 2, -nDiff).toISOString().slice(0, 10);
  }
  return lastThursday.toISOString().slice(0, 10);
}

/**
 * Converts an OI profile into a single histogram bar placed at `latestTime`.
 *
 * OI profile data is strike-based, not time-series, so we aggregate CE vs PE
 * total OI into a single bar on the chart's most recent candle timestamp.
 * Value is the absolute net imbalance normalised to [0, 100].
 * Colour convention: red = CE-heavy (bearish pressure), green = PE-heavy.
 */
function buildOIBar(
  profile: OIProfileData,
  latestTime: Time,
): { time: Time; value: number; color: string } | null {
  const { total_ce_oi, total_pe_oi } = profile;
  const absMax = Math.max(total_ce_oi, total_pe_oi);
  if (absMax === 0) return null;

  const net = total_ce_oi - total_pe_oi;
  const normValue = Math.abs(net / absMax) * 100;
  const color =
    net >= 0
      ? "rgba(239,68,68,0.55)"   // CE > PE — bearish
      : "rgba(34,197,94,0.55)";  // PE > CE — bullish

  return { time: latestTime, value: normValue, color };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useOIOverlay({
  chartRef,
  symbol,
  exchange,
  isVisible,
}: UseOIOverlayParams): void {
  const oiSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  // Remove any existing OI series — idempotent
  const removeOI = useCallback(() => {
    const chart = chartRef.current;
    if (oiSeriesRef.current) {
      try { chart?.removeSeries(oiSeriesRef.current); } catch { /* already removed */ }
      oiSeriesRef.current = null;
    }
  }, [chartRef]);

  // Create the series and fetch OI data for the current symbol/exchange
  const applyOI = useCallback(async () => {
    const chart = chartRef.current;
    if (!chart) return;

    // Clean up previous series first
    removeOI();

    const oiSeries = chart.addSeries(HistogramSeries, {
      color: "rgba(99,102,241,0.5)",
      priceFormat: { type: "volume" },
      priceScaleId: "oi",
    });

    chart.priceScale("oi").applyOptions({
      scaleMargins: { top: 0.75, bottom: 0 },
      borderVisible: false,
    });

    oiSeriesRef.current = oiSeries;

    // Derive the latest visible candle timestamp from the time scale
    let latestTime: Time | null = null;
    try {
      const ts = chart.timeScale();
      const range = ts.getVisibleLogicalRange();
      if (range) {
        // coordinateToTime at width - 1 gives the rightmost visible bar's time
        const chartEl = (chart as unknown as { chartElement?: () => HTMLElement }).chartElement?.();
        const rightPx = chartEl ? chartEl.clientWidth - 1 : 0;
        const t = ts.coordinateToTime(rightPx);
        if (t !== null) latestTime = t;
      }
    } catch { /* ignore */ }

    if (!latestTime) {
      // Fall back to today's date string if the chart has no data yet
      latestTime = new Date().toISOString().slice(0, 10) as unknown as Time;
    }

    try {
      const expiry = getNearestExpiry();
      const profile = await getFtOIProfile(symbol, exchange, expiry);

      // Guard: series may have been removed while awaiting the fetch
      if (!oiSeriesRef.current) return;

      const bar = buildOIBar(profile, latestTime);
      if (bar) {
        oiSeries.setData([bar]);
      }
    } catch {
      // OI data unavailable — series stays empty, no crash
    }
  }, [chartRef, symbol, exchange, removeOI]);

  // React to visibility toggle
  useEffect(() => {
    if (isVisible) {
      void applyOI();
    } else {
      removeOI();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isVisible]);

  // Re-fetch when symbol/exchange changes while visible
  useEffect(() => {
    if (!isVisible) return;
    void applyOI();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, exchange]);

  // Cleanup on unmount
  useEffect(() => {
    return () => { removeOI(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

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
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import {
  createFlintChartIndicatorPaneOptions,
  createFlintChartOIOverlaySeriesOptions,
  createFlintChartOIProfileBarData,
  getFlintChartIndicatorPaneSpec,
} from "@flinttrade/design-system";
import { istParts, istToday, lastIstWeekdayOfMonth, toIstIsoDate } from "@/lib/ist";
import { lightweightHistogramRuntime } from "@/lib/lightweightChartRuntime";
import { getFtOIProfile } from "@/services/ftApi";

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

/**
 * Weekday the monthly NFO contract is ASSUMED to expire on
 * (4 = Thursday, JS weekday numbering).
 *
 * This is a configured assumption, not a verified exchange rule: NSE has
 * revised its expiry weekday since 2023 and nothing in this repository pins the
 * current one. It mirrors ``NSE_EXPIRY_WEEKDAY`` in ExpiryCountdownWidget —
 * both should move to a shared exchange-rules module once one exists, so the
 * rule is confirmed in a single place.
 *
 * It is only a FALLBACK contract guess: the authoritative expiry list is the
 * broker/symbol-master feed behind ``getExpiry`` in ``@/services/api``, which
 * the option-chain surfaces already use. Wiring it here needs an
 * underlying-exchange → derivatives-exchange mapping (this hook is handed
 * ``NSE``/``NSE_INDEX``/``MCX``, not ``NFO``), which does not exist yet.
 */
const ASSUMED_MONTHLY_EXPIRY_WEEKDAY = 4;

/**
 * The nearest monthly NFO expiry as ``YYYY-MM-DD``, in IST.
 *
 * Every read is IST: the calendar month, the weekday of its last day and the
 * emitted ISO date all come from ``@/lib/ist``. The previous version mixed
 * browser-local ``new Date(y, m, d)`` maths with a UTC ``toISOString()`` tail,
 * so an operator outside India could ask the backend for the wrong contract —
 * on a machine west of IST the month, the weekday and the date could each land
 * a day out.
 *
 * The expiry day itself still returns that day's contract: it trades until the
 * 15:30 IST close, and its OI is exactly what a chart wants to show.
 *
 * Exported for its tests: the fetched contract is a correctness surface, not a
 * cosmetic one.
 *
 * @param now - The current instant; defaults to now.
 * @returns The ISO date of the assumed nearest monthly expiry.
 */
export function getNearestExpiry(now: Date = new Date()): string {
  const { year, month } = istParts(now);
  const todayKey = toIstIsoDate(now);
  const thisMonth = toIstIsoDate(
    lastIstWeekdayOfMonth(year, month, ASSUMED_MONTHLY_EXPIRY_WEEKDAY),
  );
  if (thisMonth >= todayKey) return thisMonth;
  // Month index 12 rolls into January of the following year.
  return toIstIsoDate(lastIstWeekdayOfMonth(year, month + 1, ASSUMED_MONTHLY_EXPIRY_WEEKDAY));
}

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

    const oiSeries = lightweightHistogramRuntime.addHistogramSeries(chart, createFlintChartOIOverlaySeriesOptions());

    const paneSpec = getFlintChartIndicatorPaneSpec("oi");
    chart.priceScale("oi").applyOptions(
      paneSpec
        ? createFlintChartIndicatorPaneOptions(paneSpec)
        : { scaleMargins: { top: 0.75, bottom: 0 }, borderVisible: false },
    );

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
      // Fall back to today's date string if the chart has no data yet. The
      // trading day is the IST one — `toISOString()` would still be reading
      // yesterday for the whole IST early morning.
      latestTime = istToday() as unknown as Time;
    }

    try {
      const expiry = getNearestExpiry();
      const profile = await getFtOIProfile(symbol, exchange, expiry);

      // Guard: series may have been removed while awaiting the fetch
      if (!oiSeriesRef.current) return;

      const bar = createFlintChartOIProfileBarData<Time>({
        latestTime,
        totalCeOi: profile.total_ce_oi,
        totalPeOi: profile.total_pe_oi,
      });
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

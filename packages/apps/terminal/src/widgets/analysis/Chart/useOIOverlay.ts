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
 *
 * Chain-wide aggregates from the payload are surfaced too:
 *  - max_pain_strike → a dashed "Max pain" price line on the MAIN price scale,
 *    hung off an invisible carrier line series (a lightweight-charts price line
 *    can only attach to a series, and is only drawn once that series has data).
 *  - pcr / atm_strike → a compact readout via the histogram's axis title (the
 *    overlay has no legend surface of its own).
 * Per-strike horizontal profile rendering (volume-profile style bars at each
 * strike) is a known follow-up: it needs a horizontal-histogram primitive the
 * chart runtime does not offer today.
 */

import { useEffect, useRef, useCallback } from "react";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import {
  createFlintChartIndicatorPaneOptions,
  createFlintChartOIOverlaySeriesOptions,
  createFlintChartOIProfileBarData,
  getFlintChartIndicatorPaneSpec,
} from "@flinttrade/design-system";
import type { FlintChartPriceLineSpec } from "@flinttrade/design-system";
import { istParts, istToday, lastIstWeekdayOfMonth, toIstIsoDate } from "@/lib/ist";
import { lightweightHistogramRuntime, lightweightLineRuntime } from "@/lib/lightweightChartRuntime";
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
 * ATM-centred strike window requested from the OI profile endpoint.
 *
 * The backend default (0) returns the WHOLE chain. This overlay only consumes
 * the chain-wide aggregates — total CE/PE OI, PCR, ATM and max pain — and the
 * backend computes those over the full chain regardless of this window, so a
 * compact window trims the per-strike payload without changing any rendered
 * value. Twenty mirrors the backend's volsurface default (±10 strikes around
 * ATM) and already carries enough rows for the follow-up per-strike profile
 * rendering.
 */
const OI_PROFILE_STRIKE_COUNT = 20;

/** Dashed amber for the max-pain strike line — distinct from the pivot set. */
const MAX_PAIN_LINE_COLOUR = "#f59e0b";

/**
 * Price-line spec for the max-pain strike on the main price scale.
 *
 * ``lineStyle: 2`` is the lightweight-charts dashed code — the same numeric
 * convention ``createFlintChartPivotPriceLineSpecs`` uses.
 *
 * @param price - The max-pain strike from the OI profile payload.
 * @returns The spec handed to ``createPriceLine`` on the carrier series.
 */
function createMaxPainPriceLineSpec(price: number): FlintChartPriceLineSpec {
  return {
    price,
    color: MAX_PAIN_LINE_COLOUR,
    lineWidth: 1,
    lineStyle: 2,
    axisLabelVisible: true,
    title: "Max pain",
  };
}

/**
 * Options for the invisible line series that carries the max-pain price line.
 *
 * A lightweight-charts price line can only hang off a series, and it is only
 * drawn once that series has data — so the carrier gets a single transparent
 * anchor point at the max-pain price. It sits on the main "right" price scale
 * (the strike is a price, not an OI reading) and opts out of autoscale so the
 * anchor can never stretch the candle scale.
 *
 * @returns Partial line-series options for the chart runtime.
 */
function createMaxPainCarrierSeriesOptions(): Record<string, unknown> {
  return {
    color: "transparent",
    lineVisible: false,
    lastValueVisible: false,
    priceLineVisible: false,
    crosshairMarkerVisible: false,
    priceScaleId: "right",
    autoscaleInfoProvider: () => null,
  };
}

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
  const maxPainSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Remove any existing OI series and the max-pain carrier — idempotent.
  // Removing the carrier series also removes its attached price line.
  const removeOI = useCallback(() => {
    const chart = chartRef.current;
    if (oiSeriesRef.current) {
      try { chart?.removeSeries(oiSeriesRef.current); } catch { /* already removed */ }
      oiSeriesRef.current = null;
    }
    if (maxPainSeriesRef.current) {
      try { chart?.removeSeries(maxPainSeriesRef.current); } catch { /* already removed */ }
      maxPainSeriesRef.current = null;
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
      const profile = await getFtOIProfile(symbol, exchange, expiry, OI_PROFILE_STRIKE_COUNT);

      // Guard: this run may have been superseded (toggle-off, unmount, or a
      // newer symbol's applyOI) while awaiting the fetch. A stale run must not
      // touch the chart — its own series is already removed, and creating the
      // max-pain carrier here would orphan the newer run's one.
      if (oiSeriesRef.current !== oiSeries) return;

      const bar = createFlintChartOIProfileBarData<Time>({
        latestTime,
        totalCeOi: profile.total_ce_oi,
        totalPeOi: profile.total_pe_oi,
      });
      if (bar) {
        oiSeries.setData([bar]);
      }

      // Compact PCR / ATM readout via the histogram's axis title — the overlay
      // has no legend surface of its own. Each part is guarded: the backend
      // sends null PCR when total CE OI is zero.
      const readout: string[] = [];
      if (Number.isFinite(profile.pcr)) {
        readout.push(`PCR ${profile.pcr.toFixed(2)}`);
      }
      if (Number.isFinite(profile.atm_strike)) {
        readout.push(`ATM ${profile.atm_strike.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
      }
      if (readout.length > 0) {
        oiSeries.applyOptions({ title: `OI ${readout.join(" · ")}` });
      }

      // Max pain as a dashed price line on the MAIN price scale, hung off an
      // invisible carrier series (see createMaxPainCarrierSeriesOptions).
      if (Number.isFinite(profile.max_pain_strike)) {
        const carrier = lightweightLineRuntime.addLineSeries(chart, createMaxPainCarrierSeriesOptions());
        carrier.setData([{ time: latestTime, value: profile.max_pain_strike }]);
        carrier.createPriceLine(createMaxPainPriceLineSpec(profile.max_pain_strike));
        maxPainSeriesRef.current = carrier;
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

/**
 * Co-located FT-API client for the Seasonality widget.
 *
 * NOTE for the orchestrator: fold these helpers into
 * `@/services/ftApi.analysis.ts` when the widget is registered — they are
 * kept co-located so this widget lands without touching shared files.
 *
 * The seasonality analyser is registered at the bare ``/v1`` blueprint
 * family (``/v1/analytics/seasonality``), so it must go through `postV1` —
 * the ``/api/v1`` `post` helper would 404. Callers supply daily bars
 * (typically fetched via the shared ``/api/v1/history`` path, exactly how
 * the multi-timeframe analyser is fed).
 */

import { postV1 } from "@/services/ftApi.helpers";
import { getHistory } from "@/services/api";

// ---------------------------------------------------------------------------
// Response types (mirror flinttrade_screener.analytics_routes seasonality)
// ---------------------------------------------------------------------------

export interface SeasonalityMonthlyRow {
  month: number;
  month_name: string;
  avg_return_pct: number;
  median_return_pct: number;
  std_pct: number | null;
  positive_rate: number;
  years_count: number;
  /** `[year, return_pct]` of the strongest occurrence. */
  best_year: [number, number];
  /** `[year, return_pct]` of the weakest occurrence. */
  worst_year: [number, number];
}

export interface SeasonalityWeekdayRow {
  weekday: number;
  weekday_name: string;
  avg_return_pct: number;
  std_pct: number | null;
  positive_rate: number;
  sample_count: number;
}

export interface SeasonalityDayOfMonthRow {
  day: number;
  avg_return_pct: number;
}

export interface SeasonalityMatrix {
  years: number[];
  months: number[];
  returns: (number | null)[][];
}

export interface SeasonalityData {
  symbol: string;
  exchange: string;
  is_sample_data: boolean;
  monthly: SeasonalityMonthlyRow[];
  weekday: SeasonalityWeekdayRow[];
  day_of_month: SeasonalityDayOfMonthRow[];
  matrix: SeasonalityMatrix;
}

/** Daily bar accepted by the endpoint (epoch seconds/millis or ISO string). */
export interface SeasonalityBar {
  timestamp: number | string;
  close: number;
}

/** Compute calendar seasonality statistics from caller-supplied daily bars. */
export const getSeasonality = (
  symbol: string,
  exchange: string,
  bars: SeasonalityBar[],
) => postV1<SeasonalityData>("analytics/seasonality", { symbol, exchange, bars });

// ---------------------------------------------------------------------------
// History → analyser pipeline
// ---------------------------------------------------------------------------

/** Calendar-year lookback for the daily history request. */
export const SEASONALITY_LOOKBACK_YEARS = 10;

/** ~1 trading year — fewer daily bars gives hollow calendar statistics. */
export const MIN_DAILY_BARS = 250;

/**
 * Fetch daily bars for the instrument and run the seasonality analyser.
 *
 * Throws (rather than silently degrading) when the broker returns too little
 * history, so the widget can fail closed instead of rendering thin statistics
 * as if they were meaningful.
 */
export async function fetchSeasonality(
  symbol: string,
  exchange: string,
): Promise<SeasonalityData> {
  const end = new Date().toISOString().slice(0, 10);
  const start = new Date(
    Date.now() - SEASONALITY_LOOKBACK_YEARS * 365.25 * 24 * 3600 * 1000,
  )
    .toISOString()
    .slice(0, 10);
  const raw = await getHistory(symbol, exchange, "D", start, end);
  const bars: SeasonalityBar[] = (Array.isArray(raw) ? raw : [])
    .filter((bar) => Number.isFinite(Number(bar.close)) && Number(bar.close) > 0)
    .map((bar) => ({ timestamp: bar.timestamp, close: Number(bar.close) }));
  if (bars.length < MIN_DAILY_BARS) {
    throw new Error(
      `Not enough daily history for ${symbol} — got ${bars.length} bars, need ${MIN_DAILY_BARS}+`,
    );
  }
  return getSeasonality(symbol, exchange, bars);
}

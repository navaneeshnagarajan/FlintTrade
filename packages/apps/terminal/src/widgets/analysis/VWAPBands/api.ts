/**
 * Co-located FT-API call for the VWAPBands widget.
 *
 * POST /v1/indicators/vwap — server-side VWAP with ±1σ/2σ/3σ bands
 * (screener `analytics_routes.py` → `flinttrade_indicators.vwap_bands`).
 * The blueprint registers at the bare `/v1` family, so this goes through
 * `postV1` (NOT `post`, which targets `/api/v1` and would 404).
 *
 * NOTE (ftApi consolidation): this call belongs in `services/ftApi.analysis.ts`
 * next to the other analytics calls, but that file is orchestrator-owned during
 * the FINOS migration. When consolidating, move `postVwapBands` (and these
 * types) there and re-point the widget import.
 */

import { postV1 } from "@/services/ftApi.helpers";

/** One OHLCV bar in the shape the backend route expects (oldest-first). */
export interface VwapRequestBar {
  /** ISO wall-clock timestamp, e.g. "2025-01-15T09:15:00" (IST). */
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/**
 * Unwrapped `data` payload of POST /v1/indicators/vwap.
 *
 * All arrays share the length of the request bars. Server maths (canonical):
 * σ is the VOLUME-WEIGHTED deviation of typical price about the running VWAP
 * (anchored-VWAP bands) — not the unweighted std-dev the widget's local
 * fallback uses.
 */
export interface VwapBandsResponse {
  timestamps: string[];
  vwap: number[];
  upper_1: number[];
  upper_2: number[];
  upper_3: number[];
  lower_1: number[];
  lower_2: number[];
  lower_3: number[];
}

/**
 * Fetch server-computed VWAP bands for a single session of intraday bars.
 *
 * Never call this with an empty bar list: the backend substitutes SYNTHETIC
 * sample bars when `bars` is empty, and a caller badging the result as live
 * would violate the data-honesty rule — so an empty list throws here instead.
 */
export async function postVwapBands(
  bars: VwapRequestBar[],
  sessionReset = true,
): Promise<VwapBandsResponse> {
  if (bars.length === 0) {
    throw new Error(
      "postVwapBands requires at least one bar — the backend falls back to sample data on an empty list",
    );
  }
  return postV1<VwapBandsResponse>("indicators/vwap", {
    bars,
    session_reset: sessionReset,
  });
}

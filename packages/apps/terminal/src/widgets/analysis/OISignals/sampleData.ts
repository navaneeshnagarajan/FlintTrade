/**
 * Sample OI-signal data for the OISignals widget in explore / disconnected mode.
 *
 * Mirrors the shape of /ft-api/v1/oi/analysis and /ft-api/v1/oi/unusual so the
 * widget renders identically whether it is showing this sample or live data.
 * Also used for an unavailable half of the combined view; provenance remains
 * visibly badged whenever either half is synthetic.
 */

import type {
  OIChangeAnalysisData,
  UnusualOIData,
} from "@/services/ftApi";

export const SAMPLE_ANALYSIS: OIChangeAnalysisData = {
  is_sample_data: true,
  signals: [
    { strike: 24300, option_type: "PE", oi: 41_00_000, oi_change: 9_80_000, price_change: "up", signal: "Short Build-up", signal_short: "SB" },
    { strike: 24400, option_type: "PE", oi: 38_50_000, oi_change: 6_20_000, price_change: "up", signal: "Short Build-up", signal_short: "SB" },
    { strike: 24500, option_type: "CE", oi: 52_10_000, oi_change: -7_40_000, price_change: "up", signal: "Short Covering", signal_short: "SC" },
    { strike: 24500, option_type: "PE", oi: 47_30_000, oi_change: 11_60_000, price_change: "up", signal: "Short Build-up", signal_short: "SB" },
    { strike: 24600, option_type: "CE", oi: 44_80_000, oi_change: 8_90_000, price_change: "up", signal: "Long Build-up", signal_short: "LB" },
    { strike: 24700, option_type: "CE", oi: 39_20_000, oi_change: 5_10_000, price_change: "up", signal: "Long Build-up", signal_short: "LB" },
    { strike: 24800, option_type: "CE", oi: 33_40_000, oi_change: -4_60_000, price_change: "up", signal: "Long Unwinding", signal_short: "LU" },
  ],
  long_buildups: [24600, 24700],
  short_coverings: [24500],
  short_buildups: [24300, 24400, 24500],
  long_unwindings: [24800],
  summary: {
    "Long Build-up": 2,
    "Short Covering": 1,
    "Short Build-up": 3,
    "Long Unwinding": 1,
  },
};

export const SAMPLE_UNUSUAL: UnusualOIData = {
  is_sample_data: true,
  unusual: [
    { strike: 24500, option_type: "PE", oi: 47_30_000, oi_change: 11_60_000, change_pct: 32.5, z_score: 2.8, direction: "addition" },
    { strike: 24300, option_type: "PE", oi: 41_00_000, oi_change: 9_80_000, change_pct: 31.4, z_score: 2.4, direction: "addition" },
    { strike: 24500, option_type: "CE", oi: 52_10_000, oi_change: -7_40_000, change_pct: -12.4, z_score: -2.1, direction: "reduction" },
  ],
  count: 3,
  threshold: 2.0,
};

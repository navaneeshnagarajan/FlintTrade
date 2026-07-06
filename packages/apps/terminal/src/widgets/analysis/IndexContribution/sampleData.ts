/**
 * Sample index-contribution decomposition for demo/disconnected mode.
 * Mirrors the backend make_sample_index_contribution output.
 */

import type { IndexContribution } from "@/services/ftApi.screener";

export const SAMPLE_INDEX_CONTRIBUTION: IndexContribution = {
  index_name: "NIFTY",
  index_level: 24000,
  index_change_pct: 0.42,
  index_change_points: 100.8,
  weights_as_of: "2026-06-30",
  advancers: 34,
  decliners: 17,
  constituents: [
    { symbol: "HDFCBANK", weight: 13.2, ltp: 1015, prev_close: 1000, change_pct: 1.5, contribution_pct: 0.198, contribution_points: 47.4 },
    { symbol: "RELIANCE", weight: 9.8, ltp: 1188, prev_close: 1200, change_pct: -1.0, contribution_pct: -0.098, contribution_points: -23.5 },
    { symbol: "ICICIBANK", weight: 8.4, ltp: 1112, prev_close: 1100, change_pct: 1.09, contribution_pct: 0.092, contribution_points: 22.0 },
    { symbol: "INFY", weight: 5.6, ltp: 1485, prev_close: 1500, change_pct: -1.0, contribution_pct: -0.056, contribution_points: -13.4 },
    { symbol: "BHARTIARTL", weight: 4.2, ltp: 1618, prev_close: 1600, change_pct: 1.13, contribution_pct: 0.047, contribution_points: 11.4 },
    { symbol: "ITC", weight: 3.8, ltp: 446, prev_close: 450, change_pct: -0.89, contribution_pct: -0.034, contribution_points: -8.1 },
    { symbol: "LT", weight: 3.6, ltp: 3636, prev_close: 3600, change_pct: 1.0, contribution_pct: 0.036, contribution_points: 8.6 },
    { symbol: "SBIN", weight: 3.2, ltp: 792, prev_close: 800, change_pct: -1.0, contribution_pct: -0.032, contribution_points: -7.7 },
  ],
};

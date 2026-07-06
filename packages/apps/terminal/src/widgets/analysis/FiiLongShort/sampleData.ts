/**
 * Sample FII long/short ratio surface for demo/disconnected mode.
 * Mirrors the backend `make_sample_fii_dii` → `compute_fii_long_short` output.
 */

import type { FiiLongShortRatio } from "@/services/ftApi.screener";

export const SAMPLE_FII_LONG_SHORT: FiiLongShortRatio = {
  trade_date: "04-Apr-2026",
  segments: [
    { segment: "index_futures", label: "Index Futures", long: 125000, short: 140000, net: -15000, ls_ratio: 0.8929, long_pct: 47.17 },
    { segment: "stock_futures", label: "Stock Futures", long: 80000, short: 75000, net: 5000, ls_ratio: 1.0667, long_pct: 51.61 },
    { segment: "index_calls", label: "Index Calls", long: 90000, short: 110000, net: -20000, ls_ratio: 0.8182, long_pct: 45.0 },
    { segment: "index_puts", label: "Index Puts", long: 95000, short: 85000, net: 10000, ls_ratio: 1.1176, long_pct: 52.78 },
  ],
  futures_long: 205000,
  futures_short: 215000,
  futures_bias: 48.81,
  bias_label: "Neutral",
  updated_at: "2026-04-04 18:00:00 IST",
};

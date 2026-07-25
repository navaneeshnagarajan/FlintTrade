/**
 * Intervals offered by the spot candlestick strip.
 *
 * Kept in its own module so the widget's header can render the interval
 * buttons WITHOUT statically importing `SpotPricePane` — that module pulls in
 * lightweight-charts, and the pane is lazily loaded precisely so an OI panel
 * that never opens it does not pay for it.
 */

export const SPOT_INTERVALS = ["5m", "15m", "1h", "1D"] as const;

export type SpotInterval = (typeof SPOT_INTERVALS)[number];

/** Interval label → the resolution the history endpoint expects. */
export const SPOT_INTERVAL_RESOLUTIONS: Record<SpotInterval, string> = {
  "5m": "5",
  "15m": "15",
  "1h": "60",
  "1D": "D",
};

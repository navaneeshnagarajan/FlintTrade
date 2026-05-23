/**
 * colourScale.ts — Diverging colour scale utilities for heatmap widgets.
 *
 * Absorbed from highcharts-heatmap audit: a 9-stop diverging gradient that
 * maps negative values (losses/selling pressure) to red tones, zero to a
 * neutral grey, and positive values (gains/buying pressure) to green tones.
 *
 * Primary consumer: SectorMap treemap widget (stock colouring by % change).
 * Secondary consumers: any heatmap widget that needs a diverging scale
 * (DepthHeatmap overlay, P&L heat, GEX chart, etc.).
 *
 * Design decisions:
 *   - The breakpoints are fixed at ±4 % (beyond that, colour is clamped to
 *     the darkest red / darkest green). This matches typical intraday F&O
 *     moves — a ±4 % circuit is visually extreme.
 *   - The 9 stops follow the ColorBrewer RdYlGn-9 palette adapted for the
 *     FlintTrade dark theme (#0a0a0f background). The grey midpoint is
 *     desaturated enough to read as "flat" on dark backgrounds.
 *   - Interpolation is linear in RGB space (sufficient for this range).
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A single RGB stop on the diverging scale. */
interface ColourStop {
  /** Percentage value this stop corresponds to (–4 to +4). */
  pct: number;
  r: number;
  g: number;
  b: number;
}

// ---------------------------------------------------------------------------
// The 9-stop gradient
// ---------------------------------------------------------------------------

/**
 * Nine-stop diverging gradient from deep red (–4 %) through neutral grey
 * (0 %) to deep green (+4 %). Colours are tuned for the FlintTrade dark theme.
 */
const DIVERGING_STOPS: ColourStop[] = [
  { pct: -4.0, r: 180, g: 30,  b: 30  }, // deep red      — circuit-level loss
  { pct: -3.0, r: 200, g: 50,  b: 40  }, // red
  { pct: -2.0, r: 210, g: 90,  b: 60  }, // orange-red
  { pct: -1.0, r: 200, g: 130, b: 90  }, // muted orange
  { pct:  0.0, r: 110, g: 110, b: 120 }, // neutral grey   — flat/unchanged
  { pct:  1.0, r: 80,  g: 160, b: 100 }, // muted green
  { pct:  2.0, r: 50,  g: 180, b: 90  }, // green
  { pct:  3.0, r: 30,  g: 200, b: 80  }, // bright green
  { pct:  4.0, r: 20,  g: 210, b: 80  }, // deep green     — circuit-level gain
];

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Clamp a value to [min, max]. */
function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

/**
 * Linearly interpolate between two colour stops.
 *
 * @param a    Lower stop.
 * @param b    Upper stop.
 * @param t    Interpolation factor in [0, 1].
 * @returns    CSS `rgb(...)` string.
 */
function lerpStops(a: ColourStop, b: ColourStop, t: number): string {
  const r = Math.round(a.r + (b.r - a.r) * t);
  const g = Math.round(a.g + (b.g - a.g) * t);
  const bl = Math.round(a.b + (b.b - a.b) * t);
  return `rgb(${r},${g},${bl})`;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Map an arbitrary numeric value to a diverging colour using a fixed ±4 %
 * scale, suitable for SectorMap and other heatmap widgets.
 *
 * Values beyond ±4 % are clamped to the deepest red/green stop.
 *
 * @example
 * ```ts
 * divergingColourScale(2.5)    // → "rgb(40,190,85)"  (bright green)
 * divergingColourScale(-1.5)   // → "rgb(205,110,75)" (orange-red)
 * divergingColourScale(0)      // → "rgb(110,110,120)" (grey)
 * ```
 *
 * @param pct  Percentage change value (e.g. –3.2 for –3.2 %).
 * @returns    CSS `rgb(r,g,b)` colour string.
 */
export function divergingColourScale(pct: number): string {
  const clamped = clamp(pct, DIVERGING_STOPS[0].pct, DIVERGING_STOPS[DIVERGING_STOPS.length - 1].pct);

  // Find the two stops that bracket `clamped`
  for (let i = 0; i < DIVERGING_STOPS.length - 1; i++) {
    const lo = DIVERGING_STOPS[i];
    const hi = DIVERGING_STOPS[i + 1];
    if (clamped >= lo.pct && clamped <= hi.pct) {
      const range = hi.pct - lo.pct;
      const t = range === 0 ? 0 : (clamped - lo.pct) / range;
      return lerpStops(lo, hi, t);
    }
  }

  // Should be unreachable after clamping, but guard for type safety
  const last = DIVERGING_STOPS[DIVERGING_STOPS.length - 1];
  return `rgb(${last.r},${last.g},${last.b})`;
}

/**
 * Map a value to a diverging colour using caller-supplied min/max bounds
 * instead of the fixed ±4 % defaults. Values are normalised so that:
 *   - `min` → deep red  (equivalent to –4 %)
 *   - mid-point → grey  (equivalent to 0 %)
 *   - `max` → deep green (equivalent to +4 %)
 *
 * Useful for widgets where the value range varies (e.g. OI heatmaps, P&L
 * tables with non-percentage values).
 *
 * @param value  The data value to colour.
 * @param min    The minimum expected value (maps to deep red).
 * @param max    The maximum expected value (maps to deep green).
 * @returns      CSS `rgb(r,g,b)` colour string.
 */
export function divergingColourScaleRange(
  value: number,
  min: number,
  max: number,
): string {
  if (min === max) {
    // Degenerate range — everything is grey
    const mid = DIVERGING_STOPS[Math.floor(DIVERGING_STOPS.length / 2)];
    return `rgb(${mid.r},${mid.g},${mid.b})`;
  }

  const scaleMin = DIVERGING_STOPS[0].pct;                              // –4
  const scaleMax = DIVERGING_STOPS[DIVERGING_STOPS.length - 1].pct;    // +4

  // Normalise value into [scaleMin, scaleMax]
  const clamped = clamp(value, min, max);
  const normalised = scaleMin + ((clamped - min) / (max - min)) * (scaleMax - scaleMin);

  return divergingColourScale(normalised);
}

// Re-export the stop definitions so consumers can build legends
export { DIVERGING_STOPS };
export type { ColourStop };

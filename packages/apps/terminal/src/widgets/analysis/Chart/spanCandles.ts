/** Logical bars of blank space kept to the right of the last candle. */
export const CANDLE_SPAN_RIGHT_OFFSET = 2;

/**
 * A series fills the plot when real bars cover this share of the visible range.
 * The 7px default on a 2560 desk leaves about 40% occupied.
 */
export const CANDLE_SPAN_MIN_OCCUPANCY = 0.9;

export interface CandleSpanOptions {
  barSpacing: number;
  maxBarSpacing: number;
  rightOffset: number;
}

export interface CandleSpanTimeScale {
  width?: () => number;
  getVisibleLogicalRange?: () => { from: number; to: number } | null;
  applyOptions?: (options: CandleSpanOptions) => void;
}

/** Bar spacing that places every loaded candle across the plot. */
export function candleSpanSpacing(
  plotWidth: number,
  barCount: number,
  rightOffset = CANDLE_SPAN_RIGHT_OFFSET,
): number | null {
  if (!Number.isFinite(plotWidth) || plotWidth < 32) return null;
  if (!Number.isInteger(barCount) || barCount < 1) return null;
  if (!Number.isFinite(rightOffset) || rightOffset < 0) return null;
  return plotWidth / (barCount + rightOffset);
}

/** True when the visible logical range is already candle, not empty plot. */
export function seriesOccupiesPlot(
  visibleFrom: number,
  visibleTo: number,
  barCount: number,
  minimum = CANDLE_SPAN_MIN_OCCUPANCY,
): boolean {
  if (!Number.isFinite(visibleFrom) || !Number.isFinite(visibleTo) || visibleTo <= visibleFrom) return false;
  if (!Number.isInteger(barCount) || barCount < 1) return false;
  const visible = visibleTo - visibleFrom;
  const overlap = Math.max(0, Math.min(visibleTo, barCount) - Math.max(visibleFrom, 0));
  return overlap / visible >= minimum;
}

/**
 * Options that stretch a short series across the plot.
 * Returns null when the plot is not laid out yet, or the operator is zoomed
 * into candles that already fill the visible range.
 */
export function candleSpanOptions(
  plotWidth: number,
  barCount: number,
  visible: { from: number; to: number } | null,
): CandleSpanOptions | null {
  if (visible && seriesOccupiesPlot(visible.from, visible.to, barCount)) return null;
  const spacing = candleSpanSpacing(plotWidth, barCount);
  if (spacing == null) return null;
  return {
    barSpacing: spacing,
    maxBarSpacing: Math.max(80, Math.ceil(spacing + 1)),
    rightOffset: CANDLE_SPAN_RIGHT_OFFSET,
  };
}

/** Stretch loaded candles across the plot when they currently occupy a fraction of it. */
export function applyCandleSpan(timeScale: CandleSpanTimeScale, barCount: number): void {
  const width = timeScale.width?.() ?? 0;
  const visible = timeScale.getVisibleLogicalRange?.() ?? null;
  const options = candleSpanOptions(width, barCount, visible);
  if (!options) return;
  timeScale.applyOptions?.(options);
}

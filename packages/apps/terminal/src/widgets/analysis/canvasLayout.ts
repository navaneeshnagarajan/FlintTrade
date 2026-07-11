export interface CanvasViewport {
  width: number;
  height: number;
  dpr: number;
}

export interface FootprintCanvasLayout {
  chartBottom: number;
  deltaStripHeight: number;
  deltaStripTop: number;
  showCumulativeDelta: boolean;
  timeLabelY: number;
}

export const DEVICE_PIXEL_RATIO_CHECK_INTERVAL_MS = 250;

const FOOTPRINT_DELTA_TRANSITION_START = 96;
const FOOTPRINT_DELTA_TRANSITION_END = 160;
const FOOTPRINT_FULL_DELTA_HEIGHT = 56;
const FOOTPRINT_FULL_DELTA_GAP = 4;
const FOOTPRINT_FULL_TIME_MARGIN = 20;
const FOOTPRINT_BASE_BOTTOM_MARGIN = 4;

export function normaliseDevicePixelRatio(value: number): number {
  return Number.isFinite(value) && value > 0 ? value : 1;
}

export function hasCanvasViewportChanged(
  current: CanvasViewport,
  next: CanvasViewport,
): boolean {
  return Math.abs(current.width - next.width) >= 1
    || Math.abs(current.height - next.height) >= 1
    || Math.abs(current.dpr - next.dpr) > 0.001;
}

/**
 * Select non-overlapping time labels using their measured canvas widths.
 * The latest bucket is retained when it can replace an overlapping tail label.
 */
export function selectTimeLabelIndices(
  labels: readonly string[],
  columnWidth: number,
  measureText: (label: string) => number,
  minimumGap: number,
): number[] {
  if (labels.length === 0 || !Number.isFinite(columnWidth) || columnWidth <= 0) return [];

  const widths = labels.map((label) => Math.max(0, measureText(label)));
  const selected: number[] = [];
  let previousRight = Number.NEGATIVE_INFINITY;

  for (let index = 0; index < labels.length; index += 1) {
    const centre = (index + 0.5) * columnWidth;
    const left = centre - widths[index] / 2;
    if (left < previousRight + minimumGap) continue;
    selected.push(index);
    previousRight = centre + widths[index] / 2;
  }

  const latestIndex = labels.length - 1;
  if (selected.at(-1) === latestIndex) return selected;

  const latestLeft = (latestIndex + 0.5) * columnWidth - widths[latestIndex] / 2;
  while (selected.length > 0) {
    const previousIndex = selected.at(-1)!;
    const previousCentre = (previousIndex + 0.5) * columnWidth;
    const previousLabelRight = previousCentre + widths[previousIndex] / 2;
    if (latestLeft >= previousLabelRight + minimumGap) break;
    selected.pop();
  }
  selected.push(latestIndex);
  return selected;
}

/**
 * Gradually reserves the delta strip between 96px and 160px canvas heights.
 * This avoids a fixed-height layout switching on at a single pixel boundary.
 */
export function getFootprintCanvasLayout(height: number): FootprintCanvasLayout {
  const safeHeight = Number.isFinite(height) ? Math.max(0, height) : 0;
  const transitionRange = FOOTPRINT_DELTA_TRANSITION_END - FOOTPRINT_DELTA_TRANSITION_START;
  const progress = Math.max(
    0,
    Math.min(1, (safeHeight - FOOTPRINT_DELTA_TRANSITION_START) / transitionRange),
  );
  const accessoryHeight = (
    FOOTPRINT_FULL_DELTA_HEIGHT
    + FOOTPRINT_FULL_DELTA_GAP
    + FOOTPRINT_FULL_TIME_MARGIN
    - FOOTPRINT_BASE_BOTTOM_MARGIN
  ) * progress;
  const chartBottom = safeHeight - FOOTPRINT_BASE_BOTTOM_MARGIN - accessoryHeight;
  const deltaStripHeight = FOOTPRINT_FULL_DELTA_HEIGHT * progress;
  const deltaStripTop = chartBottom + FOOTPRINT_FULL_DELTA_GAP;

  return {
    chartBottom,
    deltaStripHeight,
    deltaStripTop,
    showCumulativeDelta: progress >= 0.5,
    timeLabelY: deltaStripTop + deltaStripHeight + 3,
  };
}

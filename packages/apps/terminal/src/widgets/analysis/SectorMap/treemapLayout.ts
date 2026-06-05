/**
 * Squarified treemap layout — FlintTrade's own implementation.
 *
 * Packs weighted items into a rectangle as tiles whose aspect ratios are kept
 * as close to square as possible, following the published squarified-treemap
 * method (Bruls, Huizing & van Wijk, 2000). Items are laid out as strips along
 * the shorter edge of the remaining free rectangle; a strip keeps absorbing
 * items while doing so does not worsen its worst aspect ratio, then it is fixed
 * and the algorithm recurses on the leftover rectangle.
 *
 * Output API (signature + TreemapLayoutItem shape) is stable so the widget and
 * the other render modes can rely on it.
 */

import type { TreemapItem, TreemapLayoutItem } from "./types";

interface FreeRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface ScaledItem {
  item: TreemapItem;
  /** Pixel area this item should occupy within the target rectangle. */
  area: number;
}

/**
 * Worst (largest) aspect ratio produced by laying `areas` as a strip of the
 * given total `stripArea` along an edge of length `side`. Lower is squarer.
 */
function worstAspectRatio(areas: number[], stripArea: number, side: number): number {
  if (stripArea <= 0 || side <= 0) return Infinity;
  const thickness = stripArea / side;
  let worst = 0;
  for (const area of areas) {
    if (area <= 0) continue;
    const length = area / thickness;
    const ratio = Math.max(thickness / length, length / thickness);
    if (ratio > worst) worst = ratio;
  }
  return worst;
}

export function calculateTreemapLayout(
  items: TreemapItem[],
  x: number,
  y: number,
  width: number,
  height: number,
): TreemapLayoutItem[] {
  if (items.length === 0 || width <= 0 || height <= 0) return [];

  const totalValue = items.reduce((sum, it) => sum + Math.max(0, it.value), 0);
  if (totalValue <= 0) return [];

  // Map each value onto a pixel area proportional to the target rectangle.
  const rectArea = width * height;
  const scaled: ScaledItem[] = items.map((item) => ({
    item,
    area: (Math.max(0, item.value) / totalValue) * rectArea,
  }));

  const out: TreemapLayoutItem[] = [];
  const free: FreeRect = { x, y, width, height };
  let cursor = 0; // index into `scaled`

  while (cursor < scaled.length) {
    const side = Math.min(free.width, free.height); // strip runs along the shorter edge
    const strip: ScaledItem[] = [scaled[cursor]];
    let stripArea = scaled[cursor].area;
    let bestRatio = worstAspectRatio([stripArea], stripArea, side);
    let nextIdx = cursor + 1;

    // Extend the strip while the worst aspect ratio does not get worse.
    while (nextIdx < scaled.length) {
      const candidateAreas = strip.map((s) => s.area).concat(scaled[nextIdx].area);
      const candidateArea = stripArea + scaled[nextIdx].area;
      const candidateRatio = worstAspectRatio(candidateAreas, candidateArea, side);
      if (candidateRatio > bestRatio) break;
      strip.push(scaled[nextIdx]);
      stripArea = candidateArea;
      bestRatio = candidateRatio;
      nextIdx += 1;
    }

    // Fix the strip. Its `thickness` is consumed from the longer edge; each
    // item's `length` runs along the shorter edge (`side`).
    const wideRect = free.width >= free.height;
    const thickness = stripArea / side;
    let along = wideRect ? free.y : free.x;

    for (const { item, area } of strip) {
      const length = thickness > 0 ? area / thickness : 0;
      if (wideRect) {
        out.push({ ...item, x: free.x, y: along, width: thickness, height: length });
      } else {
        out.push({ ...item, x: along, y: free.y, width: length, height: thickness });
      }
      along += length;
    }

    // Carve the placed strip out of the free rectangle.
    if (wideRect) {
      free.x += thickness;
      free.width -= thickness;
    } else {
      free.y += thickness;
      free.height -= thickness;
    }

    cursor = nextIdx;
  }

  return out;
}

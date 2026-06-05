/**
 * treemapLayout.test — correctness of FlintTrade's squarified treemap.
 */

import { describe, it, expect } from "vitest";
import { calculateTreemapLayout } from "../treemapLayout";
import type { TreemapItem } from "../types";

const items = (...values: number[]): TreemapItem[] =>
  values.map((value, i) => ({ value, label: `i${i}` }));

describe("calculateTreemapLayout", () => {
  it("returns nothing for empty input or a degenerate rectangle", () => {
    expect(calculateTreemapLayout([], 0, 0, 100, 100)).toEqual([]);
    expect(calculateTreemapLayout(items(1, 2), 0, 0, 0, 100)).toEqual([]);
    expect(calculateTreemapLayout(items(0, 0), 0, 0, 100, 100)).toEqual([]);
  });

  it("fills the whole rectangle with a single item", () => {
    const [tile] = calculateTreemapLayout(items(5), 10, 20, 100, 60);
    expect(tile).toMatchObject({ x: 10, y: 20, width: 100, height: 60 });
  });

  it("allocates total tile area equal to the rectangle area", () => {
    const layout = calculateTreemapLayout(items(3, 1, 1, 5, 2), 0, 0, 200, 120);
    const totalArea = layout.reduce((sum, t) => sum + t.width * t.height, 0);
    expect(totalArea).toBeCloseTo(200 * 120, 4);
  });

  it("keeps tile areas proportional to item values", () => {
    const layout = calculateTreemapLayout(items(1, 3), 0, 0, 100, 100);
    const a0 = layout[0].width * layout[0].height;
    const a1 = layout[1].width * layout[1].height;
    // Item 1 has 3x the value, so ~3x the area.
    expect(a1 / a0).toBeCloseTo(3, 1);
  });

  it("keeps every tile inside the bounding rectangle", () => {
    const layout = calculateTreemapLayout(items(4, 2, 7, 1, 3, 6), 5, 5, 300, 180);
    for (const t of layout) {
      expect(t.x).toBeGreaterThanOrEqual(5 - 1e-6);
      expect(t.y).toBeGreaterThanOrEqual(5 - 1e-6);
      expect(t.x + t.width).toBeLessThanOrEqual(5 + 300 + 1e-6);
      expect(t.y + t.height).toBeLessThanOrEqual(5 + 180 + 1e-6);
    }
  });

  it("preserves item count and passes through extra fields", () => {
    const layout = calculateTreemapLayout(items(2, 2, 2), 0, 0, 90, 90);
    expect(layout).toHaveLength(3);
    expect(layout[0].label).toBe("i0");
  });
});

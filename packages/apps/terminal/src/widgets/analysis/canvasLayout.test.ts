import { describe, expect, it, vi } from "vitest";

import {
  getFootprintCanvasLayout,
  hasCanvasViewportChanged,
  normaliseDevicePixelRatio,
  selectTimeLabelIndices,
} from "./canvasLayout";

describe("analysis canvas layout", () => {
  it("treats a DPR-only transition as a backing-store change", () => {
    expect(hasCanvasViewportChanged(
      { width: 520, height: 140, dpr: 1 },
      { width: 520, height: 140, dpr: 2 },
    )).toBe(true);
  });

  it("normalises invalid DPR values without discarding fractional DPR", () => {
    expect(normaliseDevicePixelRatio(0)).toBe(1);
    expect(normaliseDevicePixelRatio(Number.NaN)).toBe(1);
    expect(normaliseDevicePixelRatio(1.25)).toBe(1.25);
  });

  it("measures and subsamples twenty HH:MM:SS labels without overlap", () => {
    const labels = Array.from(
      { length: 20 },
      (_, index) => `09:${String(15 + index).padStart(2, "0")}:00`,
    );
    const measure = vi.fn((label: string) => label.length * 6);
    const columnWidth = 22;
    const indices = selectTimeLabelIndices(labels, columnWidth, measure, 4);

    expect(measure).toHaveBeenCalledTimes(20);
    expect(indices.length).toBeGreaterThan(1);
    expect(indices.length).toBeLessThan(20);
    expect(indices.at(-1)).toBe(19);
    for (let position = 1; position < indices.length; position += 1) {
      const previous = indices[position - 1];
      const current = indices[position];
      const previousRight = (previous + 0.5) * columnWidth + measure(labels[previous]) / 2;
      const currentLeft = (current + 0.5) * columnWidth - measure(labels[current]) / 2;
      expect(currentLeft - previousRight).toBeGreaterThanOrEqual(4);
    }
  });

  it("keeps the delta layout continuous across 139px and 140px", () => {
    const at139 = getFootprintCanvasLayout(139);
    const at140 = getFootprintCanvasLayout(140);

    expect(at139.showCumulativeDelta).toBe(true);
    expect(at140.showCumulativeDelta).toBe(true);
    expect(Math.abs(at140.chartBottom - at139.chartBottom)).toBeLessThan(1);
    expect(Math.abs(at140.deltaStripHeight - at139.deltaStripHeight)).toBeLessThan(1);
    expect(getFootprintCanvasLayout(64).showCumulativeDelta).toBe(false);
  });
});

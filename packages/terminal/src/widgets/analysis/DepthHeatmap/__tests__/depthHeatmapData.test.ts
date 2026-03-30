import { describe, it, expect } from "vitest";
import {
  generateDepthHeatmapData,
  shiftAndAppendColumn,
} from "../depthHeatmapData";

describe("generateDepthHeatmapData", () => {
  it("generates data with correct dimensions", () => {
    const data = generateDepthHeatmapData(100, 30, 1);
    expect(data.priceLevels).toHaveLength(100);
    expect(data.timeLabels).toHaveLength(30);
    expect(data.grid).toHaveLength(100);
    expect(data.grid[0]).toHaveLength(30);
  });

  it("generates default dimensions (200 x 50)", () => {
    const data = generateDepthHeatmapData();
    expect(data.priceLevels).toHaveLength(200);
    expect(data.timeLabels).toHaveLength(50);
    expect(data.grid).toHaveLength(200);
    expect(data.grid[0]).toHaveLength(50);
  });

  it("produces price levels in ascending order", () => {
    const data = generateDepthHeatmapData(50, 10, 7);
    for (let i = 1; i < data.priceLevels.length; i++) {
      expect(data.priceLevels[i]).toBeGreaterThan(data.priceLevels[i - 1]);
    }
  });

  it("tracks maxVolume correctly", () => {
    const data = generateDepthHeatmapData(50, 10, 99);
    let computedMax = 0;
    for (const row of data.grid) {
      for (const cell of row) {
        computedMax = Math.max(computedMax, cell.bidVolume, cell.askVolume);
      }
    }
    expect(data.maxVolume).toBe(computedMax);
  });

  it("has non-negative volumes in all cells", () => {
    const data = generateDepthHeatmapData(100, 30, 42);
    for (const row of data.grid) {
      for (const cell of row) {
        expect(cell.bidVolume).toBeGreaterThanOrEqual(0);
        expect(cell.askVolume).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("produces deterministic output with same seed", () => {
    const a = generateDepthHeatmapData(20, 5, 123);
    const b = generateDepthHeatmapData(20, 5, 123);
    expect(a.grid).toEqual(b.grid);
    expect(a.maxVolume).toBe(b.maxVolume);
  });

  it("produces different output with different seeds", () => {
    const a = generateDepthHeatmapData(20, 5, 1);
    const b = generateDepthHeatmapData(20, 5, 2);
    // Very unlikely to be identical
    const aSum = a.grid.flat().reduce((s, c) => s + c.bidVolume + c.askVolume, 0);
    const bSum = b.grid.flat().reduce((s, c) => s + c.bidVolume + c.askVolume, 0);
    expect(aSum).not.toBe(bSum);
  });

  it("has currentPriceIndex within valid range", () => {
    const data = generateDepthHeatmapData(100, 30, 42);
    expect(data.currentPriceIndex).toBeGreaterThanOrEqual(0);
    expect(data.currentPriceIndex).toBeLessThan(data.priceLevels.length);
  });
});

describe("shiftAndAppendColumn", () => {
  it("preserves grid dimensions after shift", () => {
    const initial = generateDepthHeatmapData(50, 20, 10);
    const shifted = shiftAndAppendColumn(initial, 11);
    expect(shifted.priceLevels).toHaveLength(50);
    expect(shifted.timeLabels).toHaveLength(20);
    expect(shifted.grid).toHaveLength(50);
    expect(shifted.grid[0]).toHaveLength(20);
  });

  it("shifts time labels left (drops oldest, adds newest)", () => {
    const initial = generateDepthHeatmapData(10, 5, 1);
    const shifted = shiftAndAppendColumn(initial, 2);
    // First 4 labels of shifted should be last 4 of initial
    expect(shifted.timeLabels[0]).toBe(initial.timeLabels[1]);
    expect(shifted.timeLabels[1]).toBe(initial.timeLabels[2]);
    expect(shifted.timeLabels[2]).toBe(initial.timeLabels[3]);
    expect(shifted.timeLabels[3]).toBe(initial.timeLabels[4]);
  });

  it("does not mutate the original data", () => {
    const initial = generateDepthHeatmapData(10, 5, 1);
    const originalGrid00 = initial.grid[0][0];
    shiftAndAppendColumn(initial, 2);
    expect(initial.grid[0][0]).toBe(originalGrid00);
    expect(initial.timeLabels).toHaveLength(5);
  });

  it("keeps price levels unchanged", () => {
    const initial = generateDepthHeatmapData(30, 10, 5);
    const shifted = shiftAndAppendColumn(initial, 6);
    expect(shifted.priceLevels).toEqual(initial.priceLevels);
  });

  it("has non-negative volumes in new column", () => {
    const initial = generateDepthHeatmapData(50, 20, 42);
    const shifted = shiftAndAppendColumn(initial, 43);
    const lastColIdx = shifted.timeLabels.length - 1;
    for (const row of shifted.grid) {
      const cell = row[lastColIdx];
      expect(cell.bidVolume).toBeGreaterThanOrEqual(0);
      expect(cell.askVolume).toBeGreaterThanOrEqual(0);
    }
  });
});

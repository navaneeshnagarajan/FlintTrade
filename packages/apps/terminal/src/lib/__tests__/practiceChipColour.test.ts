import { describe, expect, it } from "vitest";
import { contrastRatio } from "../contrastUtils";
import {
  LIVE_CHIP_ON_DARK,
  LIVE_CHIP_ON_LIGHT,
  liveChipColour,
  mixSrgb,
  PRACTICE_CHIP_ON_DARK,
  PRACTICE_CHIP_ON_LIGHT,
  PRACTICE_CHIP_WASH,
  practiceChipColour,
} from "../colourMix";

describe("practice chip colour", () => {
  it("clears 4.5:1 on the light and dark amber washes", () => {
    expect(PRACTICE_CHIP_ON_LIGHT).toBe("#6b4500");
    expect(PRACTICE_CHIP_ON_DARK).toBe("#ffb900");
    expect(practiceChipColour("#ffffff")).toBe(PRACTICE_CHIP_ON_LIGHT);
    expect(practiceChipColour("#0a0a0f")).toBe(PRACTICE_CHIP_ON_DARK);
    // The measured light chip was #ffb900 on #feefd9 (1.52:1).
    expect(contrastRatio("#ffb900", "#feefd9")).toBeLessThan(4.5);
    expect(contrastRatio(PRACTICE_CHIP_ON_LIGHT, "#feefd9")).toBeGreaterThanOrEqual(4.5);
    for (const weight of [0.15, 0.25]) {
      const light = mixSrgb(PRACTICE_CHIP_WASH, weight, "#ffffff");
      const dark = mixSrgb(PRACTICE_CHIP_WASH, weight, "#0c0c14");
      expect(contrastRatio(PRACTICE_CHIP_ON_LIGHT, light)).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(PRACTICE_CHIP_ON_DARK, dark)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps the light Live chip at about 5.9:1 and leaves dark ink unchanged", () => {
    expect(LIVE_CHIP_ON_DARK).toBe("#22c55e");
    expect(LIVE_CHIP_ON_LIGHT).toBe("#0f5c2c");
    expect(liveChipColour("#ffffff")).toBe(LIVE_CHIP_ON_LIGHT);
    expect(liveChipColour("#0a0a0f")).toBe(LIVE_CHIP_ON_DARK);
    // Light Live text is profit green at 20% over the light chrome.
    const wash = mixSrgb("#166534", 0.2, "#fefeff");
    expect(contrastRatio("#15803d", "#d1fae5")).toBe(4.42);
    expect(contrastRatio(LIVE_CHIP_ON_LIGHT, wash)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(LIVE_CHIP_ON_LIGHT, wash)).toBeCloseTo(5.9, 1);
    expect(contrastRatio(LIVE_CHIP_ON_DARK, "#0c0c14")).toBeGreaterThanOrEqual(4.5);
  });
});

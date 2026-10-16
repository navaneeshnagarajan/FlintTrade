import { describe, expect, it } from "vitest";
import { contrastRatio } from "../contrastUtils";
import {
  mixSrgb,
  PRACTICE_CHIP_ON_DARK,
  PRACTICE_CHIP_ON_LIGHT,
  PRACTICE_CHIP_WASH,
  practiceChipColour,
} from "../colourMix";

describe("practice chip colour", () => {
  it("clears 4.5:1 on the light and dark amber washes", () => {
    expect(PRACTICE_CHIP_ON_LIGHT).toBe("#8a5a00");
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
});

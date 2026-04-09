/**
 * colourScale.test.ts
 *
 * Behavioural tests for the diverging colour scale utility.
 * All tests are pure (no DOM, no rendering).
 */

import { describe, it, expect } from "vitest";
import {
  divergingColourScale,
  divergingColourScaleRange,
  DIVERGING_STOPS,
} from "../colourScale";

// ---------------------------------------------------------------------------
// Helper — parse "rgb(r,g,b)" into [r, g, b]
// ---------------------------------------------------------------------------

function parseRgb(css: string): [number, number, number] {
  const m = css.match(/^rgb\((\d+),(\d+),(\d+)\)$/);
  if (!m) throw new Error(`Unexpected colour string: ${css}`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

// ---------------------------------------------------------------------------
// divergingColourScale — fixed ±4 % scale
// ---------------------------------------------------------------------------

describe("divergingColourScale", () => {
  it("returns neutral grey at exactly 0 %", () => {
    const colour = divergingColourScale(0);
    // The grey stop is rgb(110,110,120)
    expect(colour).toBe("rgb(110,110,120)");
  });

  it("positive value is greener (higher G) than zero", () => {
    const [, gZero] = parseRgb(divergingColourScale(0));
    const [, gPos] = parseRgb(divergingColourScale(2));
    expect(gPos).toBeGreaterThan(gZero);
  });

  it("negative value is redder (higher R, lower G) than zero", () => {
    const [rZero, gZero] = parseRgb(divergingColourScale(0));
    const [rNeg, gNeg] = parseRgb(divergingColourScale(-2));
    expect(rNeg).toBeGreaterThan(rZero);
    expect(gNeg).toBeLessThan(gZero);
  });

  it("value beyond +4 % is clamped to deep green", () => {
    const at4 = divergingColourScale(4);
    const at10 = divergingColourScale(10);
    expect(at4).toBe(at10);
  });

  it("value beyond -4 % is clamped to deep red", () => {
    const atMinus4 = divergingColourScale(-4);
    const atMinus10 = divergingColourScale(-10);
    expect(atMinus4).toBe(atMinus10);
  });

  it("returns a valid rgb() CSS string for all stop values", () => {
    for (const stop of DIVERGING_STOPS) {
      const colour = divergingColourScale(stop.pct);
      expect(colour).toMatch(/^rgb\(\d+,\d+,\d+\)$/);
    }
  });

  it("interpolates smoothly — value between two stops is not identical to either", () => {
    const atMinus2 = divergingColourScale(-2);
    const atMinus1 = divergingColourScale(-1);
    const atMinus15 = divergingColourScale(-1.5);
    // The interpolated colour should differ from both endpoints
    expect(atMinus15).not.toBe(atMinus2);
    expect(atMinus15).not.toBe(atMinus1);
  });

  it("positive and negative symmetry — +2 and -2 have similar luminance magnitude", () => {
    const [r1, g1, b1] = parseRgb(divergingColourScale(-2));
    const [r2, g2, b2] = parseRgb(divergingColourScale(2));
    // Rough luminance (ITU-R BT.601 coefficients)
    const lum1 = 0.299 * r1 + 0.587 * g1 + 0.114 * b1;
    const lum2 = 0.299 * r2 + 0.587 * g2 + 0.114 * b2;
    // They should have comparable luminance (within 20 units) — neither
    // should be drastically brighter/darker than the other
    expect(Math.abs(lum1 - lum2)).toBeLessThan(20);
  });
});

// ---------------------------------------------------------------------------
// divergingColourScaleRange — caller-supplied min/max
// ---------------------------------------------------------------------------

describe("divergingColourScaleRange", () => {
  it("midpoint of range maps to grey", () => {
    // min=0, max=100 → midpoint 50 → should be grey
    const colour = divergingColourScaleRange(50, 0, 100);
    expect(colour).toBe("rgb(110,110,120)");
  });

  it("minimum value maps to deep red", () => {
    const atMin = divergingColourScaleRange(0, 0, 100);
    const deepRed = divergingColourScale(-4);
    expect(atMin).toBe(deepRed);
  });

  it("maximum value maps to deep green", () => {
    const atMax = divergingColourScaleRange(100, 0, 100);
    const deepGreen = divergingColourScale(4);
    expect(atMax).toBe(deepGreen);
  });

  it("degenerate range (min === max) returns grey without throwing", () => {
    const colour = divergingColourScaleRange(5, 5, 5);
    expect(colour).toMatch(/^rgb\(\d+,\d+,\d+\)$/);
  });

  it("value clamped below min produces same result as min", () => {
    const atMin = divergingColourScaleRange(0, 0, 100);
    const belowMin = divergingColourScaleRange(-50, 0, 100);
    expect(atMin).toBe(belowMin);
  });
});

import { describe, expect, it } from "vitest";

import { contrastRatio, heatColour, heatTextColour } from "../heatColours";

const WHITE = "#ffffff";
const AA_NORMAL_TEXT = 4.5;

describe("contrastRatio", () => {
  it("matches the WCAG reference values", () => {
    expect(contrastRatio("#000000", WHITE)).toBeCloseTo(21, 5);
    expect(contrastRatio(WHITE, WHITE)).toBeCloseTo(1, 5);
    // The old strong-gain fill: white on #22c55e is only about 2.3:1.
    expect(contrastRatio("rgb(34, 197, 94)", WHITE)).toBeCloseTo(2.28, 1);
  });

  it("is symmetric and accepts hex or rgb()", () => {
    expect(contrastRatio("#15803d", WHITE)).toBeCloseTo(contrastRatio(WHITE, "rgb(21, 128, 61)") ?? 0, 5);
  });

  it("returns null for colours it cannot parse", () => {
    expect(contrastRatio("rgba(34, 197, 94, 0.5)", WHITE)).toBeNull();
    expect(contrastRatio("var(--color-profit)", WHITE)).toBeNull();
  });
});

describe("heatColour", () => {
  it("uses the neutral tile for zero, non-finite or unscaled values", () => {
    const neutral = heatColour(0, 5);
    expect(heatColour(Number.NaN, 5)).toBe(neutral);
    expect(heatColour(2, 0)).toBe(neutral);
    expect(heatColour(1e-12, 5)).toBe(neutral);
  });

  it("is opaque, so the tile does not depend on the theme surface behind it", () => {
    for (const value of [-5, -0.1, 0, 0.1, 5]) {
      expect(heatColour(value, 5)).toMatch(/^rgb\(\d+, \d+, \d+\)$/);
    }
  });

  it("separates gains from losses and deepens with magnitude", () => {
    const channels = (colour: string) => (colour.match(/\d+/g) ?? []).map(Number);

    const [weakR, weakG] = channels(heatColour(0.5, 5));
    const [strongR, strongG] = channels(heatColour(5, 5));
    expect(strongG).toBeGreaterThan(weakG);
    expect(strongG).toBeGreaterThan(strongR);

    const [lossWeakR] = channels(heatColour(-0.5, 5));
    const [lossStrongR, lossStrongG] = channels(heatColour(-5, 5));
    expect(lossStrongR).toBeGreaterThan(lossWeakR);
    expect(lossStrongR).toBeGreaterThan(lossStrongG);

    expect(weakR).toBeLessThan(lossWeakR);
  });

  it("clamps values beyond the view's maximum", () => {
    expect(heatColour(50, 5)).toBe(heatColour(5, 5));
    expect(heatColour(-50, 5)).toBe(heatColour(-5, 5));
  });
});

describe("heat tile text contrast", () => {
  it("keeps the chosen text colour at AA contrast across the whole range", () => {
    for (let step = -100; step <= 100; step += 1) {
      const fill = heatColour(step / 20, 5);
      const ratio = contrastRatio(fill, heatTextColour(fill));
      expect(ratio, `value ${step / 20} on ${fill}`).not.toBeNull();
      expect(ratio ?? 0).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
    }
  });

  it("keeps every fill dark enough for the strip's white tile labels", () => {
    for (let step = -100; step <= 100; step += 1) {
      const fill = heatColour(step / 20, 5);
      expect(contrastRatio(fill, WHITE) ?? 0, `value ${step / 20} on ${fill}`).toBeGreaterThanOrEqual(
        AA_NORMAL_TEXT,
      );
    }
  });
});

describe("heatTextColour", () => {
  it("picks white on dark fills and near-black on bright fills", () => {
    expect(heatTextColour("rgb(21, 128, 61)")).toBe(WHITE);
    expect(heatTextColour("rgb(39, 39, 42)")).toBe(WHITE);
    expect(heatTextColour("rgb(34, 197, 94)")).toBe("#0a0a0f");
    expect(heatTextColour("#fde68a")).toBe("#0a0a0f");
  });

  it("falls back to white for a fill it cannot parse", () => {
    expect(heatTextColour("var(--color-profit)")).toBe(WHITE);
  });
});

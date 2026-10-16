import { describe, expect, it } from "vitest";
import { contrastRatio } from "../contrastUtils";
import { tickerVenueColour } from "../colourMix";

describe("ticker venue colour", () => {
  it("clears 4.5:1 on Graphite dark and light surfaces", () => {
    const dark = tickerVenueColour("#0a0a0f");
    const light = tickerVenueColour("#f5f5f7");
    expect(contrastRatio(dark, "#0a0a0f")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(light, "#f5f5f7")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(dark, "#13141a")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(light, "#ffffff")).toBeGreaterThanOrEqual(4.5);
  });
});

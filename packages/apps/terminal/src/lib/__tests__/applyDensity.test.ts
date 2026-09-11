import { afterEach, describe, expect, it } from "vitest";
import { applyDensityToDocument, DENSITY_ATTRIBUTE } from "../applyDensity";

describe("applyDensityToDocument", () => {
  afterEach(() => {
    document.documentElement.removeAttribute(DENSITY_ATTRIBUTE);
    document.documentElement.classList.remove("density-compact", "density-comfortable");
  });

  it("writes data-density and the matching html class", () => {
    applyDensityToDocument("comfortable");
    expect(document.documentElement.getAttribute(DENSITY_ATTRIBUTE)).toBe("comfortable");
    expect(document.documentElement.classList.contains("density-comfortable")).toBe(true);
    expect(document.documentElement.classList.contains("density-compact")).toBe(false);

    applyDensityToDocument("compact");
    expect(document.documentElement.getAttribute(DENSITY_ATTRIBUTE)).toBe("compact");
    expect(document.documentElement.classList.contains("density-compact")).toBe(true);
    expect(document.documentElement.classList.contains("density-comfortable")).toBe(false);
  });
});

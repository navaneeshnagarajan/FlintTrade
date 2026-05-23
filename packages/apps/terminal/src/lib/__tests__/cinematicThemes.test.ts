import { describe, expect, it } from "vitest";
import { CINEMATIC_THEMES } from "../cinematicThemes";
import { contrastRatio } from "../contrastUtils";

describe("cinematic theme contrast", () => {
  it("keeps light-mode accents readable on light surfaces", () => {
    const failures = CINEMATIC_THEMES
      .map((theme) => ({
        id: theme.id,
        ratio: contrastRatio(theme.light.colors.accent, theme.light.colors.card),
      }))
      .filter(({ ratio }) => ratio < 4.5);

    expect(failures).toEqual([]);
  });
});

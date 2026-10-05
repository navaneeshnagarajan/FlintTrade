import { describe, expect, it } from "vitest";
import { CINEMATIC_THEMES } from "../cinematicThemes";
import { contrastRatio } from "../contrastUtils";

const MODES = ["dark", "light"] as const;

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

  it("keeps secondary and muted copy at WCAG AA on page and card surfaces", () => {
    const failures = CINEMATIC_THEMES.flatMap((theme) =>
      MODES.flatMap((mode) => {
        const { base, card, textSecondary, textMuted } = theme[mode].colors;
        return [
          { role: "textSecondary", colour: textSecondary },
          { role: "textMuted", colour: textMuted },
        ].flatMap(({ role, colour }) =>
          [base, card]
            .map((surface) => ({
              id: `${theme.id}.${mode}.${role}`,
              ratio: contrastRatio(colour, surface),
            }))
            .filter(({ ratio }) => ratio < 4.5),
        );
      }),
    );

    expect(failures).toEqual([]);
  });

  it("ranks secondary copy above muted copy in every mode", () => {
    const inverted = CINEMATIC_THEMES.flatMap((theme) =>
      MODES.filter((mode) => {
        const { base, textSecondary, textMuted } = theme[mode].colors;
        return contrastRatio(textSecondary, base) <= contrastRatio(textMuted, base);
      }).map((mode) => `${theme.id}.${mode}`),
    );

    expect(inverted).toEqual([]);
  });
});

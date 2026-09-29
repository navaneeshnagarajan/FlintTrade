/**
 * tabContrast.test.ts
 *
 * Dark unselected tray and panel tabs paint `--fl-color-tab-unselected`
 * (primary mixed toward secondary). That mix has to stay at least 4.5:1
 * on the lightest surface each tab sits on: the elevated tray bar, and
 * the card panel header. Light-theme Dismiss and Show/Hide hover text is
 * primary text on the surface hover fill, and that pair has to clear the
 * same bar.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";

import { CINEMATIC_THEMES } from "../cinematicThemes";
import {
  UNSELECTED_TAB_PRIMARY_WEIGHT,
  elevatedSurfaceColour,
  mixSrgb,
  unselectedTabColour,
} from "../colourMix";
import { contrastRatio } from "../contrastUtils";
import { useThemeStore } from "@/stores/themeStore";

const AA = 4.5;
const terminalCss = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../../terminal.css"),
  "utf8",
);

/** Primary percentage on `--fl-color-tab-unselected`, as CSS writes it. */
function declaredPrimaryWeight(css: string): number {
  const match = css.match(
    /--fl-color-tab-unselected:\s*color-mix\(\s*in srgb\s*,\s*var\(\s*--color-text-primary\s*,\s*#[0-9a-fA-F]{3,8}\s*\)\s*(\d+(?:\.\d+)?)%/,
  );
  if (!match) {
    throw new Error("terminal.css is missing the --fl-color-tab-unselected color-mix");
  }
  return Number(match[1]) / 100;
}

function resetTheme(): void {
  useThemeStore.setState({
    activeThemeId: "graphite",
    mode: "dark",
    customThemes: [],
    reduceMotion: false,
    glass: true,
  });
  document.documentElement.removeAttribute("style");
}

describe("unselected tab contrast", () => {
  const primaryWeight = declaredPrimaryWeight(terminalCss);

  beforeEach(() => {
    resetTheme();
  });

  it("resolves --fl-color-tab-unselected with the shared mix", () => {
    expect(primaryWeight).toBe(UNSELECTED_TAB_PRIMARY_WEIGHT);
    expect(terminalCss).toMatch(
      /\.flexlayout__theme_dark \.flexlayout__tab_button,[\s\S]*?color:\s*var\(--fl-color-tab-unselected\)/,
    );
    expect(terminalCss).toContain('html[data-mode="dark"] .ft-tray-tab:not([aria-selected="true"])');
  });

  it("keeps every dark theme's unselected tabs at 4.5:1 on the tray and the panel header", () => {
    expect(CINEMATIC_THEMES.map((theme) => theme.id)).toEqual(
      expect.arrayContaining(["graphite", "midnight", "ember"]),
    );

    const failures: string[] = [];
    for (const theme of CINEMATIC_THEMES) {
      const { text, textSecondary, card } = theme.dark.colors;
      const foreground = mixSrgb(text, primaryWeight, textSecondary);
      expect(foreground).toBe(unselectedTabColour(text, textSecondary));

      const surfaces: Array<[string, string]> = [
        ["elevated tray", elevatedSurfaceColour(card)],
        ["card header", card],
      ];
      for (const [name, background] of surfaces) {
        const ratio = contrastRatio(foreground, background);
        if (ratio < AA) {
          failures.push(`${theme.id} ${name} ${ratio}:1`);
        }
      }
    }

    expect(failures).toEqual([]);
  });

  it("publishes that mix and the elevated tray from the active dark theme", () => {
    for (const theme of CINEMATIC_THEMES) {
      useThemeStore.setState({ activeThemeId: theme.id, mode: "dark" });
      useThemeStore.getState().applyTheme();
      const root = document.documentElement.style;
      expect(root.getPropertyValue("--fl-color-tab-unselected").trim()).toBe(
        unselectedTabColour(theme.dark.colors.text, theme.dark.colors.textSecondary),
      );
      expect(root.getPropertyValue("--color-surface-elevated").trim()).toBe(
        elevatedSurfaceColour(theme.dark.colors.card),
      );
    }
  });

  it("keeps light-theme Dismiss and Show/Hide hover text at 4.5:1", () => {
    const failures: string[] = [];
    for (const theme of CINEMATIC_THEMES) {
      const ratio = contrastRatio(theme.light.colors.text, theme.light.colors.cardHover);
      if (ratio < AA) {
        failures.push(`${theme.id} primary on surface hover ${ratio}:1`);
      }
    }
    expect(failures).toEqual([]);
  });
});

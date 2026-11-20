import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";

import { contrastRatio } from "@/lib/contrastUtils";
import { useThemeStore } from "../themeStore";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../../../../../core/design-system/src/tokens.css"),
  "utf8",
);
const LIGHT_SURFACES = ["#ffffff", "#f5f5f7", "#f8f8fa"];
const AA = 4.5;

function hslToHex(value: string): string {
  const match = value.match(/(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%/);
  if (!match) throw new Error(`not hsl: ${value}`);
  const hue = Number(match[1]);
  const saturation = Number(match[2]) / 100;
  const lightness = Number(match[3]) / 100;
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const channel = chroma * (1 - Math.abs(((hue / 60) % 2) - 1));
  const mix = lightness - chroma / 2;
  const segment = [
    [chroma, channel, 0],
    [channel, chroma, 0],
    [0, chroma, channel],
    [0, channel, chroma],
    [channel, 0, chroma],
    [chroma, 0, channel],
  ][Math.floor(hue / 60) % 6] ?? [0, 0, 0];
  const hex = segment
    .map((part) => Math.round((part + mix) * 255).toString(16).padStart(2, "0"))
    .join("");
  return `#${hex}`;
}

function declared(block: string, name: string): string {
  const match = block.match(new RegExp(`${name}:\\s*([^;]+);`));
  if (!match?.[1]) throw new Error(`${name} missing`);
  return match[1].trim();
}

describe("light theme contrast", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("style");
    useThemeStore.setState({ activeThemeId: "graphite", mode: "light", customThemes: [] });
    useThemeStore.getState().applyTheme();
  });

  it("keeps muted and destructive text at 4.5:1 on light surfaces", () => {
    const light = css.slice(css.indexOf(":root:not(.dark)"), css.indexOf("/* Bright Tailwind"));
    const muted = hslToHex(declared(light, "--muted-foreground"));
    const destructive = hslToHex(declared(light, "--destructive"));
    const applied = hslToHex(
      document.documentElement.style.getPropertyValue("--muted-foreground").trim(),
    );
    for (const surface of LIGHT_SURFACES) {
      expect(contrastRatio(muted, surface)).toBeGreaterThanOrEqual(AA);
      expect(contrastRatio(destructive, surface)).toBeGreaterThanOrEqual(AA);
      expect(contrastRatio(applied, surface)).toBeGreaterThanOrEqual(AA);
    }
  });

  it("keeps light semantic inks at 4.5:1 before and after the theme class", () => {
    const media = css.slice(
      css.indexOf("@media (prefers-color-scheme: light)"),
      css.indexOf("html.theme-light"),
    );
    const themed = css.slice(css.indexOf("html.theme-light"), css.indexOf(":root:not(.dark)"));
    for (const token of [
      "--color-warning",
      "--color-bullish-text",
      "--color-bearish-text",
      "--color-itm-text",
      "--color-otm-text",
      "--color-neutral-text",
      "--color-info",
    ]) {
      const mediaInk = declared(media, token);
      const themedInk = declared(themed, token);
      expect(mediaInk).toBe(themedInk);
      for (const surface of LIGHT_SURFACES) {
        expect(contrastRatio(mediaInk, surface)).toBeGreaterThanOrEqual(AA);
      }
    }
  });
});
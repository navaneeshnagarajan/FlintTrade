import { beforeEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { CINEMATIC_THEMES } from "@/lib/cinematicThemes";
import { useThemeStore } from "../themeStore";

const token = (name: string) => document.documentElement.style.getPropertyValue(`--color-${name}`);
const luminance = (hex: string) => {
  expect(hex).toMatch(/^#[0-9a-f]{6}$/i);
  return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(n => n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4)
    .reduce((sum, n, i) => sum + n * [0.2126, 0.7152, 0.0722][i], 0);
};
const contrast = (a: string, b: string) => {
  const x = luminance(a), y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};
function expectPalette(role: string) {
  const foreground = token(`${role}-foreground`);
  const normal = token(role === "profit" ? "profit-action" : "confirmation");
  const normalContrast = contrast(foreground, normal);
  expect(normalContrast).toBeGreaterThanOrEqual(4.5);
  for (const state of ["hover", "pressed"]) {
    expect(token(`${role}-${state}`)).not.toBe(normal);
    expect(contrast(foreground, token(`${role}-${state}`))).toBeGreaterThanOrEqual(normalContrast);
  }
}
beforeEach(() => {
  document.documentElement.removeAttribute("style");
  useThemeStore.setState({ activeThemeId: "graphite", mode: "dark", customThemes: [] });
});

describe("opaque action palettes", () => {
  for (const theme of CINEMATIC_THEMES) for (const mode of ["light", "dark"] as const) {
    it(`${theme.id}/${mode} declares a stable profit foreground and bounded action backgrounds`, () => {
      useThemeStore.getState().setTheme(theme.id);
      useThemeStore.getState().setMode(mode);
      expect(token("profit-foreground")).toBe(mode === "light" ? "#ffffff" : "#0a0a0f");
      expect(token("profit-action")).toBe(token("profit"));
      expect(token("confirmation")).toBe(theme[mode].colors.accent);
      expect(token("confirmation-foreground")).toBe(theme[mode].colors.accentText);
      expectPalette("profit");
      expectPalette("confirmation");
    });
    it(`${theme.id}/${mode} falls back for a legacy custom trading definition`, () => {
      const custom = structuredClone(theme);
      custom.id = "custom-legacy";
      // Persisted pre-contract custom themes have no new foreground field.
      Reflect.deleteProperty(custom[mode].trading, "profitForeground");
      useThemeStore.getState().addCustomTheme(custom);
      useThemeStore.getState().setTheme(custom.id);
      useThemeStore.getState().setMode(mode);
      expectPalette("profit");
      expectPalette("confirmation");
    });
  }
  for (const value of ["#ffffff", "transparent", "#123", "rgba(0,0,0,.2)"]) {
    it(`bounds unsafe custom normal pairs (${value}) without changing global accent/profit`, () => {
      const custom = structuredClone(CINEMATIC_THEMES[0]);
      custom.id = "custom-unsafe";
      custom.light.colors.accent = value;
      custom.light.colors.accentText = "#ffffff";
      custom.light.trading.profitText = value;
      useThemeStore.getState().addCustomTheme(custom);
      useThemeStore.getState().setTheme(custom.id);
      useThemeStore.getState().setMode("light");
      expect(token("accent")).toBe(value);
      expect(token("profit")).toBe(value);
      expect(token("profit-action")).toBe("#166534");
      expect(token("confirmation")).toBe("#15803d");
      expectPalette("profit");
      expectPalette("confirmation");
    });
  }
  it("declares both pre-hydration mode fallbacks in the shared token stylesheet", () => {
    const css = readFileSync("../../core/design-system/src/tokens.css", "utf8");
    const dark = css.slice(css.indexOf(":root {"), css.indexOf("@media (max-width"));
    const light = css.slice(css.indexOf("@media (prefers-color-scheme: light)"), css.indexOf("html.theme-light"));
    for (const [source, fg] of [[dark, "#0a0a0f"], [light, "#ffffff"]]) {
      expect(source).toContain(`--color-profit-foreground: ${fg}`);
      expect(source).toContain(`--color-confirmation-foreground: ${fg}`);
      for (const role of ["profit", "confirmation"]) for (const state of ["hover", "pressed"]) {
        expect(source).toContain(`--color-${role}-${state}:`);
      }
    }
  });
});

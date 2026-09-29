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
import { Layout, Model } from "flexlayout-react";
import { createElement } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { rowJson, tabJson, tabsetJson, workspaceJson } from "@/layout/flexLayoutAdapter";
import { CINEMATIC_THEMES } from "../cinematicThemes";
import {
  UNSELECTED_TAB_PRIMARY_WEIGHT,
  elevatedSurfaceColour,
  mixSrgb,
  unselectedTabColour,
} from "../colourMix";
import { contrastRatio } from "../contrastUtils";
import { useThemeStore } from "@/stores/themeStore";

const here = dirname(fileURLToPath(import.meta.url));
const flexLayoutCss = readFileSync(
  join(here, "../../../node_modules/flexlayout-react/style/combined.css"),
  "utf8",
);

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

function splitTopLevel(input: string, separator: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  for (let index = 0; index < input.length; index += 1) {
    const character = input[index];
    if (character === "(") depth += 1;
    else if (character === ")") depth -= 1;
    else if (character === separator && depth === 0) {
      parts.push(input.slice(start, index).trim());
      start = index + 1;
    }
  }
  parts.push(input.slice(start).trim());
  return parts.filter((part) => part.length > 0);
}

function normaliseHex(hex: string): string {
  const digits = hex.slice(1);
  if (digits.length === 3) {
    return `#${digits.split("").map((digit) => digit + digit).join("")}`;
  }
  return `#${digits.toLowerCase()}`;
}

function parseRgb(value: string): string | null {
  const match = value.match(/^rgba?\(\s*([^)]+)\)$/i);
  if (!match?.[1]) return null;
  const parts = match[1].split(/[,\s/]+/).filter((part) => part.length > 0);
  if (parts.length < 3) return null;
  const channel = (raw: string): number => {
    if (raw.endsWith("%")) return Math.round((Number(raw.slice(0, -1)) / 100) * 255);
    return Math.round(Number(raw));
  };
  const alpha = parts[3];
  if (alpha !== undefined && Number(alpha) === 0) return "transparent";
  const hex = (raw: string): string =>
    Math.max(0, Math.min(255, channel(raw))).toString(16).padStart(2, "0");
  return `#${hex(parts[0] ?? "0")}${hex(parts[1] ?? "0")}${hex(parts[2] ?? "0")}`;
}

function declaredCustomProperty(element: Element, name: string): string {
  let cursor: Element | null = element;
  while (cursor) {
    const value = getComputedStyle(cursor).getPropertyValue(name).trim();
    if (value) return value;
    cursor = cursor.parentElement;
  }
  return "";
}

/**
 * jsdom returns the specified value (`var(...)`, `color-mix(...)`) rather
 * than a used colour. Follow that declaration on the element so a shadowed
 * custom property is the colour the tab actually paints.
 */
function resolveCssColour(element: Element, raw: string, seen: Set<string> = new Set()): string {
  const value = raw.trim().replace(/\s+/g, " ");
  if (!value || value === "transparent" || value === "rgba(0, 0, 0, 0)") return "transparent";
  if (value === "gray" || value === "grey") return "#808080";
  if (value.startsWith("#")) return normaliseHex(value);

  const rgb = parseRgb(value);
  if (rgb) return rgb;

  const variable = value.match(/^var\(\s*(--[\w-]+)\s*(?:,\s*([\s\S]+))?\)$/);
  if (variable) {
    const name = variable[1] ?? "";
    const fallback = variable[2]?.trim();
    if (seen.has(name)) {
      return fallback ? resolveCssColour(element, fallback, seen) : "";
    }
    const next = new Set(seen);
    next.add(name);
    const declared = declaredCustomProperty(element, name);
    if (declared) return resolveCssColour(element, declared, next);
    return fallback ? resolveCssColour(element, fallback, next) : "";
  }

  const mix = value.match(/^color-mix\(\s*in srgb\s*,\s*([\s\S]+)\)$/);
  if (mix?.[1]) {
    const parts = splitTopLevel(mix[1], ",");
    const first = parts[0];
    const second = parts[1];
    if (!first || !second || parts.length !== 2) return "";
    const firstWeight = first.match(/^(.*)\s+(\d+(?:\.\d+)?)%$/);
    const colourA = (firstWeight?.[1] ?? first).trim();
    const weight = firstWeight?.[2] ? Number(firstWeight[2]) / 100 : 0.5;
    const colourB = second.replace(/\s+\d+(?:\.\d+)?%$/, "").trim();
    const resolvedA = resolveCssColour(element, colourA, seen);
    const resolvedB = resolveCssColour(element, colourB, seen);
    if (!resolvedA.startsWith("#") || !resolvedB.startsWith("#")) return "";
    return mixSrgb(resolvedA, weight, resolvedB);
  }
  return "";
}

function paintedBackground(element: Element): string {
  let cursor: Element | null = element;
  while (cursor) {
    const resolved = resolveCssColour(cursor, getComputedStyle(cursor).backgroundColor);
    if (resolved && resolved !== "transparent") return resolved;
    cursor = cursor.parentElement;
  }
  return "";
}

function installPanelStyles(): HTMLStyleElement {
  const style = document.createElement("style");
  style.setAttribute("data-testid", "panel-tab-styles");
  style.textContent = `${flexLayoutCss}\n${terminalCss}`;
  document.head.appendChild(style);
  return style;
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
    expect(terminalCss).toMatch(
      /\.flexlayout__theme_dark \.flexlayout__layout\.flexlayout__layout\s*\{[^}]*--flexlayout-color-tab-unselected:\s*color-mix\(/,
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

  it("keeps dark-theme resting Show and Dismiss text at 4.5:1", () => {
    const failures: string[] = [];
    for (const theme of CINEMATIC_THEMES) {
      const ratio = contrastRatio(theme.dark.colors.text, theme.dark.colors.card);
      if (ratio < AA) {
        failures.push(`${theme.id} primary on card ${ratio}:1`);
      }
    }
    expect(failures).toEqual([]);
  });

  it("paints the rendered panel-header tab with the shared mix", () => {
    const style = installPanelStyles();
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    const model = Model.fromJson(workspaceJson(rowJson(100, [
      tabsetJson(100, [
        tabJson("chart", "Chart", { id: "tab-chart" }),
        tabJson("watchlist", "Watchlist", { id: "tab-watch" }),
      ]),
    ])));
    const view = render(createElement(
      "div",
      { className: "flexlayout__theme_dark", style: { position: "relative", width: 800, height: 400 } },
      createElement(Layout, { model, factory: () => createElement("div") }),
    ));
    const tab = view.container.querySelector(".flexlayout__tab_button--unselected");
    expect(tab).not.toBeNull();
    const header = tab as HTMLElement;

    const failures: string[] = [];
    for (const theme of CINEMATIC_THEMES) {
      useThemeStore.setState({ activeThemeId: theme.id, mode: "dark" });
      useThemeStore.getState().applyTheme();
      const foreground = resolveCssColour(header, getComputedStyle(header).color);
      const background = paintedBackground(header);
      const expected = unselectedTabColour(theme.dark.colors.text, theme.dark.colors.textSecondary);
      const ratio = foreground.startsWith("#") && background.startsWith("#")
        ? contrastRatio(foreground, background)
        : 0;
      if (foreground !== expected || ratio < AA) {
        failures.push(
          `${theme.id} painted ${foreground} on ${background} ${ratio}:1, expected ${expected}`,
        );
      }
    }

    view.unmount();
    style.remove();
    expect(failures).toEqual([]);
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

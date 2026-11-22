/**
 * Public-site contrast and touch size, read from the stylesheet.
 * WCAG 2.1 relative luminance. Normal text needs 4.5:1. Touch targets
 * declare a 44px box. Theme-toggle icons stay at their existing size.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(process.cwd(), 'src/app/globals.css'), 'utf8');

const SLOGAN_TOKENS = [
  ['Learn', 'site-slogan-1'],
  ['Invest', 'site-slogan-2'],
  ['Trade', 'site-slogan-3'],
  ['Automate', 'site-slogan-4'],
  ['Analyse', 'site-slogan-5'],
  ['Evolve', 'site-slogan-6'],
] as const;

/** Hue of each light-theme slogan colour before the lightness adjustment. */
const LIGHT_SLOGAN_HUES: Record<string, number> = {
  'site-slogan-1': 221.2,
  'site-slogan-2': 161.38,
  'site-slogan-3': 32.13,
  'site-slogan-4': 346.84,
  'site-slogan-5': 271.48,
  'site-slogan-6': 191.65,
};

function cssBlock(source: string, header: string): string {
  const start = source.indexOf(header);
  expect(start, header).toBeGreaterThan(-1);
  const open = source.indexOf('{', start);
  let depth = 0;
  for (let index = open; index < source.length; index += 1) {
    const char = source[index];
    if (char === '{') depth += 1;
    else if (char === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, index);
    }
  }
  throw new Error(`Unclosed block: ${header}`);
}

function customProperties(block: string): Record<string, string> {
  const props: Record<string, string> = {};
  for (const match of block.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) {
    props[match[1]] = match[2].trim();
  }
  return props;
}

function ruleBodies(source: string, selector: string): string[] {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`(?:^|})\\s*${escaped}\\s*\\{([^}]*)\\}`, 'g');
  return [...source.matchAll(pattern)].map((match) => match[1]);
}

function declaredColor(selector: string): string {
  for (const body of ruleBodies(css, selector)) {
    const match = body.match(/(?:^|;)\s*color:\s*([^;]+)/);
    if (match) return match[1].trim();
  }
  throw new Error(`No colour declared for ${selector}`);
}

function resolveColor(value: string, props: Record<string, string>, seen = new Set<string>()): string {
  const variable = value.match(/var\(\s*--([a-z0-9-]+)\s*\)/);
  if (variable) {
    const name = variable[1];
    if (seen.has(name)) throw new Error(`Colour cycle at --${name}`);
    seen.add(name);
    const next = props[name];
    if (!next) throw new Error(`Missing --${name}`);
    return resolveColor(next, props, seen);
  }
  const hex = value.match(/#[0-9a-fA-F]{6}\b/);
  if (!hex) throw new Error(`Not a 6-digit colour: ${value}`);
  return hex[0].toLowerCase();
}

function hexToRgb(hex: string): [number, number, number] {
  const cleaned = hex.slice(1);
  return [
    Number.parseInt(cleaned.slice(0, 2), 16),
    Number.parseInt(cleaned.slice(2, 4), 16),
    Number.parseInt(cleaned.slice(4, 6), 16),
  ];
}

function linearize(channel: number): number {
  const value = channel / 255;
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(r: number, g: number, b: number): number {
  return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b);
}

/** WCAG 2.1 contrast ratio, unrounded. */
function contrastRatio(foreground: string, background: string): number {
  const [fr, fg, fb] = hexToRgb(foreground);
  const [br, bg, bb] = hexToRgb(background);
  const lighter = Math.max(relativeLuminance(fr, fg, fb), relativeLuminance(br, bg, bb));
  const darker = Math.min(relativeLuminance(fr, fg, fb), relativeLuminance(br, bg, bb));
  return (lighter + 0.05) / (darker + 0.05);
}

function compositeOver(overlay: string, background: string): string {
  const match = overlay.match(/rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)/);
  if (!match) throw new Error(`Expected an rgba panel: ${overlay}`);
  const alpha = Number(match[4]);
  const [br, bg, bb] = hexToRgb(background);
  const channels = [0, 1, 2].map((index) => {
    const top = Number(match[index + 1]);
    return Math.round(top * alpha + [br, bg, bb][index] * (1 - alpha));
  });
  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}

function hue(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((channel) => channel / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  if (delta === 0) return 0;
  let hueValue = 0;
  if (max === r) hueValue = (g - b) / delta + (g < b ? 6 : 0);
  else if (max === g) hueValue = (b - r) / delta + 2;
  else hueValue = (r - g) / delta + 4;
  return (hueValue / 6) * 360;
}

function hueDistance(left: number, right: number): number {
  const distance = Math.abs(left - right) % 360;
  return Math.min(distance, 360 - distance);
}

function pixel(body: string, property: string): number | null {
  const match = body.match(new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*(\\d+(?:\\.\\d+)?)px`));
  return match ? Number(match[1]) : null;
}

function assertFloor(selector: string, axis: 'height' | 'width'): void {
  const bodies = ruleBodies(css, selector);
  expect(bodies.length, selector).toBeGreaterThan(0);
  const minimum = axis === 'height' ? 'min-height' : 'min-width';
  const floors = bodies.map((body) => Math.max(pixel(body, axis) ?? 0, pixel(body, minimum) ?? 0));
  expect(Math.max(...floors), `${selector} ${axis}`).toBeGreaterThanOrEqual(44);
  for (const body of bodies) {
    for (const property of [axis, minimum]) {
      const value = pixel(body, property);
      if (value != null) {
        expect(value, `${selector} ${property}`).toBeGreaterThanOrEqual(44);
      }
    }
  }
}

function themeProps(theme: 'light' | 'dark'): Record<string, string> {
  const light = customProperties(cssBlock(css, ':root {'));
  if (theme === 'light') return light;
  return { ...light, ...customProperties(cssBlock(css, 'html.dark {')) };
}

describe('site colour contrast from the stylesheet', () => {
  const themes = ['light', 'dark'] as const;

  it('holds every slogan word and the separator at 4.5:1 on the page background', () => {
    for (const theme of themes) {
      const props = themeProps(theme);
      const background = resolveColor(props['site-background'], props);
      for (const [word, token] of SLOGAN_TOKENS) {
        const colour = resolveColor(props[token], props);
        const ratio = contrastRatio(colour, background);
        expect(ratio, `${theme} ${word} ${colour} on ${background}`).toBeGreaterThanOrEqual(4.5);
      }
      const dot = resolveColor(declaredColor('.hero-slogan .slogan-dot'), props);
      const dotRatio = contrastRatio(dot, background);
      expect(dotRatio, `${theme} separator ${dot} on ${background}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('keeps the light slogan hues while the lightness changes', () => {
    const props = themeProps('light');
    for (const [, token] of SLOGAN_TOKENS) {
      const colour = resolveColor(props[token], props);
      expect(hueDistance(hue(colour), LIGHT_SLOGAN_HUES[token]), token).toBeLessThanOrEqual(1);
    }
  });

  it('holds muted text at 4.5:1 on the page, panel, card, and elevated surface', () => {
    for (const theme of themes) {
      const props = themeProps(theme);
      const muted = resolveColor(props['site-muted'], props);
      const background = resolveColor(props['site-background'], props);
      const surfaces = [
        ['page', background],
        ['panel', compositeOver(props['site-panel'], background)],
        ['card', resolveColor(props['site-surface-card'], props)],
        ['elevated', resolveColor(props['site-surface-elevated'], props)],
      ] as const;
      for (const [name, surface] of surfaces) {
        const ratio = contrastRatio(muted, surface);
        expect(ratio, `${theme} muted ${muted} on ${name} ${surface}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('holds package names and install labels at 4.5:1 on the panel', () => {
    for (const theme of themes) {
      const props = themeProps(theme);
      const background = resolveColor(props['site-background'], props);
      const panel = compositeOver(props['site-panel'], background);
      for (const selector of ['.package-row strong', '.install-card span']) {
        const colour = resolveColor(declaredColor(selector), props);
        const ratio = contrastRatio(colour, panel);
        expect(ratio, `${theme} ${selector} ${colour} on ${panel}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});

describe('site touch targets from the stylesheet', () => {
  it('gives the GitHub link a 44px box, including the narrow header', () => {
    assertFloor('.github-link', 'width');
    assertFloor('.github-link', 'height');
  });

  it('gives primary nav links a 44px box and inline-flex alignment', () => {
    assertFloor('.main-nav a', 'width');
    assertFloor('.main-nav a', 'height');
    expect(ruleBodies(css, '.main-nav a').join('\n')).toMatch(/display:\s*inline-flex/);
  });

  it('gives the desktop guide and footer links a 44px box', () => {
    for (const selector of ['.hero-electron-note a', '.site-footer a']) {
      assertFloor(selector, 'width');
      assertFloor(selector, 'height');
      expect(ruleBodies(css, selector).join('\n'), selector).toMatch(/display:\s*inline-flex/);
    }
  });

  it('gives the theme toggle a 44px box and keeps the icon centred', () => {
    const button = ruleBodies(css, '.theme-toggle button').join('\n');
    const icon = ruleBodies(css, '.theme-toggle svg').join('\n');

    expect(pixel(button, 'width')).toBe(44);
    expect(pixel(button, 'height')).toBe(44);
    expect(pixel(button, 'min-width')).toBeGreaterThanOrEqual(44);
    expect(pixel(button, 'min-height')).toBeGreaterThanOrEqual(44);
    expect(button).toMatch(/place-items:\s*center/);
    expect(pixel(icon, 'width')).toBe(14);
    expect(pixel(icon, 'height')).toBe(14);
  });

  it('gives the brand link a 44px box with centred contents', () => {
    const link = ruleBodies(css, '.brand-link').join('\n');

    expect(pixel(link, 'min-width')).toBeGreaterThanOrEqual(44);
    expect(pixel(link, 'min-height')).toBeGreaterThanOrEqual(44);
    expect(link).toMatch(/align-items:\s*center/);
    expect(link).toMatch(/justify-content:\s*center/);
    for (const body of ruleBodies(css, '.brand-link')) {
      for (const property of ['width', 'min-width', 'height', 'min-height']) {
        const value = pixel(body, property);
        if (value != null) expect(value, property).toBeGreaterThanOrEqual(44);
      }
    }
  });

  it('gives product links a 44px hit area', () => {
    const links = ruleBodies(css, '.product-links a').join('\n');

    expect(links).toMatch(/display:\s*inline-flex/);
    expect(links).toMatch(/align-items:\s*center/);
    assertFloor('.product-links a', 'width');
    assertFloor('.product-links a', 'height');
  });

  it('gives the download release-history link a 44px hit area', () => {
    const links = ruleBodies(css, '.subpage p a').join('\n');

    expect(links).toMatch(/display:\s*inline-flex/);
    expect(links).toMatch(/align-items:\s*center/);
    assertFloor('.subpage p a', 'width');
    assertFloor('.subpage p a', 'height');
  });
});

/**
 * Seasonality heat-strip colours.
 *
 * Tiles are opaque, so a tile's colour, and therefore the contrast of the
 * text on it, does not depend on which theme surface sits behind it. The
 * fills are also bounded: the heat-strip component draws each tile's label
 * and detail line in white, so every fill must stay dark enough for white
 * text (WCAG AA, 4.5:1) in dark and light themes alike.
 */

type Rgb = readonly [number, number, number];

const WEAK: Rgb = [39, 39, 42];
const STRONG_GAIN: Rgb = [21, 128, 61];
const STRONG_LOSS: Rgb = [185, 28, 28];
const NEUTRAL: Rgb = [63, 63, 70];

const LIGHT_TEXT = "#ffffff";
const DARK_TEXT = "#0a0a0f";

/** Share of the strong colour a just-above-zero return starts at. */
const MIN_STRENGTH = 0.3;

function toCss([r, g, b]: Rgb): string {
  return `rgb(${r}, ${g}, ${b})`;
}

function mix(from: Rgb, to: Rgb, share: number): Rgb {
  return [
    Math.round(from[0] + (to[0] - from[0]) * share),
    Math.round(from[1] + (to[1] - from[1]) * share),
    Math.round(from[2] + (to[2] - from[2]) * share),
  ];
}

/** Parses `#rrggbb` or `rgb(r, g, b)`; anything else is null. */
function parseColour(colour: string): Rgb | null {
  const hex = /^#([0-9a-f]{6})$/i.exec(colour.trim());
  if (hex) {
    const value = Number.parseInt(hex[1], 16);
    return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
  }
  const rgb = /^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/i.exec(colour.trim());
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  return null;
}

function relativeLuminance([r, g, b]: Rgb): number {
  const channel = (value: number): number => {
    const srgb = value / 255;
    return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/**
 * WCAG contrast ratio between two opaque colours (`#rrggbb` or `rgb()`).
 * Returns null when either colour cannot be parsed.
 */
export function contrastRatio(a: string, b: string): number | null {
  const first = parseColour(a);
  const second = parseColour(b);
  if (!first || !second) return null;
  const [lighter, darker] = [relativeLuminance(first), relativeLuminance(second)].sort((x, y) => y - x);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Return-heat tile colour: green for positive months/days, red for negative,
 * neutral grey near zero; the colour deepens with magnitude within the view.
 */
export function heatColour(value: number, maxAbs: number): string {
  if (!Number.isFinite(value) || maxAbs <= 0 || Math.abs(value) < 1e-9) {
    return toCss(NEUTRAL);
  }
  const strength = MIN_STRENGTH + (1 - MIN_STRENGTH) * Math.min(Math.abs(value) / maxAbs, 1);
  return toCss(mix(WEAK, value > 0 ? STRONG_GAIN : STRONG_LOSS, strength));
}

/** Text colour for a heat tile: whichever of white or near-black reads better on the fill. */
export function heatTextColour(fill: string): string {
  const onLight = contrastRatio(fill, LIGHT_TEXT);
  const onDark = contrastRatio(fill, DARK_TEXT);
  if (onLight === null || onDark === null) return LIGHT_TEXT;
  return onLight >= onDark ? LIGHT_TEXT : DARK_TEXT;
}

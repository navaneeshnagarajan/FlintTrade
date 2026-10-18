/**
 * colourMix.ts
 *
 * Shared sRGB mixes for theme surfaces the stylesheet and the contrast
 * tests both have to resolve. CSS `color-mix(in srgb, …)` interpolates in
 * gamma-encoded sRGB; the painted pixel is the channel rounded to 8-bit.
 */

import { hexToRgb, relativeLuminance } from "./contrastUtils";

/**
 * Share of primary text in the dark unselected-tab mix.
 * Matches `--fl-color-tab-unselected` in terminal.css:
 * `color-mix(in srgb, var(--color-text-primary) 62%, var(--color-text-secondary))`.
 */
export const UNSELECTED_TAB_PRIMARY_WEIGHT = 0.62;

/**
 * Channel lift themeStore applies when it derives `--color-surface-elevated`
 * from the card. The tray bar is this fill; it is lighter than the card,
 * so it is the stricter background for light tab text.
 */
export const ELEVATED_CHANNEL_BUMP = 12;

/**
 * CSS `color-mix(in srgb, colorA <weight>, colorB)`.
 *
 * `weight` is colorA's share in the range 0–1. The omitted percentage is
 * the remainder, the same normalisation CSS uses when only one percentage
 * is written. Channels are rounded to 8-bit.
 */
export function mixSrgb(colorA: string, weight: number, colorB: string): string {
  const share = Math.min(1, Math.max(0, weight));
  const [ar, ag, ab] = hexToRgb(colorA);
  const [br, bg, bb] = hexToRgb(colorB);
  const channel = (a: number, b: number): string =>
    Math.round(a * share + b * (1 - share)).toString(16).padStart(2, "0");
  return `#${channel(ar, br)}${channel(ag, bg)}${channel(ab, bb)}`;
}

/** Dark unselected tray and panel tab text. */
export function unselectedTabColour(primary: string, secondary: string): string {
  return mixSrgb(primary, UNSELECTED_TAB_PRIMARY_WEIGHT, secondary);
}

/** Venue-chip ink on a dark ticker. #f4f4f8 on #0a0a0f is above 4.5:1. */
export const TICKER_VENUE_ON_DARK = "#f4f4f8";

/** Venue-chip ink on a light ticker. #1a1a1e on #f5f5f7 is above 4.5:1. */
export const TICKER_VENUE_ON_LIGHT = "#1a1a1e";

/** Practice chip ink on the dark amber wash. Amber-400, #ffb900. */
export const PRACTICE_CHIP_ON_DARK = "#ffb900";

/**
 * Practice chip ink on the light amber wash.
 * #6b4500 on #feefd9 is about 7.5:1, and it stays above 4.5:1 on the
 * 15% and 25% amber washes. Dark chrome keeps #ffb900.
 */
export const PRACTICE_CHIP_ON_LIGHT = "#6b4500";

/** Tailwind amber-500. The Practice chip washes the chrome with this at 15% and 25%. */
export const PRACTICE_CHIP_WASH = "#fe9a00";

/**
 * Chip colour for NSE/MCX venue labels.
 *
 * Chosen against the theme surface, not the disabled or warning tokens.
 * Those fail 4.5:1 on Graphite in both themes.
 */
export function tickerVenueColour(background: string): string {
  const [red, green, blue] = hexToRgb(background);
  return relativeLuminance(red, green, blue) > 0.4
    ? TICKER_VENUE_ON_LIGHT
    : TICKER_VENUE_ON_DARK;
}

/** Practice chip ink. Light chrome needs the dark amber; dark chrome keeps amber-400. */
export function practiceChipColour(background: string): string {
  const [red, green, blue] = hexToRgb(background);
  return relativeLuminance(red, green, blue) > 0.4
    ? PRACTICE_CHIP_ON_LIGHT
    : PRACTICE_CHIP_ON_DARK;
}

/** Live chip ink on dark chrome. Matches dark profit text, #22c55e. */
export const LIVE_CHIP_ON_DARK = "#22c55e";

/**
 * Live chip ink on the light profit wash.
 * #0f5c2c on the 20% #166534 wash is about 5.9:1. Dark chrome keeps #22c55e.
 */
export const LIVE_CHIP_ON_LIGHT = "#0f5c2c";

/** Live chip ink. Light chrome uses the darker green; dark chrome keeps profit green. */
export function liveChipColour(background: string): string {
  const [red, green, blue] = hexToRgb(background);
  return relativeLuminance(red, green, blue) > 0.4
    ? LIVE_CHIP_ON_LIGHT
    : LIVE_CHIP_ON_DARK;
}

/** Elevated tray fill derived from the card surface. */
export function elevatedSurfaceColour(card: string): string {
  const [r, g, b] = hexToRgb(card);
  const channel = (value: number): string =>
    Math.min(255, value + ELEVATED_CHANNEL_BUMP).toString(16).padStart(2, "0");
  return `#${channel(r)}${channel(g)}${channel(b)}`;
}

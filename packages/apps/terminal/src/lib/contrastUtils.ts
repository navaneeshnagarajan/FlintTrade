/**
 * contrastUtils.ts
 *
 * WCAG 2.1 contrast ratio utilities.
 *
 * Implements the W3C relative luminance formula and 4.5:1 AA threshold check.
 * All functions are pure and synchronous — safe for use in render loops.
 *
 * References:
 *   https://www.w3.org/TR/WCAG21/#contrast-minimum
 *   https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
 */

// ---------------------------------------------------------------------------
// Hex → RGB
// ---------------------------------------------------------------------------

/**
 * Convert a 6-digit hex color string (with or without leading "#") to an
 * [r, g, b] tuple in the 0–255 range.
 *
 * Returns [0, 0, 0] for any input that is not a valid 6-digit hex color.
 */
export function hexToRgb(hex: string): [number, number, number] {
  const cleaned = hex.startsWith("#") ? hex.slice(1) : hex;
  if (cleaned.length !== 6 || !/^[0-9a-fA-F]{6}$/.test(cleaned)) {
    return [0, 0, 0];
  }
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  return [r, g, b];
}

// ---------------------------------------------------------------------------
// Relative luminance
// ---------------------------------------------------------------------------

/**
 * Linearize a single 8-bit channel value (0–255) per the WCAG 2.1 formula.
 * Applies the sRGB gamma inverse.
 */
function linearize(channel: number): number {
  const s = channel / 255;
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

/**
 * Compute the WCAG 2.1 relative luminance of an sRGB color.
 *
 * @param r - Red channel, 0–255
 * @param g - Green channel, 0–255
 * @param b - Blue channel, 0–255
 * @returns Luminance value in the range [0, 1] where 0 is black and 1 is white
 */
export function relativeLuminance(r: number, g: number, b: number): number {
  return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b);
}

// ---------------------------------------------------------------------------
// Contrast ratio
// ---------------------------------------------------------------------------

/**
 * Compute the WCAG 2.1 contrast ratio between two hex colors.
 *
 * The ratio is always >= 1. A ratio of 21 is black-on-white (maximum).
 * Returns 1 if either color is invalid.
 *
 * @param fg - Foreground hex color (e.g. "#22c55e")
 * @param bg - Background hex color (e.g. "#0a0a0f")
 * @returns Contrast ratio rounded to two decimal places
 */
export function contrastRatio(fg: string, bg: string): number {
  const [fr, fg_, fb] = hexToRgb(fg);
  const [br, bg_, bb] = hexToRgb(bg);

  const L1 = relativeLuminance(fr, fg_, fb);
  const L2 = relativeLuminance(br, bg_, bb);

  const lighter = Math.max(L1, L2);
  const darker  = Math.min(L1, L2);

  const ratio = (lighter + 0.05) / (darker + 0.05);
  return Math.round(ratio * 100) / 100;
}

// ---------------------------------------------------------------------------
// WCAG AA check
// ---------------------------------------------------------------------------

/**
 * Returns true if the foreground/background color pair meets WCAG 2.1 AA.
 *
 * - Normal text: contrast ratio >= 4.5
 * - Large text (>= 18pt or >= 14pt bold): contrast ratio >= 3.0
 *
 * @param fg        - Foreground hex color
 * @param bg        - Background hex color
 * @param largeText - When true, uses the 3.0 threshold for large text
 */
export function meetsWcagAA(fg: string, bg: string, largeText = false): boolean {
  return contrastRatio(fg, bg) >= (largeText ? 3.0 : 4.5);
}

// ---------------------------------------------------------------------------
// Result type
// ---------------------------------------------------------------------------

export interface ContrastResult {
  ratio: number;
  passes: boolean;
  label: string;
}

/**
 * Evaluate a foreground/background pair and return a structured result with
 * the computed ratio, pass/fail boolean, and a human-readable label.
 *
 * @param fg        - Foreground hex color
 * @param bg        - Background hex color
 * @param largeText - When true, uses the 3.0 (AA large) threshold
 */
export function evaluateContrast(
  fg: string,
  bg: string,
  largeText = false,
): ContrastResult {
  const ratio = contrastRatio(fg, bg);
  const threshold = largeText ? 3.0 : 4.5;
  const passes = ratio >= threshold;

  let label: string;
  if (ratio >= 7.0) {
    label = "AAA";
  } else if (ratio >= 4.5) {
    label = "AA";
  } else if (ratio >= 3.0) {
    label = "AA Large";
  } else {
    label = "Fail";
  }

  return { ratio, passes, label };
}

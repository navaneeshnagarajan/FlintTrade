/** Opaque action colours: never fade the label or its backing surface.
 * Legacy/invalid custom pairs fall back locally, not by rewriting brand/trading
 * colours. State backgrounds move monotonically away from the stable foreground
 * in sRGB, preserving the normal contrast bound at the generated endpoints.
 */
export interface ActionPalette {
  background: string;
  foreground: string;
  hover: string;
  pressed: string;
}

const opaqueHex = /^#[\da-f]{6}$/i;
const channels = (hex: string) => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
function luminance(hex: string): number {
  return channels(hex).map(n => n / 255)
    .map(n => n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4)
    .reduce((sum, n, i) => sum + n * [0.2126, 0.7152, 0.0722][i], 0);
}
function contrast(background: string, foreground: string): number {
  const a = luminance(background), b = luminance(foreground);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

export function resolveActionPalette(
  background: string,
  foreground: string | undefined,
  fallback: { background: string; foreground: string },
): ActionPalette {
  if (!foreground || !opaqueHex.test(background) || !opaqueHex.test(foreground)
    || contrast(background, foreground) < 4.5) {
    ({ background, foreground } = fallback);
  }
  const stableForeground = foreground;
  const brighter = luminance(background) > luminance(stableForeground);
  const endpoint = channels(brighter ? "#ffffff" : "#0a0a0f");
  const mix = (amount: number) => "#" + channels(background).map((n, i) => {
    // Custom backgrounds darker than the existing near-black endpoint must
    // not get lighter. Each channel therefore moves only in the safe direction.
    const target = brighter ? endpoint[i] : Math.min(n, endpoint[i]);
    return Math.round(n + (target - n) * amount).toString(16).padStart(2, "0");
  }).join("");
  return { background, foreground: stableForeground, hover: mix(0.1), pressed: mix(0.2) };
}

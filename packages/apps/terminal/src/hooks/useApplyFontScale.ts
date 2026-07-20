/**
 * useApplyFontScale — mirrors the persisted font-size preference onto the
 * document root so the design-system typography tokens can consume it.
 *
 * Settings → General → Font Size is stored in settingsStore (`fontSize`).
 * This hook writes it to a `data-font-scale` attribute on `<html>`; the
 * design-system resolves that attribute into the `--ft-font-scale` multiplier
 * (packages/core/design-system/src/tokens.css), which scales the data-table
 * and number-display typography (`--data-cell`, `--data-primary`,
 * `--data-hero`, `text-xxs`/`text-xs`/`text-sm`/`text-base`) across widgets
 * such as Positions, Orders, Option Chain and Watchlist.
 *
 * Mounted once in RootLayout so the persisted scale applies at boot and
 * re-applies whenever the setting changes.
 */

import { useEffect } from "react";
import { useSettingsStore } from "@/stores/settingsStore";

export type FontScaleSetting = "small" | "normal" | "large";

/** Root attribute the design-system CSS keys its font-scale overrides on. */
export const FONT_SCALE_ATTRIBUTE = "data-font-scale";

/** Write the font-scale setting to the document root. */
export function applyFontScale(fontSize: FontScaleSetting): void {
  document.documentElement.setAttribute(FONT_SCALE_ATTRIBUTE, fontSize);
}

/** Apply the persisted font scale at mount and on every settings change. */
export function useApplyFontScale(): void {
  const fontSize = useSettingsStore((s) => s.fontSize);

  useEffect(() => {
    applyFontScale(fontSize);
  }, [fontSize]);
}

/**
 * Mirror Compact / Comfortable onto <html> so token CSS and data-density
 * consumers stay in sync (FT-UX-001).
 */

import type { UiDensity } from "@/lib/tradeDeskDensity";

export const DENSITY_ATTRIBUTE = "data-density";

const DENSITY_CLASSES = ["density-compact", "density-comfortable"] as const;

export function applyDensityToDocument(density: UiDensity): void {
  const root = document.documentElement;
  root.setAttribute(DENSITY_ATTRIBUTE, density);
  root.classList.remove(...DENSITY_CLASSES);
  root.classList.add(`density-${density}`);
}

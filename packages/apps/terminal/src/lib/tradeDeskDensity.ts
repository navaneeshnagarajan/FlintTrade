/**
 * FT-UX-001 — Compact / Comfortable Trade desk disclosure.
 *
 * Comfortable is the new-install default (full labels). Compact on a desk
 * viewport (≥1280) collapses ticker, dock labels, and watchlist/advanced
 * tools behind one toggle so chart + order pad + positions stay primary.
 * Phone layouts (<768) are out of scope.
 */

export type UiDensity = "compact" | "comfortable";

/** Desk-first floor from the FT-UX-001 verify scenario (1280×800). */
export const DESK_MIN_WIDTH = 1280;

/** Tight Compact band called out in the acceptance checklist. */
export const DESK_COMPACT_FOCUS_MAX_WIDTH = 1600;

export const COMPACT_DESK_PRIMARY_WIDGETS = ["chart", "orderpad", "positions"] as const;
export const COMPACT_DESK_COLLAPSED_WIDGETS = [
  "watchlist",
  "orderladder",
  "ticker",
  "indexstrip",
] as const;

export const COMPACT_DESK_PRESET_ID = "compact-desk";

/** Compact progressive disclosure on desk Trade (normal + widescreen). */
export function usesCompactProgressiveDisclosure(
  density: UiDensity,
  viewportWidth: number,
): boolean {
  return density === "compact" && viewportWidth >= DESK_MIN_WIDTH;
}

export function defaultTradePresetId(
  level: "beginner" | "intermediate" | "advanced",
  density: UiDensity,
  viewportWidth: number,
  deskToolsExpanded = false,
): string {
  if (usesCompactProgressiveDisclosure(density, viewportWidth) && !deskToolsExpanded) {
    return COMPACT_DESK_PRESET_ID;
  }
  if (level === "advanced") return "scalper-zone";
  if (level === "intermediate") return "market-watch";
  return "beginner-core";
}

export type SidebarDisplayMode = "icons" | "expanded" | "auto-hide" | "hidden";

/** Compact desk forces icon rail; Comfortable desk restores full labels. */
export function resolveDockMode(
  density: UiDensity,
  stored: SidebarDisplayMode,
  viewportWidth: number,
): SidebarDisplayMode {
  if (stored === "hidden" || stored === "auto-hide") return stored;
  if (usesCompactProgressiveDisclosure(density, viewportWidth)) return "icons";
  if (density === "comfortable" && viewportWidth >= DESK_MIN_WIDTH) return "expanded";
  return stored;
}

export function showTickerChrome(
  density: UiDensity,
  viewportWidth: number,
  deskToolsExpanded = false,
): boolean {
  if (usesCompactProgressiveDisclosure(density, viewportWidth) && !deskToolsExpanded) {
    return false;
  }
  return true;
}

export function showFullToolRibbon(
  density: UiDensity,
  viewportWidth: number,
  deskToolsExpanded = false,
): boolean {
  if (usesCompactProgressiveDisclosure(density, viewportWidth) && !deskToolsExpanded) {
    return false;
  }
  return true;
}

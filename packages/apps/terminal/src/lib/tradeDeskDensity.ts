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

/** Trade route only — Compact chrome must not collapse Home / Invest / Settings. */
export function isTradePath(pathname: string): boolean {
  return pathname === "/trade" || pathname.startsWith("/trade/");
}

/** Compact progressive disclosure on desk Trade (normal + widescreen). */
export function usesCompactProgressiveDisclosure(
  density: UiDensity,
  viewportWidth: number,
  onTrade = true,
): boolean {
  return onTrade && density === "compact" && viewportWidth >= DESK_MIN_WIDTH;
}

export function defaultTradePresetId(
  level: "beginner" | "intermediate" | "advanced",
  density: UiDensity,
  viewportWidth: number,
  deskToolsExpanded = false,
  onTrade = true,
): string {
  if (usesCompactProgressiveDisclosure(density, viewportWidth, onTrade) && !deskToolsExpanded) {
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
  onTrade = true,
): SidebarDisplayMode {
  if (stored === "hidden" || stored === "auto-hide") return stored;
  if (usesCompactProgressiveDisclosure(density, viewportWidth, onTrade)) return "icons";
  if (density === "comfortable" && viewportWidth >= DESK_MIN_WIDTH) return "expanded";
  return stored;
}

export function showTickerChrome(
  density: UiDensity,
  viewportWidth: number,
  deskToolsExpanded = false,
  onTrade = true,
): boolean {
  if (usesCompactProgressiveDisclosure(density, viewportWidth, onTrade) && !deskToolsExpanded) {
    return false;
  }
  return true;
}

export function showFullToolRibbon(
  density: UiDensity,
  viewportWidth: number,
  deskToolsExpanded = false,
  onTrade = true,
): boolean {
  if (usesCompactProgressiveDisclosure(density, viewportWidth, onTrade) && !deskToolsExpanded) {
    return false;
  }
  return true;
}

const PRIMARY_WIDGETS = new Set<string>(COMPACT_DESK_PRIMARY_WIDGETS);
const DESK_TOOL_WIDGETS = new Set<string>(COMPACT_DESK_COLLAPSED_WIDGETS);

/** Collect FlexLayout tab `component` ids from a workspace JSON document. */
export function collectWorkspaceComponents(json: Record<string, unknown> | null | undefined): string[] {
  const components: string[] = [];
  const visit = (node: unknown): void => {
    if (!node || typeof node !== "object") return;
    const record = node as Record<string, unknown>;
    if (typeof record.component === "string") components.push(record.component);
    if (record.layout) visit(record.layout);
    if (Array.isArray(record.children)) {
      for (const child of record.children) visit(child);
    }
  };
  visit(json ?? {});
  return components;
}

export interface CompactDeskToolsApi<TLayout = Record<string, unknown>> {
  addPanel: (options: { component: string; title: string }) => void;
  toJSON: () => Record<string, unknown>;
  loadModelJson: (json: TLayout) => void;
}

function workspaceExtras(components: Iterable<string>): string[] {
  return [...components].filter((id) => !PRIMARY_WIDGETS.has(id) && !DESK_TOOL_WIDGETS.has(id));
}

function hasCollapsibleDeskTools(components: Iterable<string>): boolean {
  return [...components].some((id) => DESK_TOOL_WIDGETS.has(id));
}

/**
 * Reveal or hide watchlist / indices / ticker / ladder on a stock Compact desk.
 *
 * Expand adds Watchlist when the canvas does not already have one. Collapse
 * restores `compact-desk` when the only extras are desk tools (watchlist,
 * indices strip, ticker, ladder) so a customised desk (news, scalper, …)
 * is not wiped.
 */
export function applyCompactDeskToolsDisclosure<TLayout>(
  api: CompactDeskToolsApi<TLayout>,
  expanded: boolean,
  loadCompactDesk: () => TLayout,
): void {
  const components = new Set(collectWorkspaceComponents(api.toJSON()));
  if (expanded) {
    if (!components.has("watchlist")) {
      api.addPanel({ component: "watchlist", title: "Watchlist" });
    }
    return;
  }
  if (workspaceExtras(components).length === 0 && hasCollapsibleDeskTools(components)) {
    api.loadModelJson(loadCompactDesk());
  }
}

/**
 * Comfortable returns the skill-level default when the canvas is still a
 * stock desk (primary widgets and/or collapsible desk tools only).
 */
export function restoreComfortableDeskLayout<TLayout>(
  api: CompactDeskToolsApi<TLayout>,
  loadSkillDefault: () => TLayout,
): void {
  const components = collectWorkspaceComponents(api.toJSON());
  if (workspaceExtras(components).length > 0) return;
  api.loadModelJson(loadSkillDefault());
}

export interface DeskDensitySelectionOptions<TLayout = Record<string, unknown>> {
  viewportWidth: number;
  onTrade: boolean;
  layout: CompactDeskToolsApi<TLayout> | null | undefined;
  loadCompactDesk: () => TLayout;
  loadComfortableDesk: () => TLayout;
  setToolsExpanded: (expanded: boolean) => void;
}

/**
 * Apply Compact / Comfortable canvas disclosure.
 *
 * Compact always starts collapsed (tools toggle off) on a desk Trade
 * viewport. Comfortable restores the skill-level layout when safe.
 */
export function applyDeskDensitySelection<TLayout>(
  density: UiDensity,
  options: DeskDensitySelectionOptions<TLayout>,
): void {
  if (density === "compact") {
    options.setToolsExpanded(false);
    if (
      options.layout
      && usesCompactProgressiveDisclosure(density, options.viewportWidth, options.onTrade)
    ) {
      applyCompactDeskToolsDisclosure(options.layout, false, options.loadCompactDesk);
    }
    return;
  }
  if (options.layout) {
    restoreComfortableDeskLayout(options.layout, options.loadComfortableDesk);
  }
}

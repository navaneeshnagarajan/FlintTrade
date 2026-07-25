/**
 * useSkillContent — returns skill-level-appropriate UI content for the current
 * "trade" domain.
 *
 * Consumers:
 *   - TerminalRoute  — filters WidgetPicker and ToolsDropdown
 *   - TopBar         — drives SkillBadge tooltip level
 *
 * Design rule: content is *additive* — higher levels include everything from
 * lower levels plus more. Never hide a previously visible widget on upgrade.
 */

import { useMemo } from "react";
import { useSkillLevel } from "./useSkillLevel";
import { widgetCatalog } from "@/layout/widgetFactory";
import type { SkillLevel } from "@/types/skill";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TooltipLevel = "simple" | "detailed" | "expert";

export interface SkillContent {
  /** Widget IDs shown in the widget picker for this skill level. */
  availableWidgets: string[];
  /** Tool IDs shown in the tools dropdown for this skill level. */
  availableTools: string[];
  /** Whether to render advanced feature sections (walk-forward, Monte Carlo, RAG). */
  showAdvanced: boolean;
  /** Complexity level for tooltips and inline hints. */
  tooltipLevel: TooltipLevel;
  /** Default workspace preset applied on first visit. */
  defaultPreset: string;
}

// ---------------------------------------------------------------------------
// Static maps — defined outside the hook so they are never re-created
// ---------------------------------------------------------------------------

/**
 * Beginner — 7 core widgets: the minimum viable trading workspace.
 * Matches the 5-widget applyBeginnerLayout() in TerminalRoute plus
 * two extras (orders, holdings) to keep the picker useful.
 */
const BEGINNER_WIDGETS: string[] = [
  "indexstrip",
  "chart",
  "watchlist",
  "orderpad",
  "positions",
  "orders",
  "holdings",
];

/**
 * Intermediate — adds the main analysis suite on top of core.
 */
const INTERMEDIATE_WIDGETS: string[] = [
  ...BEGINNER_WIDGETS,
  "optionchain",
  "straddle",
  // Merged canonicals. `depth` folded into `orderladder` and `gex` into
  // `gammadensity`; because this list is by id and the retired ids leave the
  // catalogue, leaving them here silently removed BOTH surfaces from the
  // intermediate picker — the retired ids no longer resolve into it and the
  // survivors were never added.
  "orderladder",
  "greeks",
  "oichart",
  "marketoverview",
  "gammadensity",
  "news",
  "calculator",
  "ticker",
  "pnlmonitor",
];

/**
 * Widgets deliberately kept OUT of the Add Widget picker. Empty today — every
 * catalogued widget is functional and honest (renders real data, or carries a
 * permanent "Sample data" disclosure for explore-mode sample content). Add an
 * id here, with a reason, to hide a widget without removing it from the catalog.
 */
const WIDGET_PICKER_DENY_LIST = new Set<string>([]);

/**
 * Advanced — EVERY registered widget, sourced directly from ``widgetCatalog``
 * (minus the deny-list) so the advanced picker can never silently drift behind
 * newly-added widgets. This honours the original "all registered widgets" intent
 * without a hand-maintained list that falls out of date (the bug that left ~50
 * built widgets unreachable). New catalogue widgets are reachable by default;
 * exclude one explicitly via WIDGET_PICKER_DENY_LIST.
 */
const ADVANCED_WIDGETS: string[] = Array.from(
  new Set([
    ...INTERMEDIATE_WIDGETS,
    ...widgetCatalog.map((w) => w.id).filter((id) => !WIDGET_PICKER_DENY_LIST.has(id)),
  ]),
);

/** Tools available per skill level on the /trade route. */
const BEGINNER_TOOLS: string[] = ["settings"];
const INTERMEDIATE_TOOLS: string[] = ["trade-journal", "settings"];
const ADVANCED_TOOLS: string[] = [
  "market-intelligence",
  "trade-journal",
  "settings",
];

const WIDGET_MAP: Record<SkillLevel, string[]> = {
  beginner: BEGINNER_WIDGETS,
  intermediate: INTERMEDIATE_WIDGETS,
  advanced: ADVANCED_WIDGETS,
};

const TOOL_MAP: Record<SkillLevel, string[]> = {
  beginner: BEGINNER_TOOLS,
  intermediate: INTERMEDIATE_TOOLS,
  advanced: ADVANCED_TOOLS,
};

const TOOLTIP_MAP: Record<SkillLevel, TooltipLevel> = {
  beginner: "simple",
  intermediate: "detailed",
  advanced: "expert",
};

const PRESET_MAP: Record<SkillLevel, string> = {
  beginner: "beginner-core",
  intermediate: "market-watch",
  advanced: "scalper-zone",
};

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Returns skill-level-appropriate content for the trade domain.
 *
 * Uses the effective level for "trade" (respects per-domain overrides).
 * All returned values are stable references — safe to pass as props without
 * triggering unnecessary child re-renders.
 */
export function useSkillContent(): SkillContent {
  const level = useSkillLevel("trade");

  return useMemo<SkillContent>(
    () => ({
      availableWidgets: WIDGET_MAP[level],
      availableTools: TOOL_MAP[level],
      showAdvanced: level === "advanced",
      tooltipLevel: TOOLTIP_MAP[level],
      defaultPreset: PRESET_MAP[level],
    }),
    [level],
  );
}

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
  "dashboard",
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
  "depth",
  "greeks",
  "oichart",
  "sectormap",
  "gex",
  "news",
  "calculator",
  "ticker",
  "mtmmonitor",
];

/**
 * Advanced — all registered widgets. Kept as an explicit list (rather than
 * "show everything") so new widgets added to widgetCatalog default to
 * advanced-only until deliberately promoted to a lower level.
 */
const ADVANCED_WIDGETS: string[] = [
  ...INTERMEDIATE_WIDGETS,
  "scalper",
  "tradebook",
  "riskpanel",
  "actioncenter",
  "volsurface",
  "ivsmile",
  "straddlepnl",
  "oiprofile",
  "orderflow",
  "depthheatmap",
  "scanner",
  "alerts",
  "health",
  "threepanel",
  "aiadvisor",
];

/** Tools available per skill level on the /trade route. */
const BEGINNER_TOOLS: string[] = ["settings"];
const INTERMEDIATE_TOOLS: string[] = ["trade-journal", "settings"];
const ADVANCED_TOOLS: string[] = [
  "pnl-dashboard",
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

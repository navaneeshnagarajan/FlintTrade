export type WidgetSurface = "home" | "trade" | "shared";
export type WidgetAvailability = "sample-only" | "live-only" | "live-or-sample";

export interface WidgetMeta {
  id: string;
  name: string;
  icon: string;
  category: "Trading" | "Analysis" | "Utility";
  description?: string;
  /** Slice 3 — mounting ownership */
  surface: WidgetSurface;
  /** Slice 3 — static data contract */
  availability: WidgetAvailability;
  /** Optional: paired Home card componentId when surface === "shared" */
  homePairId?: string;
}

/**
 * The panel-scoped API a widget receives from the workspace layer.
 *
 * This is FlintTrade's own contract, implemented over flexlayout-react —
 * widgets never import the docking library directly, which is what made the
 * Dockview → FlexLayout swap a retype rather than a rewrite. Keep it narrow:
 * the audited widget surface uses exactly `id` and `updateParameters`.
 */
export interface WidgetPanelApi {
  /** Stable panel (tab node) id — chart display settings are keyed by it. */
  readonly id: string;
  /**
   * Merge params into the panel's persisted config so view state (tab,
   * view, symbol, scale…) survives with the saved layout.
   *
   * Pass ONLY the keys you changed. The adapter merges them over the
   * panel's LIVE persisted config. Never spread `props.params` into the
   * call: the rendered params snapshot is not refreshed on config-only
   * changes, so spreading it would silently revert other keys to their
   * mount-time values (the stale-spread clobber the Phase 1 audit caught).
   */
  updateParameters(params: Record<string, unknown>): void;
}

/**
 * Props every workspace widget receives. `params` carries the panel config
 * as it was when the panel content last rendered — treat it as the INITIAL
 * view state plus pinning, not a live channel (config-only updates do not
 * re-render the panel).
 */
export interface WidgetProps {
  params?: Record<string, unknown>;
  api: WidgetPanelApi;
}

// NOTE: A `WidgetId` union type previously lived here listing 30 hardcoded
// widget identifiers, but the registry in `src/layout/widgetFactory.tsx` now
// holds 83 entries. The union had zero consumers (verified by grep across
// the whole `src/` tree) and would have silently accepted any string for the
// 50+ widgets it omitted, so it was removed on 2026-05-19. If type-safe
// widget IDs are needed in future, derive them from the factory directly:
//
//   import { lazyWidgets } from "@/layout/widgetFactory";
//   type WidgetId = keyof typeof lazyWidgets;

export type ToolId =
  | "settings"
  | "trade-journal";

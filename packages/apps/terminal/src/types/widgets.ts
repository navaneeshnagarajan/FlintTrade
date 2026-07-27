export interface WidgetMeta {
  id: string;
  name: string;
  icon: string;
  category: "Trading" | "Analysis" | "Utility";
  description?: string;
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
   */
  updateParameters(params: Record<string, unknown>): void;
}

/**
 * Props every workspace widget receives. `params` carries the panel config
 * (pinned symbol, view mode, sync group…); `api` is the panel handle.
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

import type { IDockviewPanelProps } from "dockview-react";

export interface WidgetMeta {
  id: string;
  name: string;
  icon: string;
  category: "Trading" | "Analysis" | "Utility";
  description?: string;
}

export interface WidgetProps extends IDockviewPanelProps {
  // Additional FlintTrade-specific props can go here
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

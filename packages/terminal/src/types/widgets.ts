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

export type WidgetId =
  | "dashboard"
  | "scalper"
  | "positions"
  | "orders"
  | "holdings"
  | "tradebook"
  | "orderpad"
  | "mtmmonitor"
  | "riskpanel"
  | "chart"
  | "optionchain"
  | "oichart"
  | "straddle"
  | "depth"
  | "greeks"
  | "sectormap"
  | "watchlist"
  | "calculator"
  | "news"
  | "ticker"
  | "aiadvisor"
  | "orderflow"
  | "depthheatmap"
  | "actioncenter"
  | "gex"
  | "volsurface"
  | "ivsmile"
  | "straddlepnl"
  | "oiprofile"
  | "scanner"
  | "positionheatmap"
  | "marketbreadth"
  | "quicktrade"
  | "volatilitycone"
  | "profittarget";

export type ToolId =
  | "settings"
  | "pnl-dashboard"
  | "trade-journal"
  | "market-intelligence";

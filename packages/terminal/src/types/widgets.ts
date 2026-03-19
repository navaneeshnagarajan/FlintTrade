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
  | "aiadvisor";

export type ToolId =
  | "settings"
  | "backtest-lab"
  | "trade-journal"
  | "strategy-builder"
  | "pnl-dashboard"
  | "market-intelligence"
  | "flow-builder";

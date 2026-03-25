import type { DockviewApi } from "dockview-react";

export type ConnectionStatus = "connected" | "disconnected" | "connecting" | "error";

export interface ConnectionState {
  host: string;
  apiKey: string;
  wsUrl: string;
  status: ConnectionStatus;
  wsConnected: boolean;
  lastPing: number | null;
}

export interface LayoutPreset {
  id: string;
  name: string;
  description: string;
  panels: SerializedLayout;
}

export interface LayoutTab {
  id: string;
  name: string;
}

export interface LayoutState {
  tabs: LayoutTab[];
  activeTabId: string;
  dockviewApi: DockviewApi | null;
  presets: LayoutPreset[];
}

export interface TradingState {
  totalPnl: number;
  totalPnlPercent: number;
  positionCount: number;
  openOrderCount: number;
  usedMargin: number;
  availableMargin: number;
}

export interface SettingsState {
  persona: "trader" | "investor" | "beginner";
  density: "compact" | "comfortable";
  defaultExchange: string;
  defaultProduct: string;
  defaultQty: number;
  defaultOrderType: string;
  fontSize: "small" | "normal" | "large";
  riskLimits: {
    maxPositionLots: number;
    mtmStoploss: number;
    mtmTarget: number;
    maxOrdersPerMinute: number;
  };
}

export type SerializedLayout = Record<string, unknown>;

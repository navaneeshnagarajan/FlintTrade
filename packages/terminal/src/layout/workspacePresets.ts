/**
 * workspacePresets.ts
 *
 * Defines the 6 built-in workspace layout presets for the FlintTrade terminal.
 * Each preset is applied programmatically via Dockview's `addPanel()` API so
 * that panels are positioned relative to each other — no serialized JSON is
 * stored, which means presets stay stable across Dockview version upgrades.
 *
 * Direction reference (Dockview):
 *   "right"  — new panel opens to the right of the reference panel
 *   "below"  — new panel opens below the reference panel
 *   "left"   — new panel opens to the left of the reference panel
 *   "above"  — new panel opens above the reference panel
 *   "within" — new panel added as a new tab inside the same group
 */

import type { DockviewApi } from "dockview-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WorkspacePreset {
  id: string;
  name: string;
  description: string;
  icon: string; // lucide-react icon name
  apply: (api: DockviewApi) => void;
}

// ---------------------------------------------------------------------------
// Helper: generate a stable-per-call unique panel id
// ---------------------------------------------------------------------------
function pid(base: string): string {
  return `${base}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
}

// ---------------------------------------------------------------------------
// Preset 1 — Scalper Zone
//
// ┌──────────────────┬──────────┐
// │                  │ OrderPad │
// │     Chart        ├──────────┤
// │                  │ Depth    │
// ├──────────────────┼──────────┤
// │   Positions      │ Scalper  │
// └──────────────────┴──────────┘
// ---------------------------------------------------------------------------
function applyScalperZone(api: DockviewApi): void {
  const chartId = pid("chart");
  const orderPadId = pid("orderpad");
  const depthId = pid("depth");
  const positionsId = pid("positions");
  const scalperId = pid("scalper");

  api.addPanel({ id: chartId, component: "chart", title: "Chart" });

  api.addPanel({
    id: orderPadId,
    component: "orderpad",
    title: "Order Pad",
    position: { referencePanel: chartId, direction: "right" },
    initialWidth: 280,
  });

  api.addPanel({
    id: depthId,
    component: "depth",
    title: "Depth",
    position: { referencePanel: orderPadId, direction: "below" },
  });

  api.addPanel({
    id: positionsId,
    component: "positions",
    title: "Positions",
    position: { referencePanel: chartId, direction: "below" },
    initialHeight: 200,
  });

  api.addPanel({
    id: scalperId,
    component: "scalper",
    title: "Scalper",
    position: { referencePanel: positionsId, direction: "right" },
  });
}

// ---------------------------------------------------------------------------
// Preset 2 — Options Desk
//
// ┌──────────────────────────────┐
// │        Option Chain          │
// ├──────────────┬───────────────┤
// │    Chart     │   Greeks      │
// ├──────────────┼───────────────┤
// │  Positions   │   Straddle    │
// └──────────────┴───────────────┘
// ---------------------------------------------------------------------------
function applyOptionsDesk(api: DockviewApi): void {
  const optionChainId = pid("optionchain");
  const chartId = pid("chart");
  const greeksId = pid("greeks");
  const positionsId = pid("positions");
  const straddleId = pid("straddle");

  api.addPanel({
    id: optionChainId,
    component: "optionchain",
    title: "Option Chain",
    initialHeight: 320,
  });

  api.addPanel({
    id: chartId,
    component: "chart",
    title: "Chart",
    position: { referencePanel: optionChainId, direction: "below" },
  });

  api.addPanel({
    id: greeksId,
    component: "greeks",
    title: "Greeks",
    position: { referencePanel: chartId, direction: "right" },
    initialWidth: 340,
  });

  api.addPanel({
    id: positionsId,
    component: "positions",
    title: "Positions",
    position: { referencePanel: chartId, direction: "below" },
    initialHeight: 200,
  });

  api.addPanel({
    id: straddleId,
    component: "straddle",
    title: "Straddle",
    position: { referencePanel: positionsId, direction: "right" },
  });
}

// ---------------------------------------------------------------------------
// Preset 3 — Market Watch (also used as the default startup layout)
//
// ┌──────────┬────────────────────┐
// │          │                    │
// │ Watchlist│      Chart         │
// │          │                    │
// ├──────────┼────────────────────┤
// │  Ticker  │    Dashboard       │
// └──────────┴────────────────────┘
// ---------------------------------------------------------------------------
function applyMarketWatch(api: DockviewApi): void {
  const watchlistId = pid("watchlist");
  const chartId = pid("chart");
  const tickerId = pid("ticker");
  const dashboardId = pid("dashboard");

  api.addPanel({
    id: watchlistId,
    component: "watchlist",
    title: "Watchlist",
    initialWidth: 280,
  });

  api.addPanel({
    id: chartId,
    component: "chart",
    title: "Chart",
    position: { referencePanel: watchlistId, direction: "right" },
  });

  api.addPanel({
    id: tickerId,
    component: "ticker",
    title: "Ticker",
    position: { referencePanel: watchlistId, direction: "below" },
    initialHeight: 200,
  });

  api.addPanel({
    id: dashboardId,
    component: "dashboard",
    title: "Dashboard",
    position: { referencePanel: chartId, direction: "below" },
    initialHeight: 200,
  });
}

// ---------------------------------------------------------------------------
// Preset 4 — Analysis
//
// ┌──────────────┬───────────────┐
// │              │   OI Chart    │
// │    Chart     ├───────────────┤
// │              │   Depth       │
// ├──────────────┼───────────────┤
// │  Positions   │   News        │
// └──────────────┴───────────────┘
// ---------------------------------------------------------------------------
function applyAnalysis(api: DockviewApi): void {
  const chartId = pid("chart");
  const oiChartId = pid("oichart");
  const depthId = pid("depth");
  const positionsId = pid("positions");
  const newsId = pid("news");

  api.addPanel({ id: chartId, component: "chart", title: "Chart" });

  api.addPanel({
    id: oiChartId,
    component: "oichart",
    title: "OI Chart",
    position: { referencePanel: chartId, direction: "right" },
    initialWidth: 340,
  });

  api.addPanel({
    id: depthId,
    component: "depth",
    title: "Depth",
    position: { referencePanel: oiChartId, direction: "below" },
  });

  api.addPanel({
    id: positionsId,
    component: "positions",
    title: "Positions",
    position: { referencePanel: chartId, direction: "below" },
    initialHeight: 200,
  });

  api.addPanel({
    id: newsId,
    component: "news",
    title: "News",
    position: { referencePanel: positionsId, direction: "right" },
  });
}

// ---------------------------------------------------------------------------
// Preset 5 — Risk Monitor
//
// ┌──────────────┬───────────────┐
// │  Dashboard   │  Risk Panel   │
// ├──────────────┼───────────────┤
// │  MTM Monitor │  Positions    │
// ├──────────────┴───────────────┤
// │         Orders               │
// └──────────────────────────────┘
// ---------------------------------------------------------------------------
function applyRiskMonitor(api: DockviewApi): void {
  const dashboardId = pid("dashboard");
  const riskPanelId = pid("riskpanel");
  const mtmMonitorId = pid("mtmmonitor");
  const positionsId = pid("positions");
  const ordersId = pid("orders");

  api.addPanel({ id: dashboardId, component: "dashboard", title: "Dashboard" });

  api.addPanel({
    id: riskPanelId,
    component: "riskpanel",
    title: "Risk Panel",
    position: { referencePanel: dashboardId, direction: "right" },
    initialWidth: 340,
  });

  api.addPanel({
    id: mtmMonitorId,
    component: "mtmmonitor",
    title: "MTM Monitor",
    position: { referencePanel: dashboardId, direction: "below" },
  });

  api.addPanel({
    id: positionsId,
    component: "positions",
    title: "Positions",
    position: { referencePanel: mtmMonitorId, direction: "right" },
  });

  api.addPanel({
    id: ordersId,
    component: "orders",
    title: "Orders",
    position: { referencePanel: mtmMonitorId, direction: "below" },
    initialHeight: 200,
  });
}

// ---------------------------------------------------------------------------
// Preset 6 — Investor View
//
// ┌──────────────┬───────────────┐
// │              │   Watchlist   │
// │    Chart     ├───────────────┤
// │              │   Holdings    │
// ├──────────────┴───────────────┤
// │          Dashboard           │
// └──────────────────────────────┘
// ---------------------------------------------------------------------------
function applyInvestorView(api: DockviewApi): void {
  const chartId = pid("chart");
  const watchlistId = pid("watchlist");
  const holdingsId = pid("holdings");
  const dashboardId = pid("dashboard");

  api.addPanel({ id: chartId, component: "chart", title: "Chart" });

  api.addPanel({
    id: watchlistId,
    component: "watchlist",
    title: "Watchlist",
    position: { referencePanel: chartId, direction: "right" },
    initialWidth: 300,
  });

  api.addPanel({
    id: holdingsId,
    component: "holdings",
    title: "Holdings",
    position: { referencePanel: watchlistId, direction: "below" },
  });

  api.addPanel({
    id: dashboardId,
    component: "dashboard",
    title: "Dashboard",
    position: { referencePanel: chartId, direction: "below" },
    initialHeight: 220,
  });
}

// ---------------------------------------------------------------------------
// Preset registry (exported)
// ---------------------------------------------------------------------------
export const WORKSPACE_PRESETS: WorkspacePreset[] = [
  {
    id: "scalper-zone",
    name: "Scalper Zone",
    description: "Chart + Order Pad + Depth + Positions + Scalper",
    icon: "Zap",
    apply: applyScalperZone,
  },
  {
    id: "options-desk",
    name: "Options Desk",
    description: "Option Chain + Chart + Greeks + Positions + Straddle",
    icon: "Grid3x3",
    apply: applyOptionsDesk,
  },
  {
    id: "market-watch",
    name: "Market Watch",
    description: "Watchlist + Chart + Ticker + Dashboard",
    icon: "Star",
    apply: applyMarketWatch,
  },
  {
    id: "analysis",
    name: "Analysis",
    description: "Chart + OI Chart + Depth + Positions + News",
    icon: "BarChart3",
    apply: applyAnalysis,
  },
  {
    id: "risk-monitor",
    name: "Risk Monitor",
    description: "Dashboard + Risk Panel + MTM Monitor + Positions + Orders",
    icon: "ShieldAlert",
    apply: applyRiskMonitor,
  },
  {
    id: "investor-view",
    name: "Investor View",
    description: "Chart + Watchlist + Holdings + Dashboard",
    icon: "TrendingUp",
    apply: applyInvestorView,
  },
];

// ---------------------------------------------------------------------------
// applyPreset — clear the canvas and apply a preset by id
// ---------------------------------------------------------------------------
export function applyPreset(api: DockviewApi, presetId: string): void {
  const preset = WORKSPACE_PRESETS.find((p) => p.id === presetId);
  if (!preset) {
    console.warn(`[workspacePresets] Unknown preset id: "${presetId}"`);
    return;
  }
  api.clear();
  preset.apply(api);
}

// Convenience export: the default startup preset id
export const DEFAULT_PRESET_ID = "market-watch";

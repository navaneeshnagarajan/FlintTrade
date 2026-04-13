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
// Preset 7 — Options Analysis
//
// ┌──────────────────────────────┐
// │        Option Chain          │
// ├──────────┬───────────────────┤
// │ IV Skew  │  Greeks Heatmap   │
// ├──────────┼───────────────────┤
// │ Implied  │   Straddle P&L    │
// │  Move    │                   │
// └──────────┴───────────────────┘
// ---------------------------------------------------------------------------
function applyOptionsAnalysis(api: DockviewApi): void {
  const optionChainId = pid("optionchain");
  const ivSkewId = pid("ivskew");
  const greeksHeatmapId = pid("greeksheatmap");
  const impliedMoveId = pid("impliedmove");
  const straddlePnlId = pid("straddlepnl");

  api.addPanel({
    id: optionChainId,
    component: "optionchain",
    title: "Option Chain",
    initialHeight: 320,
  });

  api.addPanel({
    id: ivSkewId,
    component: "ivskew",
    title: "IV Skew",
    position: { referencePanel: optionChainId, direction: "below" },
    initialWidth: 340,
  });

  api.addPanel({
    id: greeksHeatmapId,
    component: "greeksheatmap",
    title: "Greeks Heatmap",
    position: { referencePanel: ivSkewId, direction: "right" },
  });

  api.addPanel({
    id: impliedMoveId,
    component: "impliedmove",
    title: "Implied Move",
    position: { referencePanel: ivSkewId, direction: "below" },
    initialHeight: 220,
  });

  api.addPanel({
    id: straddlePnlId,
    component: "straddlepnl",
    title: "Straddle P&L",
    position: { referencePanel: impliedMoveId, direction: "right" },
  });
}

// ---------------------------------------------------------------------------
// Preset 8 — Sector View
//
// ┌──────────────┬───────────────┐
// │  Sector Map  │ Sector Perf.  │
// ├──────────────┼───────────────┤
// │Market Breadth│ Heat Calendar │
// ├──────────────┴───────────────┤
// │     Correlation Matrix       │
// └──────────────────────────────┘
// ---------------------------------------------------------------------------
function applySectorView(api: DockviewApi): void {
  const sectorMapId = pid("sectormap");
  const sectorPerfId = pid("sectorperformance");
  const marketBreadthId = pid("marketbreadth");
  const heatCalendarId = pid("heatcalendar");
  const correlationMatrixId = pid("correlationmatrix");

  api.addPanel({
    id: sectorMapId,
    component: "sectormap",
    title: "Sector Map",
  });

  api.addPanel({
    id: sectorPerfId,
    component: "sectorperformance",
    title: "Sector Performance",
    position: { referencePanel: sectorMapId, direction: "right" },
    initialWidth: 360,
  });

  api.addPanel({
    id: marketBreadthId,
    component: "marketbreadth",
    title: "Market Breadth",
    position: { referencePanel: sectorMapId, direction: "below" },
    initialHeight: 220,
  });

  api.addPanel({
    id: heatCalendarId,
    component: "heatcalendar",
    title: "Heat Calendar",
    position: { referencePanel: marketBreadthId, direction: "right" },
  });

  api.addPanel({
    id: correlationMatrixId,
    component: "correlationmatrix",
    title: "Correlation Matrix",
    position: { referencePanel: marketBreadthId, direction: "below" },
    initialHeight: 200,
  });
}

// ---------------------------------------------------------------------------
// Preset 9 — Algo Trading
//
// ┌────────────────┬──────────────┐
// │Strategy Monitor│  Flow Builder│  (tab)
// │                │  Backtest Lab│
// ├────────────────┼──────────────┤
// │Strategy        │ Session Stats│
// │ Templates      │              │
// └────────────────┴──────────────┘
// ---------------------------------------------------------------------------
function applyAlgoTrading(api: DockviewApi): void {
  const strategyMonitorId = pid("strategymonitor");
  const flowBuilderId = pid("flowbuilder-tab");
  const strategyTemplatesId = pid("strategytemplates");
  const sessionStatsId = pid("sessionstats");

  api.addPanel({
    id: strategyMonitorId,
    component: "strategymonitor",
    title: "Strategy Monitor",
  });

  // Flow Builder lives at /automate — open chart as a stand-in analysis panel
  api.addPanel({
    id: flowBuilderId,
    component: "chart",
    title: "Chart (Algo)",
    position: { referencePanel: strategyMonitorId, direction: "right" },
    initialWidth: 400,
  });

  api.addPanel({
    id: strategyTemplatesId,
    component: "strategytemplates",
    title: "Strategy Templates",
    position: { referencePanel: strategyMonitorId, direction: "below" },
    initialHeight: 240,
  });

  api.addPanel({
    id: sessionStatsId,
    component: "sessionstats",
    title: "Session Stats",
    position: { referencePanel: strategyTemplatesId, direction: "right" },
  });
}

// ---------------------------------------------------------------------------
// Preset 10 — Portfolio Manager
//
// ┌──────────────────┬────────────┐
// │PortfolioAllocation│Net Position│
// ├──────────────────┼────────────┤
// │ Position Heatmap  │RiskDashboard│
// ├──────────────────┴────────────┤
// │       Trade Performance        │
// └────────────────────────────────┘
// ---------------------------------------------------------------------------
function applyPortfolioManager(api: DockviewApi): void {
  const portfolioAllocId = pid("portfolioallocation");
  const netPositionId = pid("netposition");
  const positionHeatmapId = pid("positionheatmap");
  const riskDashboardId = pid("riskdashboard");
  const tradePerformanceId = pid("tradeperformance");

  api.addPanel({
    id: portfolioAllocId,
    component: "portfolioallocation",
    title: "Portfolio Allocation",
  });

  api.addPanel({
    id: netPositionId,
    component: "netposition",
    title: "Net Positions",
    position: { referencePanel: portfolioAllocId, direction: "right" },
    initialWidth: 340,
  });

  api.addPanel({
    id: positionHeatmapId,
    component: "positionheatmap",
    title: "Position Heat Map",
    position: { referencePanel: portfolioAllocId, direction: "below" },
    initialHeight: 220,
  });

  api.addPanel({
    id: riskDashboardId,
    component: "riskdashboard",
    title: "Risk Dashboard",
    position: { referencePanel: positionHeatmapId, direction: "right" },
  });

  api.addPanel({
    id: tradePerformanceId,
    component: "tradeperformance",
    title: "Trade Performance",
    position: { referencePanel: positionHeatmapId, direction: "below" },
    initialHeight: 200,
  });
}

// ---------------------------------------------------------------------------
// Preset 11 — Market Overview
//
// ┌──────────────┬───────────────┐
// │Market Summary│ Global Indices│
// ├──────────────┼───────────────┤
// │Economic Cal. │ Earnings Cal. │
// ├──────────────┼───────────────┤
// │ Market Clock │    News       │
// └──────────────┴───────────────┘
// ---------------------------------------------------------------------------
function applyMarketOverview(api: DockviewApi): void {
  const marketSummaryId = pid("marketsummary");
  const globalIndicesId = pid("globalindices");
  const economicCalId = pid("economiccalendar");
  const earningsCalId = pid("earningscalendar");
  const marketClockId = pid("marketclock");
  const newsId = pid("news");

  api.addPanel({
    id: marketSummaryId,
    component: "marketsummary",
    title: "Market Summary",
  });

  api.addPanel({
    id: globalIndicesId,
    component: "globalindices",
    title: "Global Indices",
    position: { referencePanel: marketSummaryId, direction: "right" },
    initialWidth: 360,
  });

  api.addPanel({
    id: economicCalId,
    component: "economiccalendar",
    title: "Economic Calendar",
    position: { referencePanel: marketSummaryId, direction: "below" },
    initialHeight: 220,
  });

  api.addPanel({
    id: earningsCalId,
    component: "earningscalendar",
    title: "Earnings Calendar",
    position: { referencePanel: economicCalId, direction: "right" },
  });

  api.addPanel({
    id: marketClockId,
    component: "marketclock",
    title: "Market Clock",
    position: { referencePanel: economicCalId, direction: "below" },
    initialHeight: 160,
  });

  api.addPanel({
    id: newsId,
    component: "news",
    title: "News Feed",
    position: { referencePanel: marketClockId, direction: "right" },
  });
}

// ---------------------------------------------------------------------------
// Preset 12 — Quick Scalper
//
// ┌────────────┬──────────────┬──────────┐
// │ Quick Trade│DepthHeatmap  │TickSpeed │
// ├────────────┼──────────────┴──────────┤
// │ Order Lad. │   Microstructure        │
// ├────────────┴─────────────────────────┤
// │          Intraday P&L                │
// └──────────────────────────────────────┘
// ---------------------------------------------------------------------------
function applyQuickScalper(api: DockviewApi): void {
  const quickTradeId = pid("quicktrade");
  const depthHeatmapId = pid("depthheatmap");
  const tickSpeedId = pid("tickspeed");
  const orderLadderId = pid("orderladder");
  const microstructureId = pid("microstructure");
  const intradayPnlId = pid("intradaypnl");

  api.addPanel({
    id: quickTradeId,
    component: "quicktrade",
    title: "Quick Trade",
    initialWidth: 260,
  });

  api.addPanel({
    id: depthHeatmapId,
    component: "depthheatmap",
    title: "Depth Heatmap",
    position: { referencePanel: quickTradeId, direction: "right" },
  });

  api.addPanel({
    id: tickSpeedId,
    component: "tickspeed",
    title: "Tick Speed",
    position: { referencePanel: depthHeatmapId, direction: "right" },
    initialWidth: 200,
  });

  api.addPanel({
    id: orderLadderId,
    component: "orderladder",
    title: "Order Ladder",
    position: { referencePanel: quickTradeId, direction: "below" },
    initialHeight: 260,
  });

  api.addPanel({
    id: microstructureId,
    component: "microstructure",
    title: "Market Microstructure",
    position: { referencePanel: orderLadderId, direction: "right" },
  });

  api.addPanel({
    id: intradayPnlId,
    component: "intradaypnl",
    title: "Intraday P&L",
    position: { referencePanel: orderLadderId, direction: "below" },
    initialHeight: 180,
  });
}

// ---------------------------------------------------------------------------
// Preset 13 — Everything
//
// Every widget in the catalogue, organised into 6 tabbed groups:
//   Charts | Trading | Options | Analysis | Positions/Risk | Utility
//
// Use this to explore every widget in a single workspace.
// ---------------------------------------------------------------------------
function applyEverything(api: DockviewApi): void {
  // ---------- Column 1: Charts ----------
  const chartId = pid("chart");
  api.addPanel({ id: chartId, component: "chart", title: "Chart" });

  for (const comp of ["chartgrid", "threepanel", "multitimeframe"] as const) {
    api.addPanel({
      id: pid(comp),
      component: comp,
      title: comp,
      position: { referencePanel: chartId, direction: "within" },
    });
  }

  // ---------- Column 2: Trading core ----------
  const scalperId = pid("scalper");
  api.addPanel({
    id: scalperId,
    component: "scalper",
    title: "Scalper",
    position: { referencePanel: chartId, direction: "right" },
    initialWidth: 360,
  });

  for (const comp of ["orderpad", "quicktrade", "orderladder"] as const) {
    api.addPanel({
      id: pid(comp),
      component: comp,
      title: comp,
      position: { referencePanel: scalperId, direction: "within" },
    });
  }

  // ---------- Column 3: Options ----------
  const optionChainId = pid("optionchain");
  api.addPanel({
    id: optionChainId,
    component: "optionchain",
    title: "Option Chain",
    position: { referencePanel: scalperId, direction: "right" },
    initialWidth: 380,
  });

  for (const comp of [
    "oichart", "straddle", "straddlepnl", "greeks", "greeksheatmap",
    "greekssurface", "ivsmile", "ivskew", "oiprofile", "oiheatmap",
    "impliedmove", "optionsflow", "volatilitycone",
  ] as const) {
    api.addPanel({
      id: pid(comp),
      component: comp,
      title: comp,
      position: { referencePanel: optionChainId, direction: "within" },
    });
  }

  // ---------- Row 2 left: Analysis ----------
  const depthId = pid("depth");
  api.addPanel({
    id: depthId,
    component: "depth",
    title: "Depth",
    position: { referencePanel: chartId, direction: "below" },
    initialHeight: 300,
  });

  for (const comp of [
    "depthheatmap", "gex", "volsurface", "orderflow", "sectormap",
    "sectorperformance", "marketbreadth", "correlationpairs",
    "correlationmatrix", "instrumentcompare", "spreadview", "pcrtrend",
    "gapanalysis", "heatcalendar", "vwapbands", "pivotpoints",
    "orderbookreplay", "microstructure",
  ] as const) {
    api.addPanel({
      id: pid(comp),
      component: comp,
      title: comp,
      position: { referencePanel: depthId, direction: "within" },
    });
  }

  // ---------- Row 2 center: Positions / Risk ----------
  const dashboardId = pid("dashboard");
  api.addPanel({
    id: dashboardId,
    component: "dashboard",
    title: "Dashboard",
    position: { referencePanel: depthId, direction: "right" },
  });

  for (const comp of [
    "positions", "orders", "holdings", "tradebook", "intradaypnl",
    "mtmmonitor", "positionheatmap", "portfolioallocation", "netposition",
    "sessionstats", "tradeperformance", "tradelog", "riskpanel",
    "riskdashboard", "actioncenter", "strategymonitor", "tradecopier",
  ] as const) {
    api.addPanel({
      id: pid(comp),
      component: comp,
      title: comp,
      position: { referencePanel: dashboardId, direction: "within" },
    });
  }

  // ---------- Row 2 right: Utility ----------
  const watchlistId = pid("watchlist");
  api.addPanel({
    id: watchlistId,
    component: "watchlist",
    title: "Watchlist",
    position: { referencePanel: dashboardId, direction: "right" },
    initialWidth: 320,
  });

  for (const comp of [
    "calculator", "news", "ticker", "aiadvisor", "scanner", "alerts",
    "health", "fundingrate", "currencyconverter", "earningscalendar",
    "globalindices", "strategytemplates", "audittrail", "economiccalendar",
    "profittarget", "expirycountdown", "positionsizing", "marketclock",
    "tradeidea", "tickspeed", "marketsummary",
  ] as const) {
    api.addPanel({
      id: pid(comp),
      component: comp,
      title: comp,
      position: { referencePanel: watchlistId, direction: "within" },
    });
  }
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
  {
    id: "options-analysis",
    name: "Options Analysis",
    description: "Option Chain + IV Skew + Greeks Heatmap + Implied Move + Straddle P&L",
    icon: "Sigma",
    apply: applyOptionsAnalysis,
  },
  {
    id: "sector-view",
    name: "Sector View",
    description: "Sector Map + Sector Performance + Market Breadth + Heat Calendar + Correlation Matrix",
    icon: "Map",
    apply: applySectorView,
  },
  {
    id: "algo-trading",
    name: "Algo Trading",
    description: "Strategy Monitor + Chart + Strategy Templates + Session Stats",
    icon: "Bot",
    apply: applyAlgoTrading,
  },
  {
    id: "portfolio-manager",
    name: "Portfolio Manager",
    description: "Portfolio Allocation + Net Positions + Position Heatmap + Risk Dashboard + Trade Performance",
    icon: "PieChart",
    apply: applyPortfolioManager,
  },
  {
    id: "market-overview",
    name: "Market Overview",
    description: "Market Summary + Global Indices + Economic Calendar + Earnings Calendar + Market Clock + News",
    icon: "Globe",
    apply: applyMarketOverview,
  },
  {
    id: "quick-scalper",
    name: "Quick Scalper",
    description: "Quick Trade + Order Ladder + Depth Heatmap + Microstructure + Tick Speed + Intraday P&L",
    icon: "Gauge",
    apply: applyQuickScalper,
  },
  {
    id: "everything",
    name: "Everything",
    description: "All widgets in one workspace — Charts, Trading, Options, Analysis, Positions, Utility",
    icon: "LayoutDashboard",
    apply: applyEverything,
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

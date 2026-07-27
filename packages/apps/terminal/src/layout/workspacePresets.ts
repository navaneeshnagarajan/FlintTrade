/**
 * workspacePresets.ts
 *
 * Defines the built-in workspace layout presets for the FlintTrade terminal.
 * Each preset is a pure builder returning a FlexLayout `IJsonModel` document
 * (rows → tabsets → tabs, explicit weights everywhere). Builders run fresh on
 * every apply so panel ids are unique per application, and no serialised
 * library-version-specific state is stored in this file — presets stay stable
 * across FlexLayout upgrades.
 *
 * Geometry reference (FlexLayout): the root row lays children out
 * HORIZONTALLY; a row nested inside it lays out VERTICALLY, and so on,
 * alternating by depth. Weights are relative within one row.
 */

import type { IJsonModel } from "flexlayout-react";
import {
  rowJson,
  tabJson,
  tabsetJson,
  workspaceJson,
  type WorkspaceApi,
} from "@/layout/flexLayoutAdapter";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WorkspacePreset {
  id: string;
  name: string;
  description: string;
  icon: string; // lucide-react icon name
  build: () => IJsonModel;
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
function buildScalperZone(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(75, [
        tabsetJson(70, [tabJson("chart", "Chart")]),
        tabsetJson(30, [tabJson("positions", "Positions")]),
      ]),
      rowJson(25, [
        tabsetJson(35, [tabJson("orderpad", "Order Pad")]),
        // NSE tick puts each broker level on its own row — the retired
        // Depth widget's 5-level table.
        tabsetJson(35, [tabJson("orderladder", "DOM / Ladder", { params: { tick: 0.05 } })]),
        tabsetJson(30, [tabJson("scalper", "Scalper")]),
      ]),
    ]),
  );
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
function buildOptionsDesk(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(100, [
        tabsetJson(38, [tabJson("optionchain", "Option Chain")]),
        rowJson(37, [
          tabsetJson(62, [tabJson("chart", "Chart")]),
          tabsetJson(38, [tabJson("greeks", "Greeks")]),
        ]),
        rowJson(25, [
          tabsetJson(62, [tabJson("positions", "Positions")]),
          tabsetJson(38, [tabJson("straddle", "Straddle")]),
        ]),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 3 — Market Watch (also used as the default startup layout)
//
// ┌──────────┬────────────────────┐
// │          │                    │
// │ Watchlist│      Chart         │
// │          │                    │
// ├──────────┼────────────────────┤
// │  Ticker  │    Indices         │
// └──────────┴────────────────────┘
// ---------------------------------------------------------------------------
function buildMarketWatch(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(25, [
        tabsetJson(72, [tabJson("watchlist", "Watchlist")]),
        tabsetJson(28, [tabJson("ticker", "Ticker")]),
      ]),
      rowJson(75, [
        tabsetJson(72, [tabJson("chart", "Chart")]),
        tabsetJson(28, [tabJson("indexstrip", "Indices")]),
      ]),
    ]),
  );
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
function buildAnalysis(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(70, [
        tabsetJson(70, [tabJson("chart", "Chart")]),
        rowJson(30, [
          tabsetJson(60, [tabJson("positions", "Positions")]),
          tabsetJson(40, [tabJson("news", "News")]),
        ]),
      ]),
      rowJson(30, [
        tabsetJson(50, [tabJson("oichart", "OI Chart")]),
        // NSE tick — see Scalper Zone note.
        tabsetJson(50, [tabJson("orderladder", "DOM / Ladder", { params: { tick: 0.05 } })]),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 5 — Risk Monitor
//
// ┌──────────────┬───────────────┐
// │  Indices     │  Risk Panel   │
// ├──────────────┼───────────────┤
// │  MTM Monitor │  Positions    │
// ├──────────────┴───────────────┤
// │         Orders               │
// └──────────────────────────────┘
// ---------------------------------------------------------------------------
function buildRiskMonitor(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(100, [
        rowJson(30, [
          tabsetJson(65, [tabJson("indexstrip", "Indices")]),
          tabsetJson(35, [tabJson("riskdashboard", "Risk")]),
        ]),
        rowJson(45, [
          tabsetJson(50, [tabJson("pnlmonitor", "MTM Monitor")]),
          tabsetJson(50, [tabJson("positions", "Positions")]),
        ]),
        tabsetJson(25, [tabJson("orders", "Orders")]),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 6 — Investor View
//
// ┌──────────────┬───────────────┐
// │              │   Watchlist   │
// │    Chart     ├───────────────┤
// │              │   Holdings    │
// ├──────────────┴───────────────┤
// │          Indices             │
// └──────────────────────────────┘
// ---------------------------------------------------------------------------
function buildInvestorView(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(100, [
        rowJson(75, [
          tabsetJson(72, [tabJson("chart", "Chart")]),
          rowJson(28, [
            tabsetJson(50, [tabJson("watchlist", "Watchlist")]),
            tabsetJson(50, [tabJson("holdings", "Holdings")]),
          ]),
        ]),
        tabsetJson(25, [tabJson("indexstrip", "Indices")]),
      ]),
    ]),
  );
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
function buildOptionsAnalysis(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(100, [
        tabsetJson(38, [tabJson("optionchain", "Option Chain")]),
        rowJson(37, [
          // The skew projection is what this preset slot has always shown.
          tabsetJson(35, [tabJson("ivsmile", "IV Skew", { params: { view: "skew" } })]),
          tabsetJson(65, [tabJson("greeksheatmap", "Greeks Heatmap")]),
        ]),
        rowJson(25, [
          tabsetJson(35, [tabJson("straddle", "Implied Move", { params: { view: "impliedmove" } })]),
          tabsetJson(65, [tabJson("straddlepnl", "Straddle P&L")]),
        ]),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 8 — Sector View
//
// ┌──────────────┬───────────────┐
// │  Sector Map  │               │
// ├──────────────┤ Sector Perf.  │
// │Market Breadth│               │
// ├──────────────┤               │
// │ Corr. Matrix │               │
// └──────────────┴───────────────┘
// ---------------------------------------------------------------------------
function buildSectorView(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(62, [
        tabsetJson(40, [tabJson("marketoverview", "Sector Map", { params: { tab: "sectors" } })]),
        tabsetJson(35, [tabJson("marketoverview", "Market Breadth", { params: { tab: "breadth" } })]),
        tabsetJson(25, [tabJson("correlationmatrix", "Correlation Matrix")]),
      ]),
      tabsetJson(38, [
        tabJson("marketoverview", "Sector Performance", { params: { tab: "sectors", view: "bars" } }),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 9 — Order Automation
//
// ┌────────────────┬──────────────┐
// │Strategy Monitor│ Chart (Algo) │
// ├────────────────┤              │
// │Strategy        │              │
// │ Templates      │              │
// └────────────────┴──────────────┘
// Flow Builder lives at /automate — the chart stands in as analysis surface.
// ---------------------------------------------------------------------------
function buildOrderAutomation(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(55, [
        tabsetJson(62, [tabJson("strategymonitor", "Strategy Monitor")]),
        tabsetJson(38, [tabJson("strategytemplates", "Strategy Templates")]),
      ]),
      tabsetJson(45, [tabJson("chart", "Chart (Algo)")]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 10 — Portfolio Manager
//
// ┌──────────────────┬────────────┐
// │PortfolioAlloc.   │            │
// ├──────────┬───────┤NetPosition │
// │ Heat Map │ Risk  │            │
// └──────────┴───────┴────────────┘
// ---------------------------------------------------------------------------
function buildPortfolioManager(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(65, [
        tabsetJson(50, [tabJson("portfolioallocation", "Portfolio Allocation")]),
        rowJson(50, [
          tabsetJson(60, [tabJson("positions", "Position Heat Map", { params: { view: "heat" } })]),
          tabsetJson(40, [tabJson("riskdashboard", "Risk Dashboard")]),
        ]),
      ]),
      tabsetJson(35, [tabJson("positions", "Net Positions", { params: { view: "net" } })]),
    ]),
  );
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
function buildMarketOverview(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(58, [
        tabsetJson(42, [tabJson("marketoverview", "Market Summary")]),
        tabsetJson(33, [tabJson("economiccalendar", "Economic Calendar")]),
        tabsetJson(25, [tabJson("marketclock", "Market Clock")]),
      ]),
      rowJson(42, [
        tabsetJson(42, [tabJson("marketoverview", "Global Indices", { params: { tab: "indices" } })]),
        tabsetJson(33, [tabJson("earningscalendar", "Earnings Calendar")]),
        tabsetJson(25, [tabJson("news", "News Feed")]),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 12 — Quick Scalper
//
// ┌────────────┬──────────────┬──────────┐
// │ Quick Trade│DOM Heatmap   │TickSpeed │
// ├────────────┼──────────────┴──────────┤
// │ Order Lad. │   Tape & Microstructure │
// ├────────────┴─────────────────────────┤
// │          Intraday P&L                │
// └──────────────────────────────────────┘
// ---------------------------------------------------------------------------
function buildQuickScalper(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(100, [
        rowJson(45, [
          tabsetJson(22, [tabJson("quicktrade", "Quick Trade")]),
          // The gamma power-scale is the look the retired Depth Heatmap had.
          tabsetJson(58, [tabJson("domheatmap", "DOM Heatmap", { params: { scale: "gamma" } })]),
          tabsetJson(20, [tabJson("tickspeed", "Tick Speed")]),
        ]),
        rowJson(35, [
          tabsetJson(30, [tabJson("orderladder", "Order Ladder")]),
          // The statistics-only view is what this slot has always shown.
          tabsetJson(70, [tabJson("timesales", "Tape & Microstructure", { params: { view: "stats" } })]),
        ]),
        tabsetJson(20, [tabJson("pnlmonitor", "Intraday P&L")]),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 13 — Everything
//
// Every widget in the catalogue, organised into 6 tabbed groups:
//   Charts | Trading | Options   (top row)
//   Analysis | Positions/Risk | Utility   (bottom row)
//
// Use this to explore every widget in a single workspace.
// ---------------------------------------------------------------------------
function buildEverything(): IJsonModel {
  const tabs = (components: readonly string[]) => components.map((c) => tabJson(c, c));
  return workspaceJson(
    rowJson(100, [
      rowJson(100, [
        rowJson(50, [
          tabsetJson(28, [tabJson("chart", "Chart"), ...tabs(["multitimeframe"])]),
          tabsetJson(30, [tabJson("scalper", "Scalper"), ...tabs(["orderpad", "quicktrade", "orderladder"])]),
          tabsetJson(42, [
            tabJson("optionchain", "Option Chain"),
            ...tabs([
              "oichart", "straddle", "straddlepnl", "greeks", "greeksheatmap",
              "ivsmile", "volatilitycone",
            ]),
          ]),
        ]),
        rowJson(50, [
          // Anchored on the DOM heatmap. This slot held `depth` before that
          // widget merged into the ladder; a ladder panel here would open the
          // same widget twice, since the Trading group above already has one.
          tabsetJson(36, [
            tabJson("domheatmap", "DOM Heatmap"),
            ...tabs([
              "gammadensity", "volsurface", "orderflow", "marketoverview", "correlationpairs",
              "correlationmatrix", "instrumentcompare", "pcrtrend", "gapanalysis", "vwapbands",
              "pivotpoints", "timesales",
            ]),
          ]),
          tabsetJson(32, [
            tabJson("indexstrip", "Indices"),
            ...tabs([
              "positions", "orders", "holdings", "fills", "pnlmonitor", "portfolioallocation",
              "riskdashboard", "actioncenter", "strategymonitor", "tradecopier",
            ]),
          ]),
          tabsetJson(32, [
            tabJson("watchlist", "Watchlist"),
            ...tabs([
              "calculator", "news", "ticker", "aiadvisor", "conditionscanner", "alerts",
              "fundingrate", "currencyconverter", "earningscalendar", "marketoverview",
              "strategytemplates", "audittrail", "economiccalendar", "reconciliation",
              "obsidian", "aibackends", "aiteam", "expirycountdown", "marketclock",
              "tradeidea", "tickspeed",
            ]),
          ]),
        ]),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 14 — Options Scalper
//
// The four-chart options-scalping desk: the index drives timing (centre-top),
// its future sits below (centre-bottom), and the CE / PE strike charts flank it
// left and right with the live option chain (OI interpretation) under the PE.
//
// ┌──────────┬──────────────┬──────────────┐
// │          │    Index     │   PE Strike  │
// │ CE Strike├──────────────┼──────────────┤
// │          │   Futures    │ Option Chain │
// └──────────┴──────────────┴──────────────┘
//
// Each chart is pinned to its own instrument via panel params (see ChartWidget
// ChartPanelParams), so the four charts are independent — unlike the other
// presets where every chart tracks one global symbol. They seed to the NIFTY
// index (always a valid symbol) on a 1-minute scalping interval; the trader then
// loads the live future and the ATM CE/PE strikes into the labelled panels.
// ---------------------------------------------------------------------------
function buildOptionsScalper(): IJsonModel {
  const scalpInterval = "1m";
  const index = (symbol: string) => ({
    symbol,
    exchange: "NSE_INDEX",
    interval: scalpInterval,
  });
  return workspaceJson(
    rowJson(100, [
      tabsetJson(28, [tabJson("chart", "CE Strike", { params: index("NIFTY") })]),
      rowJson(44, [
        tabsetJson(50, [tabJson("chart", "Index", { params: index("NIFTY") })]),
        tabsetJson(50, [tabJson("chart", "Futures", { params: index("NIFTY") })]),
      ]),
      rowJson(28, [
        tabsetJson(50, [tabJson("chart", "PE Strike", { params: index("NIFTY") })]),
        tabsetJson(50, [tabJson("optionchain", "Option Chain", { params: { symbol: "NIFTY" } })]),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 15 — Multi Chart
//
// The 2×2 chart grid, expressed as a layout template instead of a widget (it
// replaces the retired `chartgrid` widget). Every cell is a full ChartWidget
// panel — indicators, drawings, OI overlay, quotes, replay and display
// settings all come along, each panel keeps its own indicator/display
// configuration (ChartWidget keys those by panel id), and the whole grid is
// persisted with the workspace layout instead of being lost on reload.
//
// ┌──────────────┬──────────────┐
// │    NIFTY     │  BANKNIFTY   │
// ├──────────────┼──────────────┤
// │   FINNIFTY   │  MIDCPNIFTY  │
// └──────────────┴──────────────┘
//
// The four NSE index defaults mirror the retired widget's default cells. Each
// chart is pinned via panel params so it holds its instrument instead of
// following the global watchlist selection; any cell can be re-pointed from its
// own symbol search, and panels can be closed or dragged for a 1, 2H or 2V
// arrangement through the layout itself.
// ---------------------------------------------------------------------------
function buildMultiChart(): IJsonModel {
  const gridInterval = "5m";
  const cell = (symbol: string) => ({
    symbol,
    exchange: "NSE_INDEX",
    interval: gridInterval,
  });
  return workspaceJson(
    rowJson(100, [
      rowJson(50, [
        tabsetJson(50, [tabJson("chart", "NIFTY", { params: cell("NIFTY") })]),
        tabsetJson(50, [tabJson("chart", "FINNIFTY", { params: cell("FINNIFTY") })]),
      ]),
      rowJson(50, [
        tabsetJson(50, [tabJson("chart", "BANKNIFTY", { params: cell("BANKNIFTY") })]),
        tabsetJson(50, [tabJson("chart", "MIDCPNIFTY", { params: cell("MIDCPNIFTY") })]),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 16 — Trading Desk (the retired Dashboard widget as a composition)
//
// ┌──────────────────────────────┐
// │        Indices strip         │
// ├──────────────┬───────────────┤
// │  Positions   │     Risk      │
// ├──────────────┴───────────────┤
// │           Orders             │
// └──────────────────────────────┘
// ---------------------------------------------------------------------------
function buildTradingDesk(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(100, [
        tabsetJson(20, [tabJson("indexstrip", "Indices")]),
        rowJson(52, [
          tabsetJson(65, [tabJson("positions", "Positions")]),
          tabsetJson(35, [tabJson("riskdashboard", "Risk")]),
        ]),
        tabsetJson(28, [tabJson("orders", "Orders")]),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Preset 17 — Three Panel (CE | Index | PE)
//
// Replaces the retired `threepanel` widget. Three full ChartWidget panels —
// nearest-expiry ATM CE, the underlying index (wider centre), nearest-expiry
// ATM PE — sharing one time-scale sync group, so scroll/zoom in any panel
// moves all three. Each cell keeps the full chart surface (indicators,
// drawings, replay, per-panel settings) and the layout survives reload.
// ---------------------------------------------------------------------------
function buildThreePanel(): IJsonModel {
  const legInterval = "5m"; // ThreePanel's default interval
  const syncGroup = "three-panel";
  return workspaceJson(
    rowJson(100, [
      tabsetJson(28, [
        tabJson("chart", "CE", {
          params: { optionLeg: { underlying: "NIFTY", leg: "CE" }, interval: legInterval, syncGroup },
        }),
      ]),
      tabsetJson(44, [
        tabJson("chart", "Index", {
          params: { symbol: "NIFTY", exchange: "NSE_INDEX", interval: legInterval, syncGroup },
        }),
      ]),
      tabsetJson(28, [
        tabJson("chart", "PE", {
          params: { optionLeg: { underlying: "NIFTY", leg: "PE" }, interval: legInterval, syncGroup },
        }),
      ]),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Beginner core layout (applied for the beginner skill level; not listed in
// the preset picker — TerminalRoute applies it by id "beginner-core")
//
// ┌──────────────────────────────┐
// │        Indices strip         │
// ├──────────────────┬───────────┤
// │      Chart       │ Watchlist │
// │                  ├───────────┤
// ├──────────────────┤ Order Pad │
// │    Positions     │           │
// └──────────────────┴───────────┘
// The strip replaces the retired Dashboard widget (its positions/orders
// tables and funds cards were duplicates of the Positions, Orders and Risk
// widgets; the index cards were the part a beginner layout needs at a glance).
// ---------------------------------------------------------------------------
export function buildBeginnerCore(): IJsonModel {
  return workspaceJson(
    rowJson(100, [
      rowJson(100, [
        tabsetJson(18, [tabJson("indexstrip", "Indices")]),
        rowJson(82, [
          rowJson(75, [
            tabsetJson(70, [tabJson("chart", "Chart")]),
            tabsetJson(30, [tabJson("positions", "Positions")]),
          ]),
          rowJson(25, [
            tabsetJson(50, [tabJson("watchlist", "Watchlist")]),
            tabsetJson(50, [tabJson("orderpad", "Order Pad")]),
          ]),
        ]),
      ]),
    ]),
  );
}

export const WORKSPACE_PRESETS: WorkspacePreset[] = [
  {
    id: "scalper-zone",
    name: "Scalper Zone",
    description: "Chart + Order Pad + DOM / Ladder + Positions + Scalper",
    icon: "Zap",
    build: buildScalperZone,
  },
  {
    id: "options-scalper",
    name: "Options Scalper",
    description: "Four-chart desk — Index + Futures + CE/PE strike charts + Option Chain",
    icon: "Crosshair",
    build: buildOptionsScalper,
  },
  {
    id: "multi-chart",
    name: "Multi Chart",
    description: "Four independent charts in a 2×2 grid — NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY",
    icon: "LayoutGrid",
    build: buildMultiChart,
  },
  {
    id: "options-desk",
    name: "Options Desk",
    description: "Option Chain + Chart + Greeks + Positions + Straddle",
    icon: "Grid3x3",
    build: buildOptionsDesk,
  },
  {
    id: "market-watch",
    name: "Market Watch",
    description: "Watchlist + Chart + Ticker + Dashboard",
    icon: "Star",
    build: buildMarketWatch,
  },
  {
    id: "analysis",
    name: "Analysis",
    description: "Chart + OI Analytics + DOM / Ladder + Positions + News",
    icon: "BarChart3",
    build: buildAnalysis,
  },
  {
    id: "risk-monitor",
    name: "Risk Monitor",
    description: "Dashboard + Risk + MTM Monitor + Positions + Orders",
    icon: "ShieldAlert",
    build: buildRiskMonitor,
  },
  {
    id: "investor-view",
    name: "Investor View",
    description: "Chart + Watchlist + Holdings + Indices",
    icon: "TrendingUp",
    build: buildInvestorView,
  },
  {
    id: "trading-desk",
    name: "Trading Desk",
    description: "Indices + Positions + Risk + Orders — the retired Dashboard as a composition",
    icon: "LayoutDashboard",
    build: buildTradingDesk,
  },
  {
    id: "three-panel",
    name: "Three Panel",
    description: "CE | Index | PE — three time-synchronised charts on the nearest-expiry ATM strikes",
    icon: "Columns3",
    build: buildThreePanel,
  },
  {
    id: "options-analysis",
    name: "Options Analysis",
    description: "Option Chain + IV Smile & Skew + Greeks Matrix + Straddle & Implied Move + Straddle P&L",
    icon: "Sigma",
    build: buildOptionsAnalysis,
  },
  {
    id: "sector-view",
    name: "Sector View",
    description: "Market Overview + Heat Calendar + Correlation Matrix",
    icon: "Map",
    build: buildSectorView,
  },
  {
    id: "order-automation",
    name: "Order Automation",
    description: "Strategy Monitor + Chart + Strategy Templates + Session Stats",
    icon: "Bot",
    build: buildOrderAutomation,
  },
  {
    id: "portfolio-manager",
    name: "Portfolio Manager",
    description: "Portfolio Allocation + Positions (net and heat-map views) + Risk + Trade Performance",
    icon: "PieChart",
    build: buildPortfolioManager,
  },
  {
    id: "market-overview",
    name: "Market Overview",
    description: "Market Summary + Global Indices + Economic Calendar + Earnings Calendar + Market Clock + News",
    icon: "Globe",
    build: buildMarketOverview,
  },
  {
    id: "quick-scalper",
    name: "Quick Scalper",
    description: "Quick Trade + Order Ladder + DOM Heatmap + Tape & Microstructure + Tick Speed + Intraday P&L",
    icon: "Gauge",
    build: buildQuickScalper,
  },
  {
    id: "everything",
    name: "Everything",
    description: "A broad sweep of the widget catalogue in one workspace — Charts, Trading, Options, Analysis, Positions, Utility",
    icon: "LayoutDashboard",
    build: buildEverything,
  },
];

// ---------------------------------------------------------------------------
// applyPreset — replace the canvas model with a preset by id
// ---------------------------------------------------------------------------

/**
 * Build the model document for a preset id, or undefined for an unknown id.
 * `"beginner-core"` resolves to the unlisted beginner layout.
 */
export function buildPresetJsonById(presetId: string): IJsonModel | undefined {
  if (presetId === "beginner-core") return buildBeginnerCore();
  return WORKSPACE_PRESETS.find((p) => p.id === presetId)?.build();
}

export function applyPreset(api: WorkspaceApi, presetId: string): void {
  const json = buildPresetJsonById(presetId);
  if (!json) {
    console.warn(`[workspacePresets] Unknown preset id: "${presetId}"`);
    return;
  }
  api.loadModelJson(json);
}

// Convenience export: the default startup preset id
export const DEFAULT_PRESET_ID = "market-watch";

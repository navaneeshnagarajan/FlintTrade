import { lazy, Suspense, Component, useCallback } from "react";
import type { ReactNode, ErrorInfo } from "react";
import type { TabNode } from "flexlayout-react";
import { Button } from "@/components/ui/button";
import type { WidgetMeta, WidgetProps } from "@/types/widgets";
import { widgetPropsForNode } from "@/layout/flexLayoutAdapter";

// ---------------------------------------------------------------------------
// Lazy-load all widgets -- each is a separate chunk for code splitting
// ---------------------------------------------------------------------------
const lazyWidgets = {
  // Trading widgets
  scalper: lazy(() => import("@/widgets/trading/Scalper/ScalperWidget")),
  positions: lazy(() => import("@/widgets/trading/Positions/PositionsWidget")),
  fills: lazy(() => import("@/widgets/trading/Fills/FillsWidget")),
  pnlmonitor: lazy(() => import("@/widgets/trading/PnLMonitor/PnLMonitorWidget")),
  orders: lazy(() => import("@/widgets/trading/Orders/OrdersWidget")),
  holdings: lazy(() => import("@/widgets/trading/Holdings/HoldingsWidget")),
  orderpad: lazy(() => import("@/widgets/trading/OrderPad/OrderPadWidget")),
  foreverorders: lazy(() => import("@/widgets/orders/ForeverOrdersWidget")),
  superorders: lazy(() => import("@/widgets/orders/SuperOrdersWidget")),
  conditionaltriggers: lazy(() => import("@/widgets/orders/ConditionalTriggersWidget")),
  reconciliation: lazy(() => import("@/widgets/account/ReconciliationWidget")),

  // Analysis widgets
  chart: lazy(() => import("@/widgets/analysis/Chart/ChartWidget")),
  marketoverview: lazy(() => import("@/widgets/analysis/MarketOverview/MarketOverviewWidget")),
  optionchain: lazy(() => import("@/widgets/analysis/OptionChain/OptionChainWidget")),
  oichart: lazy(() => import("@/widgets/analysis/OIChart/OIChartWidget")),
  straddle: lazy(() => import("@/widgets/analysis/Straddle/StraddleWidget")),
  greeks: lazy(() => import("@/widgets/analysis/Greeks/GreeksWidget")),

  // Utility widgets
  watchlist: lazy(() => import("@/widgets/utility/Watchlist/WatchlistWidget")),
  indexstrip: lazy(() => import("@/widgets/utility/IndexStrip/IndexStripWidget")),
  calculator: lazy(() => import("@/widgets/utility/Calculator/CalculatorWidget")),
  news: lazy(() => import("@/widgets/utility/News/NewsWidget")),
  ticker: lazy(() => import("@/widgets/utility/Ticker/TickerWidget")),
  aiadvisor: lazy(() => import("@/widgets/utility/AIAdvisor/AIAdvisorWidget")),
  aibackends: lazy(() => import("@/widgets/utility/AIBackends/AIBackendsWidget")),
  aiteam: lazy(() => import("@/widgets/utility/AITeam/AITeamWidget")),
  obsidian: lazy(() => import("@/widgets/utility/Obsidian/ObsidianWidget")),

  // New trading widgets
  actioncenter: lazy(() => import("@/widgets/trading/ActionCenter/ActionCenterWidget")),

  // New analysis widgets
  gammadensity: lazy(() => import("@/widgets/analysis/GammaDensity/GammaDensityWidget")),
  arbitragescanner: lazy(() => import("@/widgets/analysis/ArbitrageScanner/ArbitrageScannerWidget")),
  patterndetection: lazy(() => import("@/widgets/analysis/PatternDetection/PatternDetectionWidget")),
  timesales: lazy(() => import("@/widgets/analysis/TimeSales/TimeSalesWidget")),
  volsurface: lazy(() => import("@/widgets/analysis/VolSurface/VolSurfaceWidget")),
  ivsmile: lazy(() => import("@/widgets/analysis/IVSmile/IVSmileWidget")),
  straddlepnl: lazy(() => import("@/widgets/analysis/StraddlePnL/StraddlePnLWidget")),
  orderflow: lazy(() => import("@/widgets/analysis/OrderFlow/OrderFlowWidget")),

  // Utility widgets (new)
  alerts: lazy(() => import("@/widgets/utility/Alerts/AlertsWidget")),

  // Analysis widgets (new)

  // OI Heatmap

  // OI Signals (OI-action classification + unusual OI)

  // Portfolio Optimiser (mean-variance weights)
  portfoliooptimiser: lazy(() => import("@/widgets/analysis/PortfolioOptimiser/PortfolioOptimiserWidget")),

  // Condition Scanner (declarative prebuilt scans over /v1/scanner)
  conditionscanner: lazy(() => import("@/widgets/analysis/ConditionScanner/ConditionScannerWidget")),

  // Trade Copier (Ditto route)
  tradecopier: lazy(() => import("@/widgets/trading/TradeCopier/TradeCopierWidget")),

  // Smart Order (liquidity-aware slicing through the gated path)
  smartorder: lazy(() => import("@/widgets/trading/SmartOrder/SmartOrderWidget")),

  // Analysis widgets (Wave 24)

  // Utility widgets (Wave 24)
  fundingrate: lazy(() => import("@/widgets/utility/FundingRate/FundingRateWidget")),

  // Utility widgets (Wave 25)
  currencyconverter: lazy(() => import("@/widgets/utility/CurrencyConverter/CurrencyConverterWidget")),
  earningscalendar: lazy(() => import("@/widgets/utility/EarningsCalendar/EarningsCalendarWidget")),
  strategytemplates: lazy(() => import("@/widgets/utility/StrategyTemplates/StrategyTemplatesWidget")),
  audittrail: lazy(() => import("@/widgets/utility/AuditTrail/AuditTrailWidget")),

  // Wave 26 widgets
  pivotpoints: lazy(() => import("@/widgets/analysis/PivotPoints/PivotPointsWidget")),
  economiccalendar: lazy(() => import("@/widgets/utility/EconomicCalendar/EconomicCalendarWidget")),
  portfolioallocation: lazy(() => import("@/widgets/trading/PortfolioAllocation/PortfolioAllocationWidget")),

  // Wave 27 widgets
  quicktrade: lazy(() => import("@/widgets/trading/QuickTrade/QuickTradeWidget")),
  volatilitycone: lazy(() => import("@/widgets/analysis/VolatilityCone/VolatilityConeWidget")),

  // Wave 28 widgets
  vwapbands: lazy(() => import("@/widgets/analysis/VWAPBands/VWAPBandsWidget")),
  correlationpairs: lazy(() => import("@/widgets/analysis/CorrelationPairs/CorrelationPairsWidget")),
  multitimeframe: lazy(() => import("@/widgets/analysis/MultiTimeframe/MultiTimeframeWidget")),

  // Wave 29 widgets
  pcrtrend: lazy(() => import("@/widgets/analysis/PCRTrend/PCRTrendWidget")),
  instrumentcompare: lazy(() => import("@/widgets/analysis/InstrumentCompare/InstrumentCompareWidget")),

  // Wave 30 widgets
  greeksheatmap: lazy(() => import("@/widgets/analysis/GreeksHeatmap/GreeksHeatmapWidget")),
  gapanalysis: lazy(() => import("@/widgets/analysis/GapAnalysis/GapAnalysisWidget")),

  // Wave 31 widgets
  riskdashboard: lazy(() => import("@/widgets/trading/RiskDashboard/RiskDashboardWidget")),

  // Wave 32 widgets
  expirycountdown: lazy(() => import("@/widgets/utility/ExpiryCountdown/ExpiryCountdownWidget")),
  correlationmatrix: lazy(() => import("@/widgets/analysis/CorrelationMatrix/CorrelationMatrixWidget")),
  deliverydata: lazy(() => import("@/widgets/analysis/DeliveryData/DeliveryDataWidget")),

  // Wave 33 widgets
  marketclock: lazy(() => import("@/widgets/utility/MarketClock/MarketClockWidget")),
  strategymonitor: lazy(() => import("@/widgets/trading/StrategyMonitor/StrategyMonitorWidget")),

  // Wave 34 widgets
  tradeidea: lazy(() => import("@/widgets/utility/TradeIdea/TradeIdeaWidget")),
  tickspeed: lazy(() => import("@/widgets/utility/TickSpeed/TickSpeedWidget")),
  orderladder: lazy(() => import("@/widgets/trading/OrderLadder/OrderLadderWidget")),

  // Wave 35 — order flow visualisation
  domheatmap: lazy(() => import("@/widgets/analysis/DOMHeatmap/DOMHeatmapWidget")),

  // Wave 36 — historical option-chain archive
  historicalchain: lazy(() => import("@/widgets/analysis/HistoricalChain/HistoricalChainWidget")),

  // FINOS migration Phase 3 — Perspective analytics
  portfoliopivot: lazy(() => import("@/widgets/analysis/PortfolioPivot/PortfolioPivotWidget")),

  // Indicator restoration wave — seasonality patterns
  seasonality: lazy(() => import("@/widgets/analysis/Seasonality/SeasonalityWidget")),

  // Annotated trade journal (SQLite + FTS5 store)
  tradejournal: lazy(() => import("@/widgets/utility/TradeJournal/TradeJournalWidget")),
};

// ---------------------------------------------------------------------------
// Retired widget ids
// ---------------------------------------------------------------------------

/**
 * Widgets that have been merged into a canonical surface.
 *
 * A retired id is REMOVED from {@link widgetCatalog} — it no longer appears in
 * the picker — but MUST stay resolvable in {@link widgetComponents}: the
 * FlexLayout factory looks a saved tab's `component` string up in that map
 * alone, and an id that stopped resolving degrades that panel to an error
 * card, silently costing the operator the view they saved. (Under the old
 * Dockview host an unresolved id wiped the ENTIRE saved tab; FlexLayout
 * degrades one panel, but the contract stays: retired ids keep resolving.)
 *
 * Each entry names the canonical widget and the panel params that reproduce
 * the retired widget's presentation, so an operator who saved a layout
 * containing the old panel gets the same view back under the new widget.
 */
export interface RetiredMergedWidget {
  /** The canonical widget's component id. */
  readonly component: string;
  /** Params that reproduce the retired widget's view on the canonical one. */
  readonly params?: Readonly<Record<string, unknown>>;
  /** Why it was retired — shown to nobody, read by the next maintainer. */
  readonly note: string;
}

/**
 * A widget whose capability dissolved into a tool or route rather than
 * another widget. A saved panel cannot render the destination (tools are
 * overlays, Settings is a route), so it renders a small pointer instead —
 * still a resolvable component, so the saved tab survives (Dockview wipes the
 * whole tab when any one panel fails to resolve).
 */
export interface RetiredMovedWidget {
  readonly movedTo: {
    /** Human-readable destination, e.g. "Settings → Monitoring". */
    readonly destination: string;
    /** Router path when the destination is routable (Settings sections). */
    readonly route?: string;
  };
  /** Why it was retired — shown to nobody, read by the next maintainer. */
  readonly note: string;
}

export type RetiredWidget = RetiredMergedWidget | RetiredMovedWidget;

/** Narrowing helper shared with the guard tests. */
export function isMovedWidget(spec: RetiredWidget): spec is RetiredMovedWidget {
  return "movedTo" in spec;
}

export const RETIRED_WIDGET_IDS: Readonly<Record<string, RetiredWidget>> = {
  sessionstats: {
    movedTo: { destination: "Trade Review (Tools menu)" },
    note:
      "Session statistics now live in the Trade Review tool's Session tab: "
      + "same FIFO round-trip metrics via lib/pnl, same "
      + "disclosed-sample-until-a-trip-closes provenance.",
  },
  tradeperformance: {
    movedTo: { destination: "Trade Review (Tools menu)" },
    note:
      "Performance metrics now live in the Trade Review tool's Performance "
      + "tab with a Range/YTD scope toggle, routed through "
      + "lib/journalAnalytics — which fixed an equity curve running backwards "
      + "(the journal returns newest-first and this widget summed in array "
      + "order), a YTD end date computed in UTC that excluded the current "
      + "session every IST early morning, and a profit factor fabricated as "
      + "99 when there were no losses.",
  },
  heatcalendar: {
    movedTo: { destination: "Trade Review (Tools menu)" },
    note:
      "The daily heat-calendar rendering (month navigation, tooltip, legend) "
      + "survives in the Trade Review tool's Calendar tab over REAL "
      + "journalled rupee P&L; the widget's sample-only percentage data plane "
      + "retires as strictly dominated.",
  },
  dashboard: {
    component: "indexstrip",
    note:
      "Dissolved into composition (ruling D5, 2026-07-26). It imported zero "
      + "widgets and reimplemented four surfaces the terminal already had: "
      + "the live index cards (now the Index Strip widget), a positions "
      + "table (its P&L% column and FlintSegmentTracker status strip moved "
      + "into Positions, recomputed from the kernel's mtm/pnlPercent rather "
      + "than the raw broker fields), an orders table (Orders) and "
      + "funds/margin cards (Risk). A saved panel reopens as the Index Strip "
      + "— the only part of it nothing else carried; the Trading Desk preset "
      + "gives back the full at-a-glance composition.",
  },
  threepanel: {
    movedTo: { destination: "Workspace presets → Three Panel" },
    note:
      "Demoted to the Three Panel workspace preset (dedup 3.3). Its cells "
      + "were stripped chart clones (no indicators, drawings, replay or "
      + "persistence); the preset composes three full ChartWidget panels "
      + "whose time scales sync via lib/chartSyncBus and whose CE/PE cells "
      + "resolve nearest-expiry ATM legs via lib/optionLegSymbols — the "
      + "resolution logic extracted from this widget. A single saved panel "
      + "cannot render a three-panel layout, so it points at the preset.",
  },
  marketbreadth: {
    component: "marketoverview",
    params: { tab: "breadth" },
    note:
      "Merged into Market Overview. Its zod-validated /breadth fetches and "
      + "fail-closed provenance became the Breadth tab verbatim.",
  },
  sectormap: {
    component: "marketoverview",
    params: { tab: "sectors" },
    note:
      "Merged into Market Overview. Treemap/grid/table over positions became "
      + "the Sectors tab (default treemap), keeping the metric-labelling fix "
      + "— live colours are unrealised P&L% vs entry, not day change. Its RRG "
      + "and Portfolio modes moved to the Rotation tab (same localStorage "
      + "key, saved symbol lists survive).",
  },
  sectorperformance: {
    component: "marketoverview",
    params: { tab: "sectors", view: "bars" },
    note:
      "Merged into Market Overview as the Sectors bars view. It is wired to "
      + "the sectors/rotation endpoint, but that route is still a backend "
      + "stub, so the bars remain honestly badged sample; its own sample "
      + "table collapsed into the widget's single sample sector dataset.",
  },
  globalindices: {
    component: "marketoverview",
    params: { tab: "indices" },
    note:
      "Merged into Market Overview. The table, its honest empty/error/retry "
      + "states and the response-flag-keyed badge carried over unchanged into "
      + "the Indices tab.",
  },
  fiilongshort: {
    component: "marketoverview",
    params: { tab: "flows" },
    note:
      "Merged into Market Overview. Futures-bias gauge + FII segment table "
      + "became the Flows tab, joined by the 10-day FII/DII cash table and "
      + "DII derivative rows via the same getFiiDiiData call.",
  },
  marketsummary: {
    component: "marketoverview",
    params: { tab: "breadth" },
    note:
      "Split by section into Market Overview: breadth + Top Movers → Breadth; "
      + "live index tick cards → Indices (awaiting-tick honesty preserved); "
      + "sector bars → Sectors bars view; FII/DII net → Flows. Opens on "
      + "Breadth, the closest match to its at-a-glance identity.",
  },
  indexcontribution: {
    component: "marketoverview",
    params: { tab: "contribution" },
    note:
      "Merged into Market Overview per ruling D9 as the Contribution tab — "
      + "selector, diverging contribution bars, weights-as-of disclosure and "
      + "fail-closed demo affordance unchanged.",
  },
  tradebook: {
    component: "fills",
    note:
      "Merged into Fills. Its TanStack table engine, permissive raw-tradebook "
      + "parsing, value column, side pills, refresh/clock and honest "
      + "error/empty states survive unchanged; Fills adds the journal "
      + "enrichment it never had.",
  },
  tradelog: {
    component: "fills",
    note:
      "Merged into Fills. CSV export, symbol search and the stats footer "
      + "carry over. Dropped: the Type/Status/fill-time columns (never "
      + "populated by real data — the journal records fills, not orders) and "
      + "the computeStats /2 halving (the sample fixture now puts P&L on the "
      + "closing leg only, so totals are a direct sum).",
  },
  intradaypnl: {
    component: "pnlmonitor",
    params: { view: "live" },
    note:
      "Merged into P&L Monitor. Its realised/unrealised split, tradebook "
      + "partial-close booking and peak/drawdown maths are the canonical "
      + "figures (every semantic pin survives); its baseline sparkline gave "
      + "way to the MTM chart, which now plots the same corrected series.",
  },
  mtmmonitor: {
    component: "pnlmonitor",
    params: { view: "live" },
    note:
      "Merged into P&L Monitor. Contributed the Lightweight Charts curve, "
      + "target/SL price lines, staleness chip and error banner + retry; its "
      + "raw totalPositionMtm plot (blind to booked partial-close realised) "
      + "and its peak>0 drawdown guard (zero drawdown for a book that fell "
      + "straight underwater) were both corrected to the IntradayPnL maths.",
  },
  optionsflow: {
    component: "oichart",
    params: { view: "signals" },
    note:
      "Folded into OI Analytics' Signals view (ruling D1, 2026-07-26). It had "
      + "no data source at all — an unconditional hardcoded sample — and its "
      + "unusual-OI third was already dominated by the signals view's real "
      + "/v1/oi/unusual feed. The sweep/block tape presentation survives as "
      + "the collapsed, sample-labelled FlowTape section there.",
  },
  health: {
    movedTo: { destination: "Settings → Monitoring", route: "/settings#monitoring" },
    note:
      "Retired into Settings (ruling D6, 2026-07-26). Every one of its data "
      + "sources — backend health, traffic, latency, security stats, "
      + "connection state — was already rendered by Settings' Monitoring and "
      + "Security sections and the status bar; the widget was a duplicate "
      + "readout. Saved panels show a pointer rather than a fourth copy.",
  },
  gex: {
    component: "gammadensity",
    params: { view: "exposure" },
    note:
      "Merged into Dealer Gamma. The gammadensity backend endpoint reuses the "
      + "very option-chain snapshot the GEX endpoint builds, so the two were "
      + "one data plane behind two widgets. GEX's call/put decomposition and "
      + "signed Net GEX area are now the 'exposure' view; its gamma-flip "
      + "annotation is dropped because the server returns that field as null "
      + "unconditionally.",
  },
  depthheatmap: {
    component: "domheatmap",
    // Its identity was the gamma power-scale look, not a distinct view.
    params: { scale: "gamma" },
    note:
      "Merged into DOM Heatmap. Same visual, byte-identical colour ramps, same "
      + "layered-canvas architecture and the same Flame icon — the only real "
      + "difference was that this one was entirely synthetic. Its deterministic "
      + "generator survives as the labelled demo provider.",
  },
  orderbookreplay: {
    component: "domheatmap",
    params: { view: "replay" },
    note:
      "Merged into DOM Heatmap as its 'replay' view. It owned a good transport "
      + "and scrubber but played over a Math.random() sample; DOM Heatmap "
      + "already kept a real 60-snapshot ring buffer, which is what a scrubber "
      + "wants.",
  },
  ivskew: {
    component: "ivsmile",
    params: { view: "skew" },
    note:
      "Merged into IV Smile & Skew. Both read the same getFtIVSmile payload "
      + "with the same palette, symbols, axis toggle and ATM/25-delta metrics; "
      + "only the projection differed. IV Skew's four-state fail-closed "
      + "provenance badge and its percent-vs-decimal normalisation became the "
      + "canonical behaviour, because they were the stricter of the two.",
  },
  greekssurface: {
    component: "greeksheatmap",
    // The retired widget opened on IV; the merged default is delta, so a
    // saved panel needs the metric too or it reopens showing something else.
    params: { projection: "surface", metric: "iv" },
    note:
      "Merged into Greeks Matrix. One dataset under two projections — both "
      + "derived greeks from the same getFtIVSmile payload with what were "
      + "character-identical formulas. The 3-D bar projection is now a "
      + "projection setting rather than a separate widget.",
  },
  microstructure: {
    component: "timesales",
    params: { view: "stats" },
    note:
      "Merged into Tape and Microstructure. Every number it displayed came "
      + "from Math.random(); its statistics are exactly what the neighbouring "
      + "widget's REAL tick prints already support, so the merge makes them "
      + "real rather than preserving a fabricated surface.",
  },
  chartgrid: {
    component: "chart",
    note:
      "Demoted to the Multi Chart workspace preset. A grid of N charts is a "
      + "LAYOUT, not a widget: its cell was a stripped clone of the chart "
      + "widget that dropped indicators, drawings, the OI overlay and — "
      + "critically — persistence, while a preset-composed layout survives "
      + "reload. A saved grid panel reopens as one full chart; the preset "
      + "gives back the grid.",
  },
  spreadview: {
    component: "optionchain",
    note:
      "Demoted to template data. It was four hardcoded two-leg spreads with "
      + "hand-typed premiums, no data source and a permanently disabled "
      + "execute button — every one expressible as a two-row entry in the "
      + "options builder, which now also carries the economic validator that "
      + "was the only thing this surface uniquely owned. A saved panel "
      + "reopens on the option chain, where those spreads can be built for "
      + "real.",
  },
  scanner: {
    component: "conditionscanner",
    params: { view: "scans", scan: "pre_market_movers" },
    note:
      "Merged into Condition Scanner. Same client function, same endpoint, "
      + "same row type — it simply hardcoded two of the backend's eight "
      + "prebuilt scan keys into a tab enum while the canonical fetches the "
      + "whole catalogue. Its unusual-OI tab did not come across: that "
      + "endpoint already lives in OI Analytics, which this widget links to.",
  },
  positionsizing: {
    component: "calculator",
    params: { tab: "sizing" },
    note:
      "Merged into Calculator. Its fixed-fractional sizing was algebraically "
      + "identical to Profit Target's and to the Calculator's own risk tab.",
  },
  profittarget: {
    component: "calculator",
    params: { tab: "target" },
    note:
      "Merged into Calculator. Same shared sizing kernel; its reward-side "
      + "analysis becomes the Target tab.",
  },
  netposition: {
    component: "positions",
    params: { view: "net" },
    note:
      "Merged into Positions. All three position renderings read the same "
      + "cache, so they were one book behind three widgets. Its grouping "
      + "function also split on whitespace, making it a no-op on every real "
      + "broker symbol.",
  },
  positionheatmap: {
    component: "positions",
    params: { view: "heat" },
    note:
      "Merged into Positions as the heat-map view. Its P&L percentage "
      + "recompute guarded only the entry price, so any row with a zero LTP "
      + "was painted a fabricated -100%.",
  },
  oiprofile: {
    component: "oichart",
    params: { view: "butterfly" },
    note: "Merged into OI Analytics. All four answered the same question — where open interest sits across strikes. OI Chart and OI Heatmap hit the identical endpoints while independently duplicating the ATM-window, max-OI and PCR maths with different window sizes AND different change sources, so two widgets on one screen could disagree about the same strike.",
  },
  oiheatmap: {
    component: "oichart",
    params: { view: "heat" },
    note: "Merged into OI Analytics. All four answered the same question — where open interest sits across strikes. OI Chart and OI Heatmap hit the identical endpoints while independently duplicating the ATM-window, max-OI and PCR maths with different window sizes AND different change sources, so two widgets on one screen could disagree about the same strike.",
  },
  oisignals: {
    component: "oichart",
    params: { view: "signals" },
    note: "Merged into OI Analytics. All four answered the same question — where open interest sits across strikes. OI Chart and OI Heatmap hit the identical endpoints while independently duplicating the ATM-window, max-OI and PCR maths with different window sizes AND different change sources, so two widgets on one screen could disagree about the same strike.",
  },
  depth: {
    component: "orderladder",
    // At the NSE tick each broker level lands on its own row, which is what
    // the retired 5-level depth table looked like.
    params: { symbol: "NIFTY", exchange: "NSE", tick: 0.05 },
    note:
      "Merged into DOM / Ladder. These were a broken split, not duplicates: "
      + "Depth held the real level-2 book and could not trade, while the "
      + "ladder could trade but had no depth feed at all and rendered zero "
      + "resting size in live mode.",
  },
  riskpanel: {
    component: "riskdashboard",
    note:
      "Merged into Risk. The two shared exactly one metric — margin "
      + "utilisation, computed identically but banded 80/95 here and 70/90 "
      + "there, so an operator with both open saw one account at two risk "
      + "levels. No params: the merged widget has no view modes.",
  },
  impliedmove: {
    component: "straddle",
    params: { view: "impliedmove" },
    note:
      "Merged into Straddle & Implied Move. It needed only spot, ATM strike "
      + "and the two ATM premiums — all of which the straddle widget already "
      + "computed live. Being static was never a data problem. The merge also "
      + "deletes a silent mislabel where three of its five symbols showed "
      + "another index's numbers.",
  },
  footprint: {
    component: "orderflow",
    params: { view: "footprint+delta" },
    note:
      "Merged into Order Flow. The two widgets were ~90% identical — same "
      + "useOrderFlow call, same symbols and intervals, a copy-pasted "
      + "formatIntervalLabel and a near byte-identical DPR effect. Footprint's "
      + "per-cell delta text and cumulative-delta strip are now the "
      + "'footprint+delta' view mode.",
  },
};

// ---------------------------------------------------------------------------
// Widget metadata for the picker popup
// ---------------------------------------------------------------------------
export const widgetCatalog: WidgetMeta[] = [
  // Trading
  { id: "scalper", name: "Scalper", icon: "Zap", category: "Trading", description: "One-click order entry panel optimised for intraday F&O scalping" , surface: "trade", availability: "live-or-sample"},
  { id: "positions", name: "Positions", icon: "Table2", category: "Trading", description: "The open position book of the selected account in three views — a sortable table with square-off, convert and exit-all, a net view that groups legs by underlying, and a P&L heat map — all from one broker read, so the three cannot disagree" , surface: "shared", availability: "live-or-sample"},
  { id: "fills", name: "Fills", icon: "ArrowRightLeft", category: "Trading", description: "Executed fills for the session — broker tradebook joined with journal entry/exit, realised P&L, fees and screenshots; filter, sort and CSV export" , surface: "trade", availability: "live-or-sample"},
  { id: "pnlmonitor", name: "P&L Monitor", icon: "TrendingUp", category: "Trading", description: "Day P&L with realised/unrealised split, MTM chart with target and stop-loss lines, and summary and drawdown views from positions, tradebook and funds" , surface: "trade", availability: "live-or-sample"},
  { id: "orders", name: "Orders", icon: "ClipboardList", category: "Trading", description: "Order book showing pending, executed, and rejected orders" , surface: "shared", availability: "live-or-sample"},
  { id: "holdings", name: "Holdings", icon: "Wallet", category: "Trading", description: "Long-term equity and mutual fund holdings with current value" , surface: "shared", availability: "live-or-sample"},
  { id: "orderpad", name: "Order Pad", icon: "FileEdit", category: "Trading", description: "Full-featured order entry form with limit, market, and bracket orders" , surface: "trade", availability: "live-or-sample"},
  { id: "actioncenter", name: "Action Centre", icon: "ShieldCheck", category: "Trading", description: "Approval queue for orders the safety system has held back — review each pending intent and approve or reject it before it reaches a broker" , surface: "trade", availability: "live-only"},
  { id: "tradecopier", name: "Trade Copier", icon: "Copy", category: "Trading", description: "Mirror trades across multiple accounts with configurable lot multipliers" , surface: "trade", availability: "live-only"},
  { id: "smartorder", name: "Smart Order", icon: "GitFork", category: "Trading", description: "Liquidity-aware order slicing (market / depth chunks / TWAP) — every child order passes the full safety gate" , surface: "trade", availability: "live-only"},
  { id: "portfolioallocation", name: "Portfolio Allocation", icon: "PieChart", category: "Trading", description: "Pie chart breakdown of portfolio allocation by sector and instrument" , surface: "trade", availability: "live-or-sample"},
  { id: "quicktrade", name: "Quick Trade", icon: "Zap", category: "Trading", description: "Minimal order ticket for fast order placement without leaving the chart" , surface: "trade", availability: "live-or-sample"},
  { id: "riskdashboard", name: "Risk", icon: "ShieldAlert", category: "Trading", description: "Margin utilisation gauge with exposure, open positions and available cash, plus daily MTM against your local target and stop-loss references" , surface: "trade", availability: "live-or-sample"},
  { id: "strategymonitor", name: "Strategy Monitor", icon: "Activity", category: "Trading", description: "Live status of all running automated strategies with PnL per strategy" , surface: "trade", availability: "live-or-sample"},
  { id: "orderladder", name: "DOM / Ladder", icon: "ArrowUpDown", category: "Trading", description: "Level-2 book and order ladder in one surface — real resting bid/ask sizes and order counts on the rows you click to place and cancel limit orders through the safety gate", surface: "trade", availability: "live-or-sample" },
  { id: "foreverorders", name: "Forever (GTT) Orders", icon: "Clock", category: "Trading", description: "Place and manage forever/GTT orders incl. OCO legs and validity — native brokers only" , surface: "trade", availability: "live-only"},
  { id: "superorders", name: "Super Orders", icon: "Target", category: "Trading", description: "Bracket-style super orders with leg-aware modify and cancel — native brokers only" , surface: "trade", availability: "live-only"},
  { id: "conditionaltriggers", name: "Conditional Triggers", icon: "Zap", category: "Trading", description: "Condition-based trigger orders: place, modify and cancel market-condition alerts that fire orders" , surface: "trade", availability: "live-only"},

  // Analysis
  { id: "chart", name: "Chart", icon: "CandlestickChart", category: "Analysis", description: "Interactive candlestick chart with indicators, drawing tools, and replay" , surface: "trade", availability: "live-or-sample"},
  { id: "marketoverview", name: "Market Overview", icon: "LayoutGrid", category: "Analysis", description: "Market breadth, sector performance and rotation (RRG), FII/DII flows, live NSE and global indices, and index contribution by constituent weight — one tabbed surface with per-section Live/Sample provenance", surface: "shared", availability: "live-or-sample" },
  { id: "optionchain", name: "Option Chain", icon: "Grid3x3", category: "Analysis", description: "Live option chain with strike-level OI, volume, IV, and Greek data" , surface: "trade", availability: "live-or-sample"},
  { id: "historicalchain", name: "Historical Chain", icon: "Archive", category: "Analysis", description: "Browse archived (expired) option chains — strike-level OI, volume, LTP, and IV per past expiry" , surface: "trade", availability: "live-or-sample"},
  { id: "oichart", name: "OI Analytics", icon: "BarChart3", category: "Analysis", description: "Open interest across strikes for an expiry — grouped bars, a CE/PE butterfly profile, a strike heat grid, or per-strike build-up and unwinding signals, all from one chain read" , surface: "trade", availability: "live-or-sample"},
  { id: "straddle", name: "Straddle & Implied Move", icon: "Activity", category: "Analysis", description: "Live ATM straddle price with spot and synthetic-future overlays, plus the implied-move range (±1σ ≈ 68%, ±2σ ≈ 95%) derived from the same chain" , surface: "trade", availability: "live-or-sample"},
  { id: "greeks", name: "Greeks", icon: "Sigma", category: "Analysis", description: "Position-level Delta, Gamma, Theta, and Vega summary" , surface: "trade", availability: "live-or-sample"},
  { id: "gammadensity", name: "Dealer Gamma", icon: "BarChart2", category: "Analysis", description: "Dealer gamma from one option-chain snapshot, in two views: gamma-weighted open interest by strike at intraday and to-expiry horizons with the ±1σ convexity zone, or call/put gamma-exposure bars with signed net exposure and the dealer long/short-gamma zone" , surface: "trade", availability: "live-or-sample"},
  { id: "arbitragescanner", name: "Arbitrage Scanner", icon: "ArrowLeftRight", category: "Analysis", description: "Cash-future basis dislocations vs cost-of-carry plus cross-exchange (NSE/BSE) price gaps, ranked by annualised edge" , surface: "trade", availability: "live-or-sample"},
  { id: "patterndetection", name: "Pattern Detection", icon: "CandlestickChart", category: "Analysis", description: "Detects the six candlestick patterns FlintTrade backtests (doji, hammer, engulfing, morning/evening star, three soldiers) on a symbol's recent bars" , surface: "trade", availability: "live-or-sample"},
  { id: "timesales", name: "Tape & Microstructure", icon: "ClipboardList", category: "Analysis", description: "Streaming tape of trade prints inferred from live quote ticks (tick-rule side, volume-delta size), with tick velocity, aggressor ratio and large-order statistics computed from those prints" , surface: "trade", availability: "live-or-sample"},
  { id: "volsurface", name: "Vol Surface", icon: "Box", category: "Analysis", description: "3-D implied volatility surface across strikes and expiries", surface: "trade", availability: "live-or-sample" },
  { id: "ivsmile", name: "IV Smile & Skew", icon: "TrendingUp", category: "Analysis", description: "Implied volatility across strikes for the nearest expiries, as the call/put smile curves or the 25-delta put-minus-call skew" , surface: "trade", availability: "live-or-sample"},
  { id: "straddlepnl", name: "Straddle P&L", icon: "ArrowLeftRight", category: "Analysis", description: "Payoff diagram for straddle positions with breakeven markers" , surface: "trade", availability: "live-or-sample"},
  { id: "orderflow", name: "Order Flow", icon: "BarChart2", category: "Analysis", description: "Real-time buy/sell order flow footprint for active F&O contracts" , surface: "trade", availability: "live-or-sample"},
  { id: "portfoliooptimiser", name: "Portfolio Optimiser", icon: "PieChart", category: "Analysis", description: "Mean-variance (Markowitz) optimal weights for a basket, with expected return / volatility / Sharpe" , surface: "trade", availability: "live-or-sample"},
  { id: "conditionscanner", name: "Condition Scanner", icon: "Radar", category: "Analysis", description: "Run the backend's prebuilt indicator condition scans (RSI extremes, volume breakout, pre-market movers, 52-week breakouts) across a symbol universe — sortable matches with their matched conditions and one-click watchlist adds, plus live NIFTY 50 sector movers" , surface: "trade", availability: "live-or-sample"},
  { id: "pivotpoints", name: "Pivot Points", icon: "GitFork", category: "Analysis", description: "Standard, Fibonacci, Woodie, Camarilla and DeMark pivots — the pivot with R1–R4 and S1–S4 from the previous session's OHLC, plus where the price currently sits between them" , surface: "trade", availability: "live-or-sample"},
  { id: "volatilitycone", name: "Volatility Cone", icon: "Triangle", category: "Analysis", description: "Volatility cone comparing current IV against historical percentiles" , surface: "trade", availability: "live-or-sample"},
  { id: "vwapbands", name: "VWAP Bands", icon: "Waves", category: "Analysis", description: "Standalone session VWAP panel — VWAP, the close line and ±1σ/2σ/3σ bands from intraday 5-minute bars when a broker is connected, labelled sample bars otherwise" , surface: "trade", availability: "live-or-sample"},
  { id: "correlationpairs", name: "Correlation Pairs", icon: "Link", category: "Analysis", description: "Rolling correlation between selected instrument pairs" , surface: "trade", availability: "live-or-sample"},
  { id: "multitimeframe", name: "Multi-Timeframe", icon: "Layers", category: "Analysis", description: "Trend, RSI, MACD sign and EMA position for one instrument across 5m/15m/1h/1D as a signal table with a confluence score — computed from live bars when a broker is connected, labelled sample signals otherwise" , surface: "trade", availability: "live-or-sample"},
  { id: "pcrtrend", name: "PCR Trend", icon: "TrendingDown", category: "Analysis", description: "Put-Call Ratio trend line to gauge market sentiment over time — sample sessions only, no chain PCR source is wired yet" , surface: "trade", availability: "sample-only"},
  { id: "instrumentcompare", name: "Instrument Compare", icon: "GitCompare", category: "Analysis", description: "Percentage-change overlay of up to four instruments rebased to a common start — sample series only, no live price feed is wired yet" , surface: "trade", availability: "sample-only"},
  { id: "greeksheatmap", name: "Greeks Matrix", icon: "Grid3x3", category: "Analysis", description: "Per-strike theoretical Greeks across expiries — delta, gamma, theta, vega or IV — as a heat grid or a rotatable 3-D surface", surface: "trade", availability: "live-or-sample" },
  { id: "gapanalysis", name: "Gap Analysis", icon: "ArrowUpFromLine", category: "Analysis", description: "Gap-up/gap-down events with fill rate and average gap size — sample events only, no gap-history source is wired yet" , surface: "trade", availability: "sample-only"},
  { id: "correlationmatrix", name: "Correlation Matrix", icon: "Grid2x2", category: "Analysis", description: "Full correlation matrix heatmap for a configurable basket of instruments" , surface: "trade", availability: "live-or-sample"},
  { id: "deliverydata", name: "Delivery Data", icon: "Package", category: "Analysis", description: "Delivery percentage per scrip with open/high/low/close and traded volume, sorted into conviction bands — sample data only, no delivery source is wired yet" , surface: "trade", availability: "sample-only"},
  { id: "domheatmap", name: "DOM Heatmap", icon: "Flame", category: "Analysis", description: "Depth-of-market heatmap showing where large orders sit and are pulled over time — live accumulation or scrub-back replay of the captured snapshots, with log or gamma intensity" , surface: "trade", availability: "live-or-sample"},
  { id: "portfoliopivot", name: "Portfolio Pivot", icon: "Table2", category: "Analysis", description: "FINOS Perspective pivot over the live position book — group, aggregate, filter and export your open positions, with the view saved per panel" , surface: "trade", availability: "live-or-sample"},
  { id: "seasonality", name: "Seasonality", icon: "CalendarRange", category: "Analysis", description: "Monthly, weekday and day-of-month return patterns from daily price history — heat views with sample sizes, honest about thin data" , surface: "trade", availability: "live-or-sample"},

  // Utility
  { id: "watchlist", name: "Watchlist", icon: "Star", category: "Utility", description: "Customisable instrument watchlist with live LTP and change data" , surface: "shared", availability: "live-or-sample"},
  { id: "indexstrip", name: "Index Strip", icon: "TrendingUp", category: "Utility", description: "Compact strip of live index cards — NIFTY 50, BANK NIFTY, SENSEX, FIN NIFTY and India VIX with change, sparkline and a VIX>20 alert border, straight from the WebSocket tick stream" , surface: "trade", availability: "live-only"},
  { id: "calculator", name: "Calculator", icon: "Calculator", category: "Utility", description: "Position sizing (fixed %, Kelly, ATR), risk/reward targets, brokerage charges and live margin" , surface: "trade", availability: "live-or-sample"},
  { id: "news", name: "News Feed", icon: "Newspaper", category: "Utility", description: "Curated market news and announcements relevant to your watchlist" , surface: "shared", availability: "sample-only"},
  { id: "ticker", name: "Ticker", icon: "TrendingUp", category: "Utility", description: "Horizontal scrolling ticker bar showing live prices for key indices" , surface: "trade", availability: "live-or-sample"},
  { id: "aiadvisor", name: "AI Advisor", icon: "Bot", category: "Utility", description: "AI-powered trade assistant for strategy ideas, analysis, and Q&A" , surface: "trade", availability: "live-or-sample"},
  { id: "aibackends", name: "AI Backends", icon: "Layers", category: "Utility", description: "Detect and run supported AI backends — Claude Code, Cerebras, Codex, and other CLI/ACP agents" , surface: "trade", availability: "live-or-sample"},
  { id: "aiteam", name: "AI Team", icon: "Users", category: "Utility", description: "Multi-agent consensus analysis — technical, fundamental, sentiment, and risk specialists vote on a symbol" , surface: "trade", availability: "live-or-sample"},
  { id: "obsidian", name: "Obsidian Vault", icon: "BookText", category: "Utility", description: "Browse and search the Obsidian vault the AI agent reads for context and journals decisions into" , surface: "trade", availability: "live-or-sample"},
  { id: "alerts", name: "Price Alerts", icon: "Bell", category: "Utility", description: "Last-traded-price alerts — above, below, crosses above, crosses below — armed in this browser and polled while the panel is open, with a log of the ones that fired" , surface: "trade", availability: "live-or-sample"},
  { id: "reconciliation", name: "Reconciliation", icon: "ShieldCheck", category: "Utility", description: "Broker-vs-FlintTrade reconciliation status per native account with expandable mismatch reports" , surface: "trade", availability: "live-only"},
  { id: "fundingrate", name: "Funding Rates", icon: "Percent", category: "Utility", description: "Perpetual futures funding rates — needs a connected crypto broker; sample preview in Explore" , surface: "trade", availability: "live-or-sample"},
  { id: "currencyconverter", name: "Currency Converter", icon: "ArrowLeftRight", category: "Utility", description: "Convert between INR, USD, EUR, GBP, JPY, SGD and AED — static reference rates only, no FX feed is wired yet" , surface: "trade", availability: "sample-only"},
  { id: "earningscalendar", name: "Earnings Calendar", icon: "CalendarDays", category: "Utility", description: "Upcoming earnings announcements and results calendar for NSE stocks" , surface: "trade", availability: "live-or-sample"},
  { id: "strategytemplates", name: "Strategy Templates", icon: "BookOpen", category: "Utility", description: "Library of pre-built option strategy templates to launch from one click" , surface: "trade", availability: "live-or-sample"},
  { id: "audittrail", name: "Audit Trail", icon: "ScrollText", category: "Utility", description: "Append-only audit log of all orders and account events" , surface: "trade", availability: "live-or-sample"},
  { id: "economiccalendar", name: "Economic Calendar", icon: "CalendarClock", category: "Utility", description: "Macro economic event calendar with market impact ratings" , surface: "trade", availability: "live-or-sample"},
  { id: "expirycountdown", name: "Expiry Countdown", icon: "Timer", category: "Utility", description: "Countdown timers to weekly and monthly expiry across all segments" , surface: "trade", availability: "live-or-sample"},
  { id: "marketclock", name: "Market Clock", icon: "Clock", category: "Utility", description: "Multi-timezone market clock showing session open/close for NSE, NYSE, etc." , surface: "trade", availability: "live-or-sample"},
  { id: "tradeidea", name: "Trade Ideas", icon: "Lightbulb", category: "Utility", description: "Your own trade setups, typed by hand and kept in this browser: symbol, direction, entry zone, stop-loss, target, timeframe, notes and tags, tracked from planned through to completed" , surface: "trade", availability: "live-or-sample"},
  { id: "tickspeed", name: "Tick Speed", icon: "Gauge", category: "Utility", description: "Tick arrival rate gauge for detecting unusual activity in F&O instruments" , surface: "trade", availability: "live-or-sample"},
  { id: "tradejournal", name: "Journal Entries", icon: "NotebookPen", category: "Utility", description: "Your annotated trade journal on the backend store — write, edit and delete entries with notes, tags, side, prices and strategy, find them by full-text search, and see win rate and P&L across them" , surface: "trade", availability: "live-or-sample"},
];

// ---------------------------------------------------------------------------
// Fallback / Error UI
// ---------------------------------------------------------------------------
function WidgetSkeleton() {
  return (
    <div className="h-full w-full p-3 flex flex-col gap-3 animate-pulse" aria-hidden="true">
      <div className="h-4 w-2/5 rounded bg-surface-hover" />
      <div className="h-3 w-3/4 rounded bg-surface-hover" />
      <div className="h-3 w-1/2 rounded bg-surface-hover" />
      <div className="flex-1 rounded bg-surface-hover" />
    </div>
  );
}

function WidgetError({ name, message, onRetry }: { name: string; message?: string; onRetry: () => void }) {
  const handleRetry = useCallback(() => onRetry(), [onRetry]);
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3">
      <span className="text-loss text-sm">Failed to load &quot;{name}&quot;</span>
      <span className="text-text-muted text-xs">
        {message ? `Error: ${message}` : "Check console for errors"}
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleRetry}
        className="text-xs"
      >
        Retry
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error boundary to isolate widget crashes
// ---------------------------------------------------------------------------
interface ErrorBoundaryProps {
  name: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  message?: string;
}

class WidgetErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
    this.handleRetry = this.handleRetry.bind(this);
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`Widget "${this.props.name}" crashed:`, error, info);
  }

  handleRetry(): void {
    this.setState({ hasError: false, message: undefined });
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <WidgetError
          name={this.props.name}
          message={this.state.message}
          onRetry={this.handleRetry}
        />
      );
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// Panel wrapper: wraps each lazy widget in Suspense + ErrorBoundary
// ---------------------------------------------------------------------------
function createWidgetPanel(
  widgetId: string,
  LazyWidget: React.LazyExoticComponent<React.ComponentType<WidgetProps>>
): React.FC<WidgetProps> {
  const PanelComponent: React.FC<WidgetProps> = (props) => (
    <Suspense fallback={<WidgetSkeleton />}>
      <WidgetErrorBoundary name={widgetId}>
        <LazyWidget {...props} />
      </WidgetErrorBoundary>
    </Suspense>
  );
  PanelComponent.displayName = `Panel(${widgetId})`;
  return PanelComponent;
}

// ---------------------------------------------------------------------------
// Export: widgetComponents record resolved by the FlexLayout factory
// ---------------------------------------------------------------------------
/**
 * Wrap a canonical widget so a retired id keeps resolving, with the params
 * that reproduce the retired widget's presentation merged in.
 *
 * Params already present on the saved panel win: an operator who changed the
 * view before saving keeps their choice.
 */
/** Pointer panel for widgets whose capability moved into a tool or route. */
function MovedWidgetNotice({ retiredId, movedTo }: {
  retiredId: string;
  movedTo: RetiredMovedWidget["movedTo"];
}) {
  return (
    <div
      className="h-full flex flex-col items-center justify-center gap-2 px-4 text-center bg-surface-base"
      data-testid={`moved-widget-${retiredId}`}
    >
      <span className="text-sm font-medium text-text-primary">
        This widget moved to {movedTo.destination}
      </span>
      <span className="text-xs text-text-muted max-w-72">
        Its readouts live there now, so this panel can be closed — nothing else
        is lost from this layout.
      </span>
      {movedTo.route && (
        <a
          href={movedTo.route}
          className="mt-1 px-2.5 py-1 text-xs rounded border border-border-default text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
        >
          Open {movedTo.destination.split("→")[0]?.trim() ?? "destination"}
        </a>
      )}
    </div>
  );
}

function createRetiredWidgetPanel(
  retiredId: string,
  spec: RetiredWidget,
  resolved: Record<string, React.FC<WidgetProps>>,
): React.FC<WidgetProps> {
  if (isMovedWidget(spec)) {
    const PanelComponent: React.FC<WidgetProps> = () => (
      <MovedWidgetNotice retiredId={retiredId} movedTo={spec.movedTo} />
    );
    PanelComponent.displayName = `Retired(${retiredId}→${spec.movedTo.destination})`;
    return PanelComponent;
  }
  const { component, params } = spec;
  const Canonical = resolved[component];
  const PanelComponent: React.FC<WidgetProps> = (props) => {
    if (!Canonical) return <WidgetError name={retiredId} message="Canonical widget missing" onRetry={() => {}} />;
    const merged = { ...props, params: { ...params, ...(props.params ?? {}) } };
    return <Canonical {...merged} />;
  };
  PanelComponent.displayName = `Retired(${retiredId}→${component})`;
  return PanelComponent;
}

const liveWidgetComponents: Record<string, React.FC<WidgetProps>> =
  Object.fromEntries(
    Object.entries(lazyWidgets).map(([id, LazyWidget]) => [
      id,
      createWidgetPanel(id, LazyWidget as React.LazyExoticComponent<React.ComponentType<WidgetProps>>),
    ])
  );

export const widgetComponents: Record<string, React.FC<WidgetProps>> = {
  ...liveWidgetComponents,
  ...Object.fromEntries(
    Object.entries(RETIRED_WIDGET_IDS).map(([retiredId, spec]) => [
      retiredId,
      createRetiredWidgetPanel(retiredId, spec, liveWidgetComponents),
    ]),
  ),
};

// ---------------------------------------------------------------------------
// FlexLayout tab factory
// ---------------------------------------------------------------------------
/**
 * The `factory` prop for the FlexLayout `<Layout>` host: resolves the tab's
 * `component` id in {@link widgetComponents} and renders it with the
 * FlintTrade panel props bridged from the tab node.
 *
 * An unresolvable id renders the widget error surface INSIDE the tab rather
 * than failing the whole model load — under FlexLayout a saved layout with a
 * stale id degrades one panel, it never wipes the tab (the Dockview-era
 * wipe hazard is gone, but the retired-id map above still gives operators
 * their canonical widget back instead of an error card).
 */
export function flexLayoutFactory(node: TabNode): ReactNode {
  const componentId = node.getComponent();
  const WidgetComponent = componentId ? widgetComponents[componentId] : undefined;
  if (!WidgetComponent) {
    return (
      <WidgetError
        name={componentId ?? "unknown"}
        message="Unknown widget id in saved layout"
        onRetry={() => {}}
      />
    );
  }
  return <WidgetComponent {...widgetPropsForNode(node)} />;
}

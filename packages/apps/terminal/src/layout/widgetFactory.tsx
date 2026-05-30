import { lazy, Suspense, Component, useCallback } from "react";
import type { ReactNode, ErrorInfo } from "react";
import type { IDockviewPanelProps } from "dockview-react";
import type { WidgetMeta } from "@/types/widgets";

// ---------------------------------------------------------------------------
// Lazy-load all widgets -- each is a separate chunk for code splitting
// ---------------------------------------------------------------------------
const lazyWidgets = {
  // Trading widgets
  dashboard: lazy(() => import("@/widgets/trading/Dashboard/DashboardWidget")),
  scalper: lazy(() => import("@/widgets/trading/Scalper/ScalperWidget")),
  positions: lazy(() => import("@/widgets/trading/Positions/PositionsWidget")),
  orders: lazy(() => import("@/widgets/trading/Orders/OrdersWidget")),
  holdings: lazy(() => import("@/widgets/trading/Holdings/HoldingsWidget")),
  tradebook: lazy(() => import("@/widgets/trading/TradeBook/TradeBookWidget")),
  orderpad: lazy(() => import("@/widgets/trading/OrderPad/OrderPadWidget")),

  // Analysis widgets
  chart: lazy(() => import("@/widgets/analysis/Chart/ChartWidget")),
  chartgrid: lazy(() => import("@/widgets/analysis/Chart/ChartGrid")),
  optionchain: lazy(() => import("@/widgets/analysis/OptionChain/OptionChainWidget")),
  oichart: lazy(() => import("@/widgets/analysis/OIChart/OIChartWidget")),
  straddle: lazy(() => import("@/widgets/analysis/Straddle/StraddleWidget")),
  depth: lazy(() => import("@/widgets/analysis/Depth/DepthWidget")),
  greeks: lazy(() => import("@/widgets/analysis/Greeks/GreeksWidget")),

  // Utility widgets
  watchlist: lazy(() => import("@/widgets/utility/Watchlist/WatchlistWidget")),
  calculator: lazy(() => import("@/widgets/utility/Calculator/CalculatorWidget")),
  news: lazy(() => import("@/widgets/utility/News/NewsWidget")),
  ticker: lazy(() => import("@/widgets/utility/Ticker/TickerWidget")),
  aiadvisor: lazy(() => import("@/widgets/utility/AIAdvisor/AIAdvisorWidget")),

  // New trading widgets
  intradaypnl: lazy(() => import("@/widgets/trading/IntradayPnL/IntradayPnLWidget")),
  mtmmonitor: lazy(() => import("@/widgets/trading/MTMMonitor/MTMMonitorWidget")),
  riskpanel: lazy(() => import("@/widgets/trading/RiskPanel/RiskPanelWidget")),
  actioncenter: lazy(() => import("@/widgets/trading/ActionCenter/ActionCenterWidget")),
  positionheatmap: lazy(() => import("@/widgets/trading/PositionHeatMap/PositionHeatMapWidget")),

  // New analysis widgets
  sectormap: lazy(() => import("@/widgets/analysis/SectorMap/SectorMapWidget")),
  gex: lazy(() => import("@/widgets/analysis/GEX/GEXWidget")),
  volsurface: lazy(() => import("@/widgets/analysis/VolSurface/VolSurfaceWidget")),
  ivsmile: lazy(() => import("@/widgets/analysis/IVSmile/IVSmileWidget")),
  straddlepnl: lazy(() => import("@/widgets/analysis/StraddlePnL/StraddlePnLWidget")),
  oiprofile: lazy(() => import("@/widgets/analysis/OIProfile/OIProfileWidget")),
  orderflow: lazy(() => import("@/widgets/analysis/OrderFlow/OrderFlowWidget")),
  depthheatmap: lazy(() => import("@/widgets/analysis/DepthHeatmap/DepthHeatmapWidget")),

  // Utility widgets (new)
  scanner: lazy(() => import("@/widgets/utility/Scanner/ScannerWidget")),
  alerts: lazy(() => import("@/widgets/utility/Alerts/AlertsWidget")),
  health: lazy(() => import("@/widgets/utility/Health/HealthWidget")),

  // Analysis widgets (new)
  threepanel: lazy(() => import("@/widgets/analysis/ThreePanel/ThreePanelWidget")),

  // OI Heatmap
  oiheatmap: lazy(() => import("@/widgets/analysis/OIHeatmap/OIHeatmapWidget")),

  // Trade Copier (Ditto route)
  tradecopier: lazy(() => import("@/widgets/trading/TradeCopier/TradeCopierWidget")),

  // Analysis widgets (Wave 24)
  greekssurface: lazy(() => import("@/widgets/analysis/GreeksSurface/GreeksSurfaceWidget")),

  // Utility widgets (Wave 24)
  fundingrate: lazy(() => import("@/widgets/utility/FundingRate/FundingRateWidget")),

  // Utility widgets (Wave 25)
  currencyconverter: lazy(() => import("@/widgets/utility/CurrencyConverter/CurrencyConverterWidget")),
  earningscalendar: lazy(() => import("@/widgets/utility/EarningsCalendar/EarningsCalendarWidget")),
  globalindices: lazy(() => import("@/widgets/utility/GlobalIndices/GlobalIndicesWidget")),
  strategytemplates: lazy(() => import("@/widgets/utility/StrategyTemplates/StrategyTemplatesWidget")),
  audittrail: lazy(() => import("@/widgets/utility/AuditTrail/AuditTrailWidget")),

  // Wave 26 widgets
  pivotpoints: lazy(() => import("@/widgets/analysis/PivotPoints/PivotPointsWidget")),
  economiccalendar: lazy(() => import("@/widgets/utility/EconomicCalendar/EconomicCalendarWidget")),
  portfolioallocation: lazy(() => import("@/widgets/trading/PortfolioAllocation/PortfolioAllocationWidget")),
  orderbookreplay: lazy(() => import("@/widgets/analysis/OrderBookReplay/OrderBookReplayWidget")),

  // Wave 27 widgets
  marketbreadth: lazy(() => import("@/widgets/analysis/MarketBreadth/MarketBreadthWidget")),
  quicktrade: lazy(() => import("@/widgets/trading/QuickTrade/QuickTradeWidget")),
  volatilitycone: lazy(() => import("@/widgets/analysis/VolatilityCone/VolatilityConeWidget")),
  profittarget: lazy(() => import("@/widgets/utility/ProfitTarget/ProfitTargetWidget")),

  // Wave 28 widgets
  heatcalendar: lazy(() => import("@/widgets/analysis/HeatCalendar/HeatCalendarWidget")),
  vwapbands: lazy(() => import("@/widgets/analysis/VWAPBands/VWAPBandsWidget")),
  correlationpairs: lazy(() => import("@/widgets/analysis/CorrelationPairs/CorrelationPairsWidget")),
  multitimeframe: lazy(() => import("@/widgets/analysis/MultiTimeframe/MultiTimeframeWidget")),

  // Wave 29 widgets
  pcrtrend: lazy(() => import("@/widgets/analysis/PCRTrend/PCRTrendWidget")),
  tradeperformance: lazy(() => import("@/widgets/trading/TradePerformance/TradePerformanceWidget")),
  instrumentcompare: lazy(() => import("@/widgets/analysis/InstrumentCompare/InstrumentCompareWidget")),
  spreadview: lazy(() => import("@/widgets/analysis/SpreadView/SpreadViewWidget")),

  // Wave 30 widgets
  greeksheatmap: lazy(() => import("@/widgets/analysis/GreeksHeatmap/GreeksHeatmapWidget")),
  marketsummary: lazy(() => import("@/widgets/utility/MarketSummary/MarketSummaryWidget")),
  gapanalysis: lazy(() => import("@/widgets/analysis/GapAnalysis/GapAnalysisWidget")),
  sessionstats: lazy(() => import("@/widgets/trading/SessionStats/SessionStatsWidget")),

  // Wave 31 widgets
  impliedmove: lazy(() => import("@/widgets/analysis/ImpliedMove/ImpliedMoveWidget")),
  riskdashboard: lazy(() => import("@/widgets/trading/RiskDashboard/RiskDashboardWidget")),
  optionsflow: lazy(() => import("@/widgets/analysis/OptionsFlow/OptionsFlowWidget")),
  tradelog: lazy(() => import("@/widgets/trading/TradeLog/TradeLogWidget")),

  // Wave 32 widgets
  microstructure: lazy(() => import("@/widgets/analysis/Microstructure/MicrostructureWidget")),
  expirycountdown: lazy(() => import("@/widgets/utility/ExpiryCountdown/ExpiryCountdownWidget")),
  positionsizing: lazy(() => import("@/widgets/utility/PositionSizing/PositionSizingWidget")),
  correlationmatrix: lazy(() => import("@/widgets/analysis/CorrelationMatrix/CorrelationMatrixWidget")),

  // Wave 33 widgets
  ivskew: lazy(() => import("@/widgets/analysis/IVSkew/IVSkewWidget")),
  marketclock: lazy(() => import("@/widgets/utility/MarketClock/MarketClockWidget")),
  strategymonitor: lazy(() => import("@/widgets/trading/StrategyMonitor/StrategyMonitorWidget")),
  netposition: lazy(() => import("@/widgets/trading/NetPosition/NetPositionWidget")),

  // Wave 34 widgets
  tradeidea: lazy(() => import("@/widgets/utility/TradeIdea/TradeIdeaWidget")),
  sectorperformance: lazy(() => import("@/widgets/analysis/SectorPerformance/SectorPerformanceWidget")),
  tickspeed: lazy(() => import("@/widgets/utility/TickSpeed/TickSpeedWidget")),
  orderladder: lazy(() => import("@/widgets/trading/OrderLadder/OrderLadderWidget")),

  // Wave 35 — order flow visualisation
  footprint: lazy(() => import("@/widgets/analysis/Footprint/FootprintWidget")),
  domheatmap: lazy(() => import("@/widgets/analysis/DOMHeatmap/DOMHeatmapWidget")),
};

// ---------------------------------------------------------------------------
// Widget metadata for the picker popup
// ---------------------------------------------------------------------------
export const widgetCatalog: WidgetMeta[] = [
  // Trading
  { id: "dashboard", name: "Dashboard", icon: "LayoutDashboard", category: "Trading", description: "Overview of open positions, real-time P&L, and market status" },
  { id: "scalper", name: "Scalper", icon: "Zap", category: "Trading", description: "One-click order entry panel optimised for intraday F&O scalping" },
  { id: "positions", name: "Positions", icon: "Table2", category: "Trading", description: "Live position book with MTM P&L, quantity, and average price" },
  { id: "orders", name: "Orders", icon: "ClipboardList", category: "Trading", description: "Order book showing pending, executed, and rejected orders" },
  { id: "holdings", name: "Holdings", icon: "Wallet", category: "Trading", description: "Long-term equity and mutual fund holdings with current value" },
  { id: "tradebook", name: "Trade Book", icon: "BookOpen", category: "Trading", description: "Executed trade history for the current session" },
  { id: "orderpad", name: "Order Pad", icon: "FileEdit", category: "Trading", description: "Full-featured order entry form with limit, market, and bracket orders" },
  { id: "intradaypnl", name: "Intraday P&L", icon: "TrendingUp", category: "Trading", description: "Intraday profit and loss chart updated tick by tick" },
  { id: "mtmmonitor", name: "MTM Monitor", icon: "Target", category: "Trading", description: "Mark-to-market monitor with target and stop-loss level alerts" },
  { id: "riskpanel", name: "Risk Panel", icon: "ShieldAlert", category: "Trading", description: "Real-time risk metrics: max drawdown, margin used, and exposure limits" },
  { id: "actioncenter", name: "Action Center", icon: "ShieldCheck", category: "Trading", description: "One-click emergency actions: exit all, cancel all, flatten book" },
  { id: "positionheatmap", name: "Position Heat Map", icon: "SquareStack", category: "Trading", description: "Heat map of current positions coloured by unrealised P&L" },
  { id: "tradecopier", name: "Trade Copier", icon: "Copy", category: "Trading", description: "Mirror trades across multiple accounts with configurable lot multipliers" },
  { id: "portfolioallocation", name: "Portfolio Allocation", icon: "PieChart", category: "Trading", description: "Pie chart breakdown of portfolio allocation by sector and instrument" },
  { id: "quicktrade", name: "Quick Trade", icon: "Zap", category: "Trading", description: "Minimal order ticket for fast order placement without leaving the chart" },
  { id: "sessionstats", name: "Session Stats", icon: "Clock", category: "Trading", description: "Key statistics for the current trading session: trades, win rate, turnover" },
  { id: "riskdashboard", name: "Risk Dashboard", icon: "ShieldAlert", category: "Trading", description: "Consolidated risk dashboard: Greeks exposure, VaR, and concentration risk" },
  { id: "tradelog", name: "Trade Log", icon: "FileText", category: "Trading", description: "Annotated trade journal with entry/exit reasons and screenshots" },
  { id: "tradeperformance", name: "Trade Performance", icon: "Trophy", category: "Trading", description: "Performance analytics: expectancy, Sharpe ratio, and streak analysis" },
  { id: "strategymonitor", name: "Strategy Monitor", icon: "Activity", category: "Trading", description: "Live status of all running automated strategies with PnL per strategy" },
  { id: "netposition", name: "Net Positions", icon: "Layers", category: "Trading", description: "Aggregated net position across all accounts for a given instrument" },
  { id: "orderladder", name: "Order Ladder", icon: "ArrowUpDown", category: "Trading", description: "Ladder-style DOM view for rapid limit order placement and cancellation" },

  // Analysis
  { id: "chart", name: "Chart", icon: "CandlestickChart", category: "Analysis", description: "Interactive candlestick chart with indicators, drawing tools, and replay" },
  { id: "chartgrid", name: "Multi Chart", icon: "LayoutGrid", category: "Analysis", description: "1×1, 1×2, 2×1, or 2×2 grid of independent charts with per-cell symbol and interval" },
  { id: "optionchain", name: "Option Chain", icon: "Grid3x3", category: "Analysis", description: "Live option chain with strike-level OI, volume, IV, and Greek data" },
  { id: "oichart", name: "OI Chart", icon: "BarChart3", category: "Analysis", description: "Open interest change chart across strikes for a selected expiry" },
  { id: "straddle", name: "Straddle", icon: "Activity", category: "Analysis", description: "Straddle and strangle builder with premium, breakeven, and IV display" },
  { id: "depth", name: "Depth", icon: "Layers", category: "Analysis", description: "Level-2 market depth showing top 5 or 50 bid/ask levels" },
  { id: "greeks", name: "Greeks", icon: "Sigma", category: "Analysis", description: "Position-level Delta, Gamma, Theta, Vega, and Rho summary" },
  { id: "sectormap", name: "Sector Map", icon: "Map", category: "Analysis", description: "Colour-coded sector tree map showing intraday performance by industry" },
  { id: "gex", name: "GEX Dashboard", icon: "BarChart2", category: "Analysis", description: "Gamma Exposure (GEX) by strike to identify key support and resistance levels" },
  { id: "volsurface", name: "Vol Surface", icon: "Box", category: "Analysis", description: "3-D implied volatility surface across strikes and expiries" },
  { id: "ivsmile", name: "IV Smile", icon: "TrendingUp", category: "Analysis", description: "Implied volatility smile curve for a selected expiry date" },
  { id: "straddlepnl", name: "Straddle P&L", icon: "ArrowLeftRight", category: "Analysis", description: "Payoff diagram for straddle positions with breakeven markers" },
  { id: "oiprofile", name: "OI Profile", icon: "BarChart", category: "Analysis", description: "OI distribution profile across strikes to identify congestion zones" },
  { id: "orderflow", name: "Order Flow", icon: "BarChart2", category: "Analysis", description: "Real-time buy/sell order flow footprint for active F&O contracts" },
  { id: "depthheatmap", name: "Depth Heatmap", icon: "Flame", category: "Analysis", description: "Heatmap of order book depth changes over time" },
  { id: "threepanel", name: "Three-Panel Chart", icon: "Columns3", category: "Analysis", description: "Three synchronised chart panels for multi-instrument comparison" },
  { id: "oiheatmap", name: "OI Heatmap", icon: "Grid2x2", category: "Analysis", description: "Heat map of open interest changes across strikes and expiries" },
  { id: "greekssurface", name: "Greeks Surface", icon: "Box", category: "Analysis", description: "3-D surface plot of option Greeks across strikes and days to expiry" },
  { id: "pivotpoints", name: "Pivot Points", icon: "GitFork", category: "Analysis", description: "Classic, Camarilla, and Woodie pivot levels for the current session" },
  { id: "orderbookreplay", name: "Order Book Replay", icon: "BarChart3", category: "Analysis", description: "Historical replay of the order book for post-session microstructure analysis" },
  { id: "marketbreadth", name: "Market Breadth", icon: "BarChart4", category: "Analysis", description: "Advance/decline ratio, new highs/lows, and breadth oscillators for NSE" },
  { id: "volatilitycone", name: "Volatility Cone", icon: "Triangle", category: "Analysis", description: "Volatility cone comparing current IV against historical percentiles" },
  { id: "heatcalendar", name: "Heat Calendar", icon: "Calendar", category: "Analysis", description: "Calendar heat map of daily P&L or returns for pattern spotting" },
  { id: "vwapbands", name: "VWAP Bands", icon: "Waves", category: "Analysis", description: "VWAP with standard deviation bands overlaid on the price chart" },
  { id: "correlationpairs", name: "Correlation Pairs", icon: "Link", category: "Analysis", description: "Rolling correlation between selected instrument pairs" },
  { id: "multitimeframe", name: "Multi-Timeframe", icon: "Layers", category: "Analysis", description: "Four charts of the same instrument at different timeframes in one view" },
  { id: "pcrtrend", name: "PCR Trend", icon: "TrendingDown", category: "Analysis", description: "Put-Call Ratio trend line to gauge market sentiment over time" },
  { id: "instrumentcompare", name: "Instrument Compare", icon: "GitCompare", category: "Analysis", description: "Percentage-based comparison chart for up to five instruments" },
  { id: "spreadview", name: "Spread View", icon: "ArrowUpDown", category: "Analysis", description: "Spread and basis chart between two correlated instruments or futures" },
  { id: "greeksheatmap", name: "Greeks Heatmap", icon: "Grid3x3", category: "Analysis", description: "Heat map of aggregate Greeks exposure across the option portfolio" },
  { id: "gapanalysis", name: "Gap Analysis", icon: "ArrowUpFromLine", category: "Analysis", description: "Historical gap statistics showing fill probability and average size" },
  { id: "impliedmove", name: "Implied Move", icon: "MoveHorizontal", category: "Analysis", description: "Expected move range derived from ATM straddle premium for current expiry" },
  { id: "optionsflow", name: "Options Flow", icon: "Workflow", category: "Analysis", description: "Real-time large options trade scanner showing unusual activity" },
  { id: "microstructure", name: "Market Microstructure", icon: "Microscope", category: "Analysis", description: "Tick-level microstructure analysis: trade clustering, aggressor ratio, VPIN" },
  { id: "correlationmatrix", name: "Correlation Matrix", icon: "Grid2x2", category: "Analysis", description: "Full correlation matrix heatmap for a configurable basket of instruments" },
  { id: "ivskew", name: "IV Skew", icon: "Activity", category: "Analysis", description: "Skew chart showing the difference in IV between OTM puts and calls" },
  { id: "sectorperformance", name: "Sector Performance", icon: "BarChart", category: "Analysis", description: "Bar chart of intraday performance ranked by sector" },
  { id: "footprint", name: "Footprint Chart", icon: "BarChart2", category: "Analysis", description: "Footprint chart with per-cell buy/sell volume, delta, POC, and cumulative delta strip" },
  { id: "domheatmap", name: "DOM Heatmap", icon: "Flame", category: "Analysis", description: "Historical depth-of-market heatmap showing where large orders sit and are pulled over time" },

  // Utility
  { id: "watchlist", name: "Watchlist", icon: "Star", category: "Utility", description: "Customisable instrument watchlist with live LTP and change data" },
  { id: "calculator", name: "Calculator", icon: "Calculator", category: "Utility", description: "Options payoff and break-even calculator with strategy builder" },
  { id: "news", name: "News Feed", icon: "Newspaper", category: "Utility", description: "Curated market news and announcements relevant to your watchlist" },
  { id: "ticker", name: "Ticker", icon: "TrendingUp", category: "Utility", description: "Horizontal scrolling ticker bar showing live prices for key indices" },
  { id: "aiadvisor", name: "AI Advisor", icon: "Bot", category: "Utility", description: "AI-powered trade assistant for strategy ideas, analysis, and Q&A" },
  { id: "scanner", name: "Pre-Market Scanner", icon: "ScanLine", category: "Utility", description: "Pre-market gap scanner filtering by OI buildup, IV rank, and price action" },
  { id: "alerts", name: "Price Alerts", icon: "Bell", category: "Utility", description: "Price and indicator alerts with Telegram and in-app notifications" },
  { id: "health", name: "System Health", icon: "Activity", category: "Utility", description: "OpenAlgo connection status, WebSocket latency, and API health metrics" },
  { id: "fundingrate", name: "Funding Rates", icon: "Percent", category: "Utility", description: "Perpetual futures funding rates across exchanges for arbitrage tracking" },
  { id: "currencyconverter", name: "Currency Converter", icon: "ArrowLeftRight", category: "Utility", description: "Live currency converter for INR, USD, and major pairs" },
  { id: "earningscalendar", name: "Earnings Calendar", icon: "CalendarDays", category: "Utility", description: "Upcoming earnings announcements and results calendar for NSE stocks" },
  { id: "globalindices", name: "Global Indices", icon: "Globe", category: "Utility", description: "Live prices for major global indices: SGX Nifty, Dow, S&P, Nasdaq, etc." },
  { id: "strategytemplates", name: "Strategy Templates", icon: "BookOpen", category: "Utility", description: "Library of pre-built option strategy templates to launch from one click" },
  { id: "audittrail", name: "Audit Trail", icon: "ScrollText", category: "Utility", description: "Append-only audit log of all orders and account events" },
  { id: "economiccalendar", name: "Economic Calendar", icon: "CalendarClock", category: "Utility", description: "Macro economic event calendar with market impact ratings" },
  { id: "profittarget", name: "Profit Target Calc", icon: "Target", category: "Utility", description: "Position-aware profit target and stop-loss calculator with R:R ratio" },
  { id: "expirycountdown", name: "Expiry Countdown", icon: "Timer", category: "Utility", description: "Countdown timers to weekly and monthly expiry across all segments" },
  { id: "positionsizing", name: "Position Sizing", icon: "Ruler", category: "Utility", description: "Kelly criterion and fixed-risk position sizing calculator" },
  { id: "marketclock", name: "Market Clock", icon: "Clock", category: "Utility", description: "Multi-timezone market clock showing session open/close for NSE, NYSE, etc." },
  { id: "tradeidea", name: "Trade Ideas", icon: "Lightbulb", category: "Utility", description: "AI-generated trade ideas based on screener signals and market regime" },
  { id: "tickspeed", name: "Tick Speed", icon: "Gauge", category: "Utility", description: "Tick arrival rate gauge for detecting unusual activity in F&O instruments" },
  { id: "marketsummary", name: "Market Summary", icon: "LayoutDashboard", category: "Utility", description: "Snapshot of market breadth, FII/DII data, and sector rotation for the day" },
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

function WidgetError({ name, onRetry }: { name: string; onRetry: () => void }) {
  const handleRetry = useCallback(() => onRetry(), [onRetry]);
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3">
      <span className="text-loss text-sm">Failed to load &quot;{name}&quot;</span>
      <span className="text-text-muted text-xs">Check console for errors</span>
      <button
        type="button"
        onClick={handleRetry}
        className="px-3 py-1.5 text-xs font-medium rounded border border-border-default text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
      >
        Retry
      </button>
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
}

class WidgetErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
    this.handleRetry = this.handleRetry.bind(this);
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`Widget "${this.props.name}" crashed:`, error, info);
  }

  handleRetry(): void {
    this.setState({ hasError: false });
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return <WidgetError name={this.props.name} onRetry={this.handleRetry} />;
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// Dockview panel wrapper: wraps each lazy widget in Suspense + ErrorBoundary
// ---------------------------------------------------------------------------
function createWidgetPanel(
  widgetId: string,
  LazyWidget: React.LazyExoticComponent<React.ComponentType<IDockviewPanelProps>>
): React.FC<IDockviewPanelProps> {
  const PanelComponent: React.FC<IDockviewPanelProps> = (props) => (
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
// Export: widgetComponents record for DockviewReact `components` prop
// ---------------------------------------------------------------------------
export const widgetComponents: Record<string, React.FC<IDockviewPanelProps>> =
  Object.fromEntries(
    Object.entries(lazyWidgets).map(([id, LazyWidget]) => [
      id,
      createWidgetPanel(id, LazyWidget as React.LazyExoticComponent<React.ComponentType<IDockviewPanelProps>>),
    ])
  );

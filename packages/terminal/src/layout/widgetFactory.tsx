import { lazy, Suspense, Component } from "react";
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
};

// ---------------------------------------------------------------------------
// Widget metadata for the picker popup
// ---------------------------------------------------------------------------
export const widgetCatalog: WidgetMeta[] = [
  { id: "dashboard", name: "Dashboard", icon: "LayoutDashboard", category: "Trading" },
  { id: "scalper", name: "Scalper", icon: "Zap", category: "Trading" },
  { id: "positions", name: "Positions", icon: "Table2", category: "Trading" },
  { id: "orders", name: "Orders", icon: "ClipboardList", category: "Trading" },
  { id: "holdings", name: "Holdings", icon: "Wallet", category: "Trading" },
  { id: "tradebook", name: "Trade Book", icon: "BookOpen", category: "Trading" },
  { id: "orderpad", name: "Order Pad", icon: "FileEdit", category: "Trading" },
  { id: "chart", name: "Chart", icon: "CandlestickChart", category: "Analysis" },
  { id: "optionchain", name: "Option Chain", icon: "Grid3x3", category: "Analysis" },
  { id: "oichart", name: "OI Chart", icon: "BarChart3", category: "Analysis" },
  { id: "straddle", name: "Straddle", icon: "Activity", category: "Analysis" },
  { id: "depth", name: "Depth", icon: "Layers", category: "Analysis" },
  { id: "greeks", name: "Greeks", icon: "Sigma", category: "Analysis" },
  { id: "watchlist", name: "Watchlist", icon: "Star", category: "Utility" },
  { id: "calculator", name: "Calculator", icon: "Calculator", category: "Utility" },
  { id: "news", name: "News Feed", icon: "Newspaper", category: "Utility" },
  { id: "ticker", name: "Ticker", icon: "TrendingUp", category: "Utility" },
  { id: "aiadvisor", name: "AI Advisor", icon: "Bot", category: "Utility" },
  { id: "intradaypnl", name: "Intraday P&L", icon: "TrendingUp", category: "Trading" },
  { id: "mtmmonitor", name: "MTM Monitor", icon: "Target", category: "Trading" },
  { id: "riskpanel", name: "Risk Panel", icon: "ShieldAlert", category: "Trading" },
  { id: "actioncenter", name: "Action Center", icon: "ShieldCheck", category: "Trading" },
  { id: "positionheatmap", name: "Position Heat Map", icon: "SquareStack", category: "Trading" },
  { id: "sectormap", name: "Sector Map", icon: "Map", category: "Analysis" },
  { id: "gex", name: "GEX Dashboard", icon: "BarChart2", category: "Analysis" },
  { id: "volsurface", name: "Vol Surface", icon: "Box", category: "Analysis" },
  { id: "ivsmile", name: "IV Smile", icon: "TrendingUp", category: "Analysis" },
  { id: "straddlepnl", name: "Straddle P&L", icon: "ArrowLeftRight", category: "Analysis" },
  { id: "oiprofile", name: "OI Profile", icon: "BarChart", category: "Analysis" },
  { id: "orderflow", name: "Order Flow", icon: "BarChart2", category: "Analysis" },
  { id: "depthheatmap", name: "Depth Heatmap", icon: "Flame", category: "Analysis" },
  { id: "scanner", name: "Pre-Market Scanner", icon: "ScanLine", category: "Utility" },
  { id: "alerts", name: "Price Alerts", icon: "Bell", category: "Utility" },
  { id: "health", name: "System Health", icon: "Activity", category: "Utility" },
  { id: "threepanel", name: "Three-Panel Chart", icon: "Columns3", category: "Analysis" },
  { id: "oiheatmap", name: "OI Heatmap", icon: "Grid2x2", category: "Analysis" },
  { id: "tradecopier", name: "Trade Copier", icon: "Copy", category: "Trading" },
  { id: "greekssurface", name: "Greeks Surface", icon: "Box", category: "Analysis" },
  { id: "fundingrate", name: "Funding Rates", icon: "Percent", category: "Utility" },
  { id: "currencyconverter", name: "Currency Converter", icon: "ArrowLeftRight", category: "Utility" },
  { id: "earningscalendar", name: "Earnings Calendar", icon: "CalendarDays", category: "Utility" },
  { id: "globalindices", name: "Global Indices", icon: "Globe", category: "Utility" },
  { id: "strategytemplates", name: "Strategy Templates", icon: "BookOpen", category: "Utility" },
  { id: "audittrail", name: "Audit Trail", icon: "ScrollText", category: "Utility" },
  { id: "pivotpoints", name: "Pivot Points", icon: "GitFork", category: "Analysis" },
  { id: "economiccalendar", name: "Economic Calendar", icon: "CalendarClock", category: "Utility" },
  { id: "portfolioallocation", name: "Portfolio Allocation", icon: "PieChart", category: "Trading" },
  { id: "orderbookreplay", name: "Order Book Replay", icon: "BarChart3", category: "Analysis" },

  // Wave 27
  { id: "marketbreadth", name: "Market Breadth", icon: "BarChart4", category: "Analysis" },
  { id: "quicktrade", name: "Quick Trade", icon: "Zap", category: "Trading" },
  { id: "volatilitycone", name: "Volatility Cone", icon: "Triangle", category: "Analysis" },
  { id: "profittarget", name: "Profit Target Calc", icon: "Target", category: "Utility" },

  // Wave 28
  { id: "heatcalendar", name: "Heat Calendar", icon: "Calendar", category: "Analysis" },
  { id: "vwapbands", name: "VWAP Bands", icon: "Waves", category: "Analysis" },
  { id: "correlationpairs", name: "Correlation Pairs", icon: "Link", category: "Analysis" },
  { id: "multitimeframe", name: "Multi-Timeframe", icon: "Layers", category: "Analysis" },

  // Wave 29
  { id: "pcrtrend", name: "PCR Trend", icon: "TrendingDown", category: "Analysis" },
  { id: "tradeperformance", name: "Trade Performance", icon: "Trophy", category: "Trading" },
  { id: "instrumentcompare", name: "Instrument Compare", icon: "GitCompare", category: "Analysis" },
  { id: "spreadview", name: "Spread View", icon: "ArrowUpDown", category: "Analysis" },

  // Wave 30
  { id: "greeksheatmap", name: "Greeks Heatmap", icon: "Grid3x3", category: "Analysis" },
  { id: "marketsummary", name: "Market Summary", icon: "LayoutDashboard", category: "Utility" },
  { id: "gapanalysis", name: "Gap Analysis", icon: "ArrowUpFromLine", category: "Analysis" },
  { id: "sessionstats", name: "Session Stats", icon: "Clock", category: "Trading" },
];

// ---------------------------------------------------------------------------
// Fallback / Error UI
// ---------------------------------------------------------------------------
function WidgetFallback() {
  return (
    <div className="flex items-center justify-center h-full text-text-secondary text-sm">
      Loading widget...
    </div>
  );
}

function WidgetError({ name }: { name: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-2">
      <span className="text-loss text-sm">Failed to load &quot;{name}&quot;</span>
      <span className="text-text-muted text-xs">Check console for errors</span>
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
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`Widget "${this.props.name}" crashed:`, error, info);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return <WidgetError name={this.props.name} />;
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
    <Suspense fallback={<WidgetFallback />}>
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

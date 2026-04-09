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
  mtmmonitor: lazy(() => import("@/widgets/trading/MTMMonitor/MTMMonitorWidget")),
  riskpanel: lazy(() => import("@/widgets/trading/RiskPanel/RiskPanelWidget")),
  actioncenter: lazy(() => import("@/widgets/trading/ActionCenter/ActionCenterWidget")),

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
  { id: "mtmmonitor", name: "MTM Monitor", icon: "Target", category: "Trading" },
  { id: "riskpanel", name: "Risk Panel", icon: "ShieldAlert", category: "Trading" },
  { id: "actioncenter", name: "Action Center", icon: "ShieldCheck", category: "Trading" },
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

import { lazy, Suspense } from 'react'

// Lazy-load all widgets — each is a separate chunk for code splitting
const widgets = {
  // Trading widgets
  dashboard: lazy(() => import('../widgets/trading/Dashboard/DashboardWidget')),
  scalper: lazy(() => import('../widgets/trading/Scalper/ScalperWidget')),
  positions: lazy(() => import('../widgets/trading/Positions/PositionsWidget')),
  orders: lazy(() => import('../widgets/trading/Orders/OrdersWidget')),
  holdings: lazy(() => import('../widgets/trading/Holdings/HoldingsWidget')),

  // Analysis widgets
  chart: lazy(() => import('../widgets/analysis/Chart/ChartWidget')),
  optionchain: lazy(() => import('../widgets/analysis/OptionChain/OptionChainWidget')),
  oichart: lazy(() => import('../widgets/analysis/OIChart/OIChartWidget')),

  // Utility widgets
  watchlist: lazy(() => import('../widgets/utility/Watchlist/WatchlistWidget')),
}

// Widget metadata for the picker popup
export const widgetCatalog = [
  { id: 'dashboard', name: 'Dashboard', icon: 'LayoutDashboard', category: 'Trading' },
  { id: 'scalper', name: 'Scalper', icon: 'Zap', category: 'Trading' },
  { id: 'positions', name: 'Positions', icon: 'Table2', category: 'Trading' },
  { id: 'orders', name: 'Orders', icon: 'ClipboardList', category: 'Trading' },
  { id: 'holdings', name: 'Holdings', icon: 'Wallet', category: 'Trading' },
  { id: 'chart', name: 'Chart', icon: 'CandlestickChart', category: 'Analysis' },
  { id: 'optionchain', name: 'Option Chain', icon: 'Grid3x3', category: 'Analysis' },
  { id: 'oichart', name: 'OI Chart', icon: 'BarChart3', category: 'Analysis' },
  { id: 'watchlist', name: 'Watchlist', icon: 'Star', category: 'Utility' },
]

function WidgetFallback() {
  return (
    <div className="flex items-center justify-center h-full text-text-secondary text-sm">
      Loading widget...
    </div>
  )
}

function WidgetError({ name }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-2">
      <span className="text-loss text-sm">Failed to load "{name}"</span>
      <span className="text-text-muted text-xs">Check console for errors</span>
    </div>
  )
}

// FlexLayout factory function — maps node.getComponent() → React component
export function widgetFactory(node) {
  const component = node.getComponent()
  const Widget = widgets[component]

  if (!Widget) {
    return <WidgetError name={component} />
  }

  return (
    <Suspense fallback={<WidgetFallback />}>
      <ErrorBoundary name={component}>
        <Widget node={node} />
      </ErrorBoundary>
    </Suspense>
  )
}

// Error boundary to isolate widget crashes
import { Component } from 'react'

class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, info) {
    console.error(`Widget "${this.props.name}" crashed:`, error, info)
  }

  render() {
    if (this.state.hasError) {
      return <WidgetError name={this.props.name} />
    }
    return this.props.children
  }
}

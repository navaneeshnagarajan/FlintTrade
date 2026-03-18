# Phase 1: FlexLayout Foundation — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the terminal from a fixed-sidebar module app into a FlexLayout-based widget-composable workspace, consolidating all 3 React packages into 1.

**Architecture:** Replace App.jsx's sidebar+module pattern with a chrome shell (TopBar, TickerBar) + FlexLayout canvas. Existing modules become widgets rendered by a factory function. Layouts are JSON files saved to localStorage. A centralized DataBus prevents duplicate API calls across widgets.

**Tech Stack:** React 19, flexlayout-react, Vite 6, Tailwind CSS v4, lightweight-charts v5, existing OpenAlgo API client + WebSocket client.

---

## File Structure (what changes)

### Keep (unchanged):
- `src/services/api.js` — OpenAlgo REST client (works perfectly)
- `src/services/websocket.js` — OpenAlgo WebSocket client (works perfectly)
- `src/components/Chart.jsx` — TradingView Lightweight Charts wrapper
- `src/index.css` — Theme variables and Tailwind config
- `src/main.jsx` — Entry point (minor edit)
- `vite.config.js` — Build config (unchanged)
- `index.html` — HTML template (unchanged)

### Create (new files):
- `src/App.jsx` — **REWRITE**: Chrome shell + FlexLayout container
- `src/chrome/TopBar.jsx` — Logo, clock, layout tabs, P&L, TOOLS, WIDGETS buttons
- `src/chrome/TickerBar.jsx` — Scrolling index prices
- `src/chrome/LayoutTabs.jsx` — Multiple layout tabs with add/rename/close
- `src/chrome/WidgetPicker.jsx` — Popup grid of available widgets
- `src/chrome/ToolsDropdown.jsx` — Dropdown for full-page tools
- `src/layout/LayoutManager.jsx` — FlexLayout `<Layout>` wrapper
- `src/layout/widgetFactory.jsx` — Maps widget type → React component
- `src/layout/layoutStore.js` — Save/load/manage layouts in localStorage
- `src/layout/presets/scalper-zone.json` — Preset layout
- `src/layout/presets/analysis-desk.json` — Preset layout
- `src/layout/presets/market-watch.json` — Preset layout
- `src/layout/presets/minimal.json` — Preset layout
- `src/layout/presets/blank.json` — Empty canvas preset
- `src/services/dataBus.js` — Centralized data subscription + rate limiting
- `src/services/rateLimiter.js` — Token-bucket rate limiter
- `src/widgets/trading/Positions/PositionsWidget.jsx` — From Portfolio.jsx positions tab
- `src/widgets/trading/Orders/OrdersWidget.jsx` — From Portfolio.jsx orders tab
- `src/widgets/analysis/OptionChain/OptionChainWidget.jsx` — From OptionChain.jsx
- `src/widgets/analysis/Chart/ChartWidget.jsx` — Wraps existing Chart.jsx
- `src/widgets/utility/Watchlist/WatchlistWidget.jsx` — New
- `src/hooks/useDataBus.js` — Hook to subscribe to DataBus topics

### Move/Rename (existing code → widget structure):
- `src/modules/Dashboard.jsx` → `src/widgets/trading/Dashboard/DashboardWidget.jsx`
- `src/modules/OptionChain.jsx` → `src/widgets/analysis/OptionChain/OptionChainWidget.jsx`
- `src/modules/Settings.jsx` → `src/tools/Settings/SettingsTool.jsx`
- `src/modules/Scalper.jsx` → `src/widgets/trading/Scalper/ScalperWidget.jsx`
- `src/modules/Portfolio.jsx` → Split into Positions + Orders + Holdings widgets
- `src/modules/Journal.jsx` → `src/tools/TradeJournal/TradeJournalTool.jsx`
- `src/modules/Backtest.jsx` → `src/tools/BacktestLab/BacktestLabTool.jsx`
- `src/modules/FuturesOI.jsx` → `src/widgets/analysis/OIChart/OIChartWidget.jsx`
- `src/modules/Strategy.jsx` → `src/tools/StrategyBuilder/StrategyBuilderTool.jsx`

### Delete:
- `packages/dashboard/` — Entire directory (stub, absorbed)
- `packages/backtest/` — Entire directory (stub, absorbed)
- `src/hooks/useKeyboard.js` — Global F1-F8 shortcuts no longer apply (keyboard moves into individual widgets)

---

## Task 1: Install flexlayout-react and update dependencies

**Files:**
- Modify: `packages/terminal/package.json`

- [ ] **Step 1: Install flexlayout-react**

```bash
cd packages/terminal && npm install flexlayout-react
```

- [ ] **Step 2: Verify installation**

```bash
cd packages/terminal && node -e "require('flexlayout-react'); console.log('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add packages/terminal/package.json packages/terminal/package-lock.json
git commit -m "chore(terminal): install flexlayout-react for widget layout system"
```

---

## Task 2: Create rate limiter service

**Files:**
- Create: `src/services/rateLimiter.js`
- Create: `src/services/__tests__/rateLimiter.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
// src/services/__tests__/rateLimiter.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { RateLimiter } from '../rateLimiter'

describe('RateLimiter', () => {
  it('allows requests within limit', () => {
    const limiter = new RateLimiter({ tokensPerSecond: 10, bucketSize: 10 })
    for (let i = 0; i < 10; i++) {
      expect(limiter.tryConsume()).toBe(true)
    }
  })

  it('rejects requests over limit', () => {
    const limiter = new RateLimiter({ tokensPerSecond: 2, bucketSize: 2 })
    expect(limiter.tryConsume()).toBe(true)
    expect(limiter.tryConsume()).toBe(true)
    expect(limiter.tryConsume()).toBe(false)
  })

  it('refills tokens over time', () => {
    vi.useFakeTimers()
    const limiter = new RateLimiter({ tokensPerSecond: 10, bucketSize: 10 })
    // Drain all tokens
    for (let i = 0; i < 10; i++) limiter.tryConsume()
    expect(limiter.tryConsume()).toBe(false)
    // Advance 500ms → should have ~5 tokens
    vi.advanceTimersByTime(500)
    expect(limiter.tryConsume()).toBe(true)
    vi.useRealTimers()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/terminal && npx vitest run src/services/__tests__/rateLimiter.test.js`
Expected: FAIL — module not found

- [ ] **Step 3: Write implementation**

```javascript
// src/services/rateLimiter.js
export class RateLimiter {
  constructor({ tokensPerSecond, bucketSize }) {
    this.tokensPerSecond = tokensPerSecond
    this.bucketSize = bucketSize
    this.tokens = bucketSize
    this.lastRefill = Date.now()
  }

  tryConsume(count = 1) {
    this._refill()
    if (this.tokens >= count) {
      this.tokens -= count
      return true
    }
    return false
  }

  _refill() {
    const now = Date.now()
    const elapsed = (now - this.lastRefill) / 1000
    this.tokens = Math.min(this.bucketSize, this.tokens + elapsed * this.tokensPerSecond)
    this.lastRefill = now
  }
}

// Pre-configured limiters matching OpenAlgo rate limits
export const orderLimiter = new RateLimiter({ tokensPerSecond: 10, bucketSize: 10 })
export const smartOrderLimiter = new RateLimiter({ tokensPerSecond: 2, bucketSize: 2 })
export const generalLimiter = new RateLimiter({ tokensPerSecond: 50, bucketSize: 50 })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/terminal && npx vitest run src/services/__tests__/rateLimiter.test.js`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/terminal/src/services/rateLimiter.js packages/terminal/src/services/__tests__/rateLimiter.test.js
git commit -m "feat(terminal): add token-bucket rate limiter for OpenAlgo API protection"
```

---

## Task 3: Create DataBus service

**Files:**
- Create: `src/services/dataBus.js`
- Create: `src/services/__tests__/dataBus.test.js`
- Create: `src/hooks/useDataBus.js`

- [ ] **Step 1: Write the failing test**

```javascript
// src/services/__tests__/dataBus.test.js
import { describe, it, expect, vi } from 'vitest'
import { DataBus } from '../dataBus'

describe('DataBus', () => {
  it('broadcasts data to all subscribers of a topic', () => {
    const bus = new DataBus()
    const cb1 = vi.fn()
    const cb2 = vi.fn()
    bus.subscribe('positions', cb1)
    bus.subscribe('positions', cb2)
    bus.publish('positions', [{ symbol: 'NIFTY' }])
    expect(cb1).toHaveBeenCalledWith([{ symbol: 'NIFTY' }])
    expect(cb2).toHaveBeenCalledWith([{ symbol: 'NIFTY' }])
  })

  it('does not broadcast to unsubscribed callbacks', () => {
    const bus = new DataBus()
    const cb = vi.fn()
    bus.subscribe('positions', cb)
    bus.unsubscribe('positions', cb)
    bus.publish('positions', [])
    expect(cb).not.toHaveBeenCalled()
  })

  it('caches last value per topic', () => {
    const bus = new DataBus()
    bus.publish('quotes:NIFTY', { ltp: 23581 })
    expect(bus.getLastValue('quotes:NIFTY')).toEqual({ ltp: 23581 })
  })

  it('returns null for topics with no data', () => {
    const bus = new DataBus()
    expect(bus.getLastValue('nonexistent')).toBeNull()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/terminal && npx vitest run src/services/__tests__/dataBus.test.js`
Expected: FAIL

- [ ] **Step 3: Write DataBus implementation**

```javascript
// src/services/dataBus.js
class DataBus {
  constructor() {
    this.subscriptions = new Map()
    this.cache = new Map()
  }

  subscribe(topic, callback) {
    if (!this.subscriptions.has(topic)) {
      this.subscriptions.set(topic, new Set())
    }
    this.subscriptions.get(topic).add(callback)
    // Immediately deliver cached value if available
    const cached = this.cache.get(topic)
    if (cached) callback(cached.data)
    return () => this.unsubscribe(topic, callback)
  }

  unsubscribe(topic, callback) {
    this.subscriptions.get(topic)?.delete(callback)
  }

  publish(topic, data) {
    this.cache.set(topic, { data, timestamp: Date.now() })
    this.subscriptions.get(topic)?.forEach(cb => {
      try { cb(data) } catch (e) { console.error(`DataBus error [${topic}]:`, e) }
    })
  }

  getLastValue(topic) {
    return this.cache.get(topic)?.data ?? null
  }

  getLastTimestamp(topic) {
    return this.cache.get(topic)?.timestamp ?? null
  }

  isStale(topic, maxAgeMs = 10000) {
    const ts = this.getLastTimestamp(topic)
    if (!ts) return true
    return Date.now() - ts > maxAgeMs
  }

  clear() {
    this.subscriptions.clear()
    this.cache.clear()
  }
}

// Singleton — all widgets share one DataBus
export const dataBus = new DataBus()
export { DataBus }
```

- [ ] **Step 4: Write useDataBus hook**

```javascript
// src/hooks/useDataBus.js
import { useState, useEffect, useCallback } from 'react'
import { dataBus } from '../services/dataBus'

export function useDataBus(topic) {
  const [data, setData] = useState(() => dataBus.getLastValue(topic))
  const [isStale, setIsStale] = useState(() => dataBus.isStale(topic))

  useEffect(() => {
    const unsubscribe = dataBus.subscribe(topic, (newData) => {
      setData(newData)
      setIsStale(false)
    })

    // Check staleness every 5s
    const interval = setInterval(() => {
      setIsStale(dataBus.isStale(topic))
    }, 5000)

    return () => {
      unsubscribe()
      clearInterval(interval)
    }
  }, [topic])

  const refresh = useCallback(() => {
    // Trigger a manual fetch — widgets call this, DataBus handles dedup
    dataBus.publish(`${topic}:refresh`, Date.now())
  }, [topic])

  return { data, isStale, refresh }
}
```

- [ ] **Step 5: Run tests**

Run: `cd packages/terminal && npx vitest run src/services/__tests__/dataBus.test.js`
Expected: 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/terminal/src/services/dataBus.js packages/terminal/src/services/__tests__/dataBus.test.js packages/terminal/src/hooks/useDataBus.js
git commit -m "feat(terminal): add DataBus for centralized data subscriptions across widgets"
```

---

## Task 4: Create layout store and presets

**Files:**
- Create: `src/layout/layoutStore.js`
- Create: `src/layout/presets/minimal.json`
- Create: `src/layout/presets/scalper-zone.json`
- Create: `src/layout/presets/blank.json`

- [ ] **Step 1: Write layoutStore**

```javascript
// src/layout/layoutStore.js
const STORAGE_KEY = 'flinttrade:layouts'
const ACTIVE_KEY = 'flinttrade:activeLayout'

export function saveLayout(id, name, modelJson) {
  const layouts = getAllLayouts()
  layouts[id] = { id, name, model: modelJson, updatedAt: Date.now() }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts))
}

export function loadLayout(id) {
  const layouts = getAllLayouts()
  return layouts[id]?.model ?? null
}

export function getAllLayouts() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
  } catch {
    return {}
  }
}

export function deleteLayout(id) {
  const layouts = getAllLayouts()
  delete layouts[id]
  localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts))
}

export function renameLayout(id, newName) {
  const layouts = getAllLayouts()
  if (layouts[id]) {
    layouts[id].name = newName
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts))
  }
}

export function getActiveLayoutId() {
  return localStorage.getItem(ACTIVE_KEY) || null
}

export function setActiveLayoutId(id) {
  localStorage.setItem(ACTIVE_KEY, id)
}

export function generateLayoutId() {
  return `LAY-${Date.now()}${Math.random().toString(36).slice(2, 8)}`
}
```

- [ ] **Step 2: Create preset JSON files**

```json
// src/layout/presets/minimal.json
{
  "global": {
    "splitterSize": 4,
    "tabEnableClose": true,
    "tabSetEnableMaximize": true,
    "tabSetEnableTabStrip": true
  },
  "layout": {
    "type": "row",
    "children": [
      {
        "type": "tabset",
        "weight": 70,
        "children": [
          { "type": "tab", "name": "Chart", "component": "chart" }
        ]
      },
      {
        "type": "tabset",
        "weight": 30,
        "children": [
          { "type": "tab", "name": "Positions", "component": "positions" },
          { "type": "tab", "name": "Orders", "component": "orders" }
        ]
      }
    ]
  }
}
```

```json
// src/layout/presets/scalper-zone.json
{
  "global": {
    "splitterSize": 4,
    "tabEnableClose": true,
    "tabSetEnableMaximize": true
  },
  "layout": {
    "type": "row",
    "children": [
      {
        "type": "tabset",
        "weight": 70,
        "children": [
          { "type": "tab", "name": "Scalper", "component": "scalper" }
        ]
      },
      {
        "type": "tabset",
        "weight": 30,
        "children": [
          { "type": "tab", "name": "Positions", "component": "positions" },
          { "type": "tab", "name": "Orders", "component": "orders" },
          { "type": "tab", "name": "Option Chain", "component": "optionchain" }
        ]
      }
    ]
  }
}
```

```json
// src/layout/presets/blank.json
{
  "global": {
    "splitterSize": 4,
    "tabEnableClose": true,
    "tabSetEnableMaximize": true
  },
  "layout": {
    "type": "row",
    "children": [
      {
        "type": "tabset",
        "children": []
      }
    ]
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add packages/terminal/src/layout/
git commit -m "feat(terminal): add layout store and preset JSON files for FlexLayout"
```

---

## Task 5: Create widget factory

**Files:**
- Create: `src/layout/widgetFactory.jsx`

- [ ] **Step 1: Write widget factory**

```jsx
// src/layout/widgetFactory.jsx
import { lazy, Suspense } from 'react'

// Lazy-load all widgets for code splitting
const widgets = {
  // Trading widgets
  dashboard: lazy(() => import('../widgets/trading/Dashboard/DashboardWidget')),
  scalper: lazy(() => import('../widgets/trading/Scalper/ScalperWidget')),
  positions: lazy(() => import('../widgets/trading/Positions/PositionsWidget')),
  orders: lazy(() => import('../widgets/trading/Orders/OrdersWidget')),

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
  { id: 'scalper', name: 'Scalper', icon: 'TrendingUp', category: 'Trading' },
  { id: 'positions', name: 'Positions', icon: 'Table2', category: 'Trading' },
  { id: 'orders', name: 'Orders', icon: 'ClipboardList', category: 'Trading' },
  { id: 'chart', name: 'Chart', icon: 'CandlestickChart', category: 'Analysis' },
  { id: 'optionchain', name: 'Option Chain', icon: 'Grid3x3', category: 'Analysis' },
  { id: 'oichart', name: 'OI Chart', icon: 'BarChart3', category: 'Analysis' },
  { id: 'watchlist', name: 'Watchlist', icon: 'Star', category: 'Utility' },
]

function WidgetFallback() {
  return (
    <div className="flex items-center justify-center h-full text-text-secondary">
      Loading...
    </div>
  )
}

function WidgetError({ name }) {
  return (
    <div className="flex items-center justify-center h-full text-loss">
      Widget "{name}" failed to load
    </div>
  )
}

// FlexLayout factory function — maps node.getComponent() to React component
export function widgetFactory(node) {
  const component = node.getComponent()
  const Widget = widgets[component]

  if (!Widget) {
    return <WidgetError name={component} />
  }

  return (
    <Suspense fallback={<WidgetFallback />}>
      <Widget node={node} />
    </Suspense>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add packages/terminal/src/layout/widgetFactory.jsx
git commit -m "feat(terminal): add widget factory with lazy loading and catalog"
```

---

## Task 6: Create chrome shell components

**Files:**
- Create: `src/chrome/TopBar.jsx`
- Create: `src/chrome/TickerBar.jsx`
- Create: `src/chrome/WidgetPicker.jsx`
- Create: `src/chrome/ToolsDropdown.jsx`

- [ ] **Step 1: Write TopBar**

```jsx
// src/chrome/TopBar.jsx
import { useState, useEffect } from 'react'
import { Settings, Grid3x3, Wrench, User, Maximize } from 'lucide-react'
import { ping } from '../services/api'

function ISTClock() {
  const [time, setTime] = useState('')
  useEffect(() => {
    const tick = () => setTime(new Date().toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    }))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])
  return <span className="font-mono text-xs text-text-secondary">{time} IST</span>
}

export default function TopBar({ layoutTabs, activeTab, onTabSelect, onNewLayout, onWidgetPicker, onToolsMenu }) {
  const [connected, setConnected] = useState(false)
  const [broker, setBroker] = useState('')

  useEffect(() => {
    const check = async () => {
      try {
        const res = await ping()
        setConnected(true)
        setBroker(res?.broker || '')
      } catch { setConnected(false) }
    }
    check()
    const id = setInterval(check, 10000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="h-10 bg-surface-card border-b border-border-default flex items-center justify-between px-3 select-none">
      {/* Left: Logo + Layout Tabs */}
      <div className="flex items-center gap-3">
        <span className="text-profit font-bold text-lg tracking-tight">FT</span>
        <div className="flex items-center gap-1">
          {layoutTabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => onTabSelect(tab.id)}
              className={`px-3 py-1 text-xs rounded transition-colors ${
                tab.id === activeTab
                  ? 'bg-surface-hover text-text-primary'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              {tab.name}
            </button>
          ))}
          <button
            onClick={onNewLayout}
            className="px-2 py-1 text-xs text-text-muted hover:text-text-primary"
          >+</button>
        </div>
      </div>

      {/* Right: Tools + Widgets + Status + Clock */}
      <div className="flex items-center gap-3">
        <button onClick={onToolsMenu} className="flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary">
          <Wrench size={14} /> TOOLS
        </button>
        <button onClick={onWidgetPicker} className="flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary">
          <Grid3x3 size={14} /> WIDGETS
        </button>
        <div className="flex items-center gap-1.5">
          <div className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-profit' : 'bg-loss'}`} />
          <span className="text-xs text-text-secondary">{broker || 'Disconnected'}</span>
        </div>
        <ISTClock />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Write TickerBar**

```jsx
// src/chrome/TickerBar.jsx
import { useDataBus } from '../hooks/useDataBus'

const INDICES = [
  { symbol: 'NIFTY', exchange: 'NSE_INDEX', name: 'NIFTY 50' },
  { symbol: 'SENSEX', exchange: 'BSE_INDEX', name: 'SENSEX' },
  { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', name: 'BANK NIFTY' },
  { symbol: 'INDIA VIX', exchange: 'NSE_INDEX', name: 'VIX' },
]

function IndexChip({ symbol, exchange, name }) {
  const { data } = useDataBus(`quote:${symbol}:${exchange}`)
  const ltp = data?.ltp ?? '—'
  const change = data?.change ?? 0
  const pct = data?.pct ?? 0
  const isUp = change >= 0

  return (
    <div className="flex items-center gap-2 px-3 py-1 shrink-0">
      <span className="text-xs text-text-secondary">{name}</span>
      <span className="text-xs font-mono text-text-primary">{typeof ltp === 'number' ? ltp.toLocaleString('en-IN') : ltp}</span>
      <span className={`text-xs font-mono ${isUp ? 'text-profit' : 'text-loss'}`}>
        {isUp ? '▲' : '▼'}{Math.abs(pct).toFixed(2)}%
      </span>
    </div>
  )
}

export default function TickerBar() {
  return (
    <div className="h-7 bg-surface-base border-b border-border-subtle flex items-center overflow-x-auto scrollbar-none">
      {INDICES.map(idx => (
        <IndexChip key={idx.symbol} {...idx} />
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Write WidgetPicker popup**

```jsx
// src/chrome/WidgetPicker.jsx
import { X } from 'lucide-react'
import * as icons from 'lucide-react'
import { widgetCatalog } from '../layout/widgetFactory'

export default function WidgetPicker({ isOpen, onClose, onAddWidget }) {
  if (!isOpen) return null

  const categories = [...new Set(widgetCatalog.map(w => w.category))]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-surface-card border border-border-default rounded-lg p-6 w-[500px] max-h-[80vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-text-primary">Widgets</h2>
          <button onClick={onClose}><X size={18} className="text-text-secondary" /></button>
        </div>
        {categories.map(cat => (
          <div key={cat} className="mb-4">
            <h3 className="text-xs uppercase text-text-muted mb-2">{cat}</h3>
            <div className="grid grid-cols-4 gap-2">
              {widgetCatalog.filter(w => w.category === cat).map(widget => {
                const Icon = icons[widget.icon] || icons.Box
                return (
                  <button
                    key={widget.id}
                    onClick={() => { onAddWidget(widget.id, widget.name); onClose() }}
                    className="flex flex-col items-center gap-1 p-3 rounded hover:bg-surface-hover transition-colors"
                  >
                    <Icon size={20} className="text-text-secondary" />
                    <span className="text-xs text-text-primary">{widget.name}</span>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Write ToolsDropdown**

```jsx
// src/chrome/ToolsDropdown.jsx
import { useState, useRef, useEffect } from 'react'
import { BarChart3, FlaskConical, Workflow, BookOpen, Settings, Brain, PieChart } from 'lucide-react'

const TOOLS = [
  { id: 'pnl-dashboard', name: 'P&L Dashboard', icon: PieChart },
  { id: 'strategy-builder', name: 'Strategy Builder', icon: Brain },
  { id: 'market-intelligence', name: 'Market Intelligence', icon: BarChart3 },
  { id: 'backtest-lab', name: 'Backtest Lab', icon: FlaskConical },
  { id: 'flow-builder', name: 'Flow Builder', icon: Workflow },
  { id: 'trade-journal', name: 'Trade Journal', icon: BookOpen },
  { id: 'settings', name: 'Settings', icon: Settings },
]

export default function ToolsDropdown({ isOpen, onClose, onSelectTool }) {
  const ref = useRef(null)

  useEffect(() => {
    const handleClick = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose() }
    if (isOpen) document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div ref={ref} className="absolute right-24 top-10 z-40 bg-surface-card border border-border-default rounded-lg shadow-xl py-1 w-52">
      {TOOLS.map(tool => {
        const Icon = tool.icon
        return (
          <button
            key={tool.id}
            onClick={() => { onSelectTool(tool.id); onClose() }}
            className="w-full flex items-center gap-2 px-4 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
          >
            <Icon size={16} />
            {tool.name}
          </button>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 5: Commit**

```bash
git add packages/terminal/src/chrome/
git commit -m "feat(terminal): add chrome shell components (TopBar, TickerBar, WidgetPicker, ToolsDropdown)"
```

---

## Task 7: Create LayoutManager (FlexLayout wrapper)

**Files:**
- Create: `src/layout/LayoutManager.jsx`

- [ ] **Step 1: Write LayoutManager**

```jsx
// src/layout/LayoutManager.jsx
import { useRef, useCallback } from 'react'
import { Layout, Model, Actions } from 'flexlayout-react'
import 'flexlayout-react/style/dark.css'
import { widgetFactory } from './widgetFactory'

export default function LayoutManager({ model, onModelChange, onAddWidget }) {
  const layoutRef = useRef(null)

  const factory = useCallback((node) => {
    return widgetFactory(node)
  }, [])

  const handleAddWidget = useCallback((componentId, name) => {
    if (!layoutRef.current) return
    layoutRef.current.addTabToActiveTabSet({
      type: 'tab',
      name,
      component: componentId,
    })
  }, [])

  // Expose addWidget for external use (WidgetPicker)
  if (onAddWidget) {
    onAddWidget.current = handleAddWidget
  }

  return (
    <div className="flex-1 relative">
      <Layout
        ref={layoutRef}
        model={model}
        factory={factory}
        onModelChange={onModelChange}
        font={{ size: '12px', family: 'Inter, system-ui, sans-serif' }}
      />
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add packages/terminal/src/layout/LayoutManager.jsx
git commit -m "feat(terminal): add FlexLayout LayoutManager wrapper"
```

---

## Task 8: Migrate existing modules to widget structure

**Files:**
- Move: `src/modules/Dashboard.jsx` → `src/widgets/trading/Dashboard/DashboardWidget.jsx`
- Move: `src/modules/OptionChain.jsx` → `src/widgets/analysis/OptionChain/OptionChainWidget.jsx`
- Move: `src/modules/Scalper.jsx` → `src/widgets/trading/Scalper/ScalperWidget.jsx`
- Create: `src/widgets/trading/Positions/PositionsWidget.jsx` (extract from Portfolio.jsx)
- Create: `src/widgets/trading/Orders/OrdersWidget.jsx` (extract from Portfolio.jsx)
- Create: `src/widgets/analysis/Chart/ChartWidget.jsx` (wrap Chart.jsx)
- Create: `src/widgets/analysis/OIChart/OIChartWidget.jsx` (from FuturesOI.jsx)
- Create: `src/widgets/utility/Watchlist/WatchlistWidget.jsx` (new)
- Move: `src/modules/Settings.jsx` → `src/tools/Settings/SettingsTool.jsx`
- Move: `src/modules/Journal.jsx` → `src/tools/TradeJournal/TradeJournalTool.jsx`
- Move: `src/modules/Backtest.jsx` → `src/tools/BacktestLab/BacktestLabTool.jsx`
- Move: `src/modules/Strategy.jsx` → `src/tools/StrategyBuilder/StrategyBuilderTool.jsx`

- [ ] **Step 1: Create directory structure**

```bash
cd packages/terminal/src
mkdir -p widgets/trading/Dashboard widgets/trading/Scalper widgets/trading/Positions widgets/trading/Orders
mkdir -p widgets/analysis/Chart widgets/analysis/OptionChain widgets/analysis/OIChart
mkdir -p widgets/utility/Watchlist
mkdir -p tools/Settings tools/TradeJournal tools/BacktestLab tools/StrategyBuilder tools/PnLDashboard tools/MarketIntelligence tools/FlowBuilder
```

- [ ] **Step 2: Move each module to its new location**

For each file: copy the existing module, add `export default` wrapper, keep all existing logic intact. The key change is each widget receives a `node` prop from FlexLayout but doesn't need to use it initially.

Example transformation (Dashboard):
```jsx
// src/widgets/trading/Dashboard/DashboardWidget.jsx
// Copied from modules/Dashboard.jsx with minimal changes:
// 1. Rename function: DashboardModule → DashboardWidget
// 2. Add default export
// 3. Accept { node } prop (from FlexLayout, unused for now)

import { useState, useEffect } from 'react'
// ... rest of existing Dashboard code, unchanged ...

export default function DashboardWidget({ node }) {
  // Exact same code as DashboardModule
  // ...
}
```

Repeat for all 9 modules → widgets/tools.

- [ ] **Step 3: Create PositionsWidget (extracted from Portfolio.jsx)**

Extract the Positions tab content from Portfolio.jsx into its own widget. Same pattern for OrdersWidget.

- [ ] **Step 4: Create ChartWidget wrapper**

```jsx
// src/widgets/analysis/Chart/ChartWidget.jsx
import Chart from '../../../components/Chart'

export default function ChartWidget({ node }) {
  return (
    <div className="h-full w-full">
      <Chart symbol="NIFTY" exchange="NSE_INDEX" />
    </div>
  )
}
```

- [ ] **Step 5: Create WatchlistWidget (minimal)**

```jsx
// src/widgets/utility/Watchlist/WatchlistWidget.jsx
import { useState } from 'react'

const DEFAULT_SYMBOLS = [
  { symbol: 'NIFTY', exchange: 'NSE_INDEX', name: 'NIFTY 50' },
  { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', name: 'BANK NIFTY' },
  { symbol: 'SBIN', exchange: 'NSE', name: 'SBI' },
  { symbol: 'RELIANCE', exchange: 'NSE', name: 'Reliance' },
]

export default function WatchlistWidget({ node }) {
  const [symbols] = useState(DEFAULT_SYMBOLS)

  return (
    <div className="h-full overflow-auto p-2">
      <div className="text-xs text-text-muted uppercase mb-2">Watchlist</div>
      {symbols.map(s => (
        <div key={s.symbol} className="flex justify-between items-center py-1.5 px-2 hover:bg-surface-hover rounded cursor-pointer text-sm">
          <span className="text-text-primary">{s.name}</span>
          <span className="font-mono text-text-secondary">—</span>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 6: Commit**

```bash
git add packages/terminal/src/widgets/ packages/terminal/src/tools/
git commit -m "feat(terminal): migrate modules to widget/tool structure for FlexLayout"
```

---

## Task 9: Rewrite App.jsx (chrome shell + FlexLayout)

**Files:**
- Rewrite: `src/App.jsx`

- [ ] **Step 1: Write new App.jsx**

```jsx
// src/App.jsx
import { useState, useRef, useCallback, useEffect } from 'react'
import { Model } from 'flexlayout-react'
import TopBar from './chrome/TopBar'
import TickerBar from './chrome/TickerBar'
import WidgetPicker from './chrome/WidgetPicker'
import ToolsDropdown from './chrome/ToolsDropdown'
import LayoutManager from './layout/LayoutManager'
import { loadLayout, saveLayout, getAllLayouts, getActiveLayoutId, setActiveLayoutId, generateLayoutId } from './layout/layoutStore'
import minimalPreset from './layout/presets/minimal.json'

// Tools (lazy loaded, full-page)
import { lazy, Suspense } from 'react'
const tools = {
  'settings': lazy(() => import('./tools/Settings/SettingsTool')),
  'backtest-lab': lazy(() => import('./tools/BacktestLab/BacktestLabTool')),
  'trade-journal': lazy(() => import('./tools/TradeJournal/TradeJournalTool')),
  'strategy-builder': lazy(() => import('./tools/StrategyBuilder/StrategyBuilderTool')),
}

export default function App() {
  // Layout state
  const [layoutTabs, setLayoutTabs] = useState(() => {
    const saved = getAllLayouts()
    const entries = Object.values(saved)
    if (entries.length > 0) return entries.map(e => ({ id: e.id, name: e.name }))
    const id = generateLayoutId()
    return [{ id, name: 'Workspace' }]
  })
  const [activeTab, setActiveTab] = useState(() => getActiveLayoutId() || layoutTabs[0]?.id)
  const [model, setModel] = useState(() => {
    const saved = loadLayout(activeTab)
    return Model.fromJson(saved || minimalPreset)
  })

  // UI state
  const [widgetPickerOpen, setWidgetPickerOpen] = useState(false)
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false)
  const [activeTool, setActiveTool] = useState(null) // null = show layout, string = show tool

  // Widget add ref
  const addWidgetRef = useRef(null)

  // Save layout on change
  const handleModelChange = useCallback((newModel) => {
    setModel(newModel)
    const tab = layoutTabs.find(t => t.id === activeTab)
    if (tab) saveLayout(activeTab, tab.name, newModel.toJson())
  }, [activeTab, layoutTabs])

  // Switch layout tab
  const handleTabSelect = useCallback((id) => {
    // Save current layout first
    const currentTab = layoutTabs.find(t => t.id === activeTab)
    if (currentTab) saveLayout(activeTab, currentTab.name, model.toJson())

    setActiveTab(id)
    setActiveLayoutId(id)
    const saved = loadLayout(id)
    setModel(Model.fromJson(saved || minimalPreset))
    setActiveTool(null)
  }, [activeTab, layoutTabs, model])

  // New layout
  const handleNewLayout = useCallback(() => {
    const id = generateLayoutId()
    const name = `Layout ${layoutTabs.length + 1}`
    setLayoutTabs(prev => [...prev, { id, name }])
    saveLayout(id, name, minimalPreset)
    setActiveTab(id)
    setActiveLayoutId(id)
    setModel(Model.fromJson(minimalPreset))
    setActiveTool(null)
  }, [layoutTabs])

  // Add widget from picker
  const handleAddWidget = useCallback((componentId, name) => {
    if (addWidgetRef.current) {
      addWidgetRef.current(componentId, name)
    }
  }, [])

  // Open tool (replaces layout)
  const handleSelectTool = useCallback((toolId) => {
    setActiveTool(toolId)
  }, [])

  // Global Escape to close tool
  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === 'Escape' && activeTool) setActiveTool(null)
      if (e.key === 'Escape' && widgetPickerOpen) setWidgetPickerOpen(false)
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [activeTool, widgetPickerOpen])

  const ToolComponent = activeTool ? tools[activeTool] : null

  return (
    <div className="h-screen flex flex-col bg-surface-base text-text-primary overflow-hidden">
      <TopBar
        layoutTabs={layoutTabs}
        activeTab={activeTab}
        onTabSelect={handleTabSelect}
        onNewLayout={handleNewLayout}
        onWidgetPicker={() => setWidgetPickerOpen(true)}
        onToolsMenu={() => setToolsMenuOpen(!toolsMenuOpen)}
      />
      <TickerBar />

      {/* Tools dropdown */}
      <ToolsDropdown
        isOpen={toolsMenuOpen}
        onClose={() => setToolsMenuOpen(false)}
        onSelectTool={handleSelectTool}
      />

      {/* Main content: either FlexLayout canvas or full-page tool */}
      {activeTool && ToolComponent ? (
        <div className="flex-1 overflow-auto">
          <Suspense fallback={<div className="flex items-center justify-center h-full text-text-secondary">Loading...</div>}>
            <ToolComponent onClose={() => setActiveTool(null)} />
          </Suspense>
        </div>
      ) : (
        <LayoutManager
          model={model}
          onModelChange={handleModelChange}
          onAddWidget={addWidgetRef}
        />
      )}

      {/* Widget picker popup */}
      <WidgetPicker
        isOpen={widgetPickerOpen}
        onClose={() => setWidgetPickerOpen(false)}
        onAddWidget={handleAddWidget}
      />
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add packages/terminal/src/App.jsx
git commit -m "feat(terminal): rewrite App.jsx with chrome shell + FlexLayout canvas + tools system"
```

---

## Task 10: Add FlexLayout dark theme CSS overrides

**Files:**
- Modify: `src/index.css`

- [ ] **Step 1: Add FlexLayout dark theme overrides**

Add to the end of `index.css`:

```css
/* FlexLayout dark theme overrides */
.flexlayout__layout {
  --color-1: #0a0a0f;
  --color-2: #12121a;
  --color-3: #1e1e2e;
  --color-4: #16161f;
  --color-text: #e4e4e7;
  --color-drag1: #3b82f680;
  --color-drag2: #3b82f640;
  background-color: var(--color-1);
}

.flexlayout__tab {
  background-color: var(--color-1);
  border-color: var(--color-3);
}

.flexlayout__tabset_header,
.flexlayout__tabset-selected,
.flexlayout__tab_button--selected {
  background-color: var(--color-2);
}

.flexlayout__tab_button {
  color: var(--color-text);
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 12px;
}

.flexlayout__splitter {
  background-color: var(--color-4);
}

.flexlayout__splitter:hover {
  background-color: var(--color-3);
}

.flexlayout__tab_toolbar_button {
  color: #71717a;
}

.flexlayout__tab_toolbar_button:hover {
  color: #e4e4e7;
  background-color: var(--color-2);
}
```

- [ ] **Step 2: Commit**

```bash
git add packages/terminal/src/index.css
git commit -m "style(terminal): add FlexLayout dark theme overrides matching FlintTrade theme"
```

---

## Task 11: Delete stub packages and old modules directory

**Files:**
- Delete: `packages/dashboard/` (entire directory)
- Delete: `packages/backtest/` (entire directory)
- Delete: `src/modules/` (replaced by widgets/ and tools/)
- Delete: `src/hooks/useKeyboard.js` (global shortcuts removed — individual widgets handle their own)

- [ ] **Step 1: Delete packages**

```bash
rm -rf packages/dashboard packages/backtest
rm -rf packages/terminal/src/modules
rm packages/terminal/src/hooks/useKeyboard.js
```

- [ ] **Step 2: Update Makefile — remove ports 5174/5175 references**

Check Makefile for any references to dashboard or backtest packages and remove them.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove dashboard/backtest stub packages, migrate modules to widgets/tools"
```

---

## Task 12: Verify build and test

- [ ] **Step 1: Install dependencies**

```bash
cd packages/terminal && npm install
```

- [ ] **Step 2: Run tests**

```bash
cd packages/terminal && npx vitest run
```
Expected: All existing tests pass + new rate limiter + DataBus tests pass

- [ ] **Step 3: Dev server**

```bash
cd packages/terminal && npm run dev
```
Expected: App loads at http://localhost:5173 with:
- TopBar (FT logo, clock, layout tab, TOOLS, WIDGETS buttons)
- TickerBar (index prices, data shows "—" until OpenAlgo connected)
- FlexLayout canvas with Minimal preset (Chart left, Positions+Orders right)
- Clicking WIDGETS opens the picker popup
- Clicking TOOLS shows dropdown
- Dragging tabs between panels works
- Splitter resize works

- [ ] **Step 4: Production build**

```bash
cd packages/terminal && npm run build
```
Expected: Build completes without errors

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(terminal): Phase 1 complete — FlexLayout widget workspace foundation"
```

---

## Summary

After Phase 1, the terminal is transformed from a fixed-sidebar module app to a composable widget workspace:

- **Chrome shell**: TopBar + TickerBar (always visible)
- **FlexLayout canvas**: Drag, drop, resize, tab, maximize any widget
- **8 widgets**: Dashboard, Scalper, Positions, Orders, Chart, OptionChain, OIChart, Watchlist
- **7 tools** (full-page): P&L Dashboard, Strategy Builder, Market Intelligence, Backtest Lab, Flow Builder, Trade Journal, Settings
- **Layout persistence**: Save/load layouts to localStorage
- **Layout tabs**: Multiple layouts, switch between them
- **DataBus**: Centralized data subscriptions, no duplicate API calls
- **Rate limiter**: Token-bucket protecting OpenAlgo API
- **Preset layouts**: Minimal, Scalper Zone, Blank (more to come)
- **Code splitting**: Every widget lazy-loaded, errors isolated per widget

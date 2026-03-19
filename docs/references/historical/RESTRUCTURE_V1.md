# FlintTrade v2 — Complete Restructuring Blueprint

> **Date:** 2026-03-18 | **Version:** 2.0 (replaces v1)
> **Input:** 222 repos, 83+ screenshots, 4 platform deep-dives, 3 blueprint docs, full DOM analysis
> **Principle:** Widget-composable workspace. User builds their own terminal. No fixed layouts.

---

## PART 1: THE ARCHITECTURE DECISION

### What Groww 915 Actually Is

Groww 915 is NOT a multi-page app with a sidebar. It is a **docking layout manager** where:

1. **Top Bar** (fixed) — Logo, clock, layout tabs, P&L summary, TOOLS dropdown, WIDGETS button
2. **Ticker Bar** (fixed) — Scrolling index prices
3. **FlexLayout Canvas** (user-customizable) — Users drag widgets into rows/columns/tabs
4. **Tools** (full-page) — P&L Dashboard, Strategy Builder, etc. replace the canvas temporarily

The library is **`flexlayout-react`** by Caplin (confirmed from Groww's DOM). It uses a JSON model:

```
Model (JSON tree)
├── global (config: splitter size, tab close, etc.)
├── layout (row → tabset → tab hierarchy)
└── borders (edge-docked persistent panels)
```

Layouts are saved/restored via `model.toJson()` / `Model.fromJson()`. This is how presets and user-saved layouts work.

### FlintTrade Must Follow This Pattern

**DELETE the concept of F1-F10 fixed modules with a sidebar.**

Replace with:
- A canvas of composable widgets
- Preset layouts for common workflows
- Users save custom layouts
- Multiple layouts open as tabs simultaneously
- Full-page tools accessible from dropdown

---

## PART 2: THE THREE UI LAYERS

### Layer 1: Chrome (always visible, never customizable)

```
┌────────────────────────────────────────────────────────────────────┐
│ [FT logo] [clock] │ [Layout 1] [Layout 2] [+] │ [P&L: ₹0] │     │
│                    │  (layout tabs)              │ [TOOLS ▼]  │     │
│                    │                             │ [WIDGETS]  │     │
│                    │                             │ [⚙] [👤]  │     │
├────────────────────────────────────────────────────────────────────┤
│ NIFTY 23581 ▲0.74% │ SENSEX 76070 ▲0.75% │ BANKNIFTY 54876 ▲0.85%│
│ VIX 13.45 ▼2.1%   │ GOLD 85200 ▲0.3%    │ CRUDE 5840 ▼0.5%      │
└────────────────────────────────────────────────────────────────────┘
```

Components:
- **Logo + IST Clock** — Always visible
- **Layout Tabs** — Switch between saved layouts (like browser tabs)
- **[+] Button** — Create new layout (from preset or blank)
- **Total P&L** — Portfolio P&L always visible
- **TOOLS Dropdown** — Opens full-page tools (replaces canvas)
- **WIDGETS Button** — Opens widget picker popup
- **Settings Gear** — Quick settings
- **Profile** — Account, broker status
- **Index Ticker Bar** — Scrolling horizontal bar with live prices

### Layer 2: FlexLayout Canvas (fully customizable)

The entire area below the ticker bar is a `flexlayout-react` container. Users arrange widgets by:
- Dragging widgets from the WIDGETS popup into the canvas
- Dragging tabs between tabsets to reorganize
- Dragging splitters to resize panels
- Clicking maximize to expand a tabset to full area
- Closing individual widget tabs
- The layout auto-saves to `~/.flinttrade/layouts/{layout-id}.json`

### Layer 3: Full-Page Tools (replace canvas temporarily)

Accessed from TOOLS dropdown. These are NOT widgets — they're full-page views:
- **P&L Dashboard** — Calendar heatmap, trade stats, streaks
- **Strategy Builder** — Multi-leg option strategy construction with payoff chart
- **Market Intelligence** — OiPulse-style 49-tool data hub (tabbed)
- **Backtest Lab** — Strategy testing, Monte Carlo, walk-forward
- **Flow Builder** — n8n-like visual workflow automation
- **Trade Journal** — Trade review, screenshots, notes, analytics
- **Settings** — Full configuration

When a tool is open, the layout canvas is hidden (not destroyed). Closing the tool returns to the layout.

---

## PART 3: WIDGET CATALOG (20 widgets)

Every widget is self-contained: own state, own data subscriptions, own keyboard handling when focused.

### Trading Widgets (6)

| Widget | Description | Key Features | Reference |
|--------|-------------|--------------|-----------|
| **Scalper** | 3-panel chart (Spot + CE + PE) with quick trade buttons | Shift+arrows when focused, one-click toggle, lot spinner, margin display, exit all | 1Cliq, INDmoney Flash, Groww Scalper |
| **Order Pad** | Standalone order entry form | Symbol search, order type, qty, price, product type, SL/target | 1Cliq order controls |
| **Positions** | Open positions table with live P&L | Per-position SL/target, asset-based SL, trailing SL, close/partial exit buttons, MTM display | All platforms |
| **Orders** | Order book (open, today, all) | Modify, cancel, status tracking, CSV export | All platforms |
| **Trade Book** | Executed trades list | Fill price, time, charges, P&L per trade | All platforms |
| **Holdings** | Delivery holdings | Current value, day change, overall return | INDmoney, 1Cliq |

### Analysis Widgets (7)

| Widget | Description | Key Features | Reference |
|--------|-------------|--------------|-----------|
| **Chart** | TradingView Advanced Chart | Multi-timeframe, indicators, drawing tools, OHLCV, volume, Buy/Sell overlay | Groww, INDmoney Terminal |
| **Option Chain** | Full chain table | LTP/OI/Greeks/IV/PCR toggle views, expiry selector, add-to-basket, moneyness badges, BUILD UP annotations | All platforms |
| **Straddle** | ATM straddle chart | Straddle/Spot/Synthetic Fut overlays, interval selector, straddle price readout | Groww, OiPulse |
| **OI Chart** | Open Interest bar chart | Call/Put OI per strike, increase/decrease filter, time scrubber, PCR, support/resistance labels | Groww, OiPulse |
| **Depth** | Market depth (5/20/50 level) | Bid/ask levels, order flow visualization, volume at price | Groww, fyers-websockets |
| **Greeks** | Portfolio Greeks dashboard | Net Delta/Gamma/Theta/Vega, per-position Greeks, risk graph | openalgo-portfoliogreeks |
| **Sector Map** | Sector heatmap (treemap) | Market cap sizing, % change coloring, drill-down to stocks | OiPulse, highcharts-heatmap |

### Utility Widgets (5)

| Widget | Description | Key Features | Reference |
|--------|-------------|--------------|-----------|
| **Watchlist** | Custom symbol lists | Multiple lists, LTP/change/volume, click to load in chart, drag to scalper | Groww, INDmoney |
| **Ticker** | Scrolling price ticker | Configurable symbols, horizontal scroll | Groww |
| **Calculator** | Margin/profit calculator | Margin required, breakeven, max profit/loss for strategies | Groww, 1Cliq |
| **News** | Financial news feed | Sentiment analysis (color-coded), source links, keyword filter | finnews-ai, OiPulse |
| **AI Advisor** | LLM-powered assistant | Natural language queries, trade suggestions, market analysis, voice input | openalgo-mcp, TradingAgents, Agent 915 |

### Risk Management Widgets (2)

| Widget | Description | Key Features | Reference |
|--------|-------------|--------------|-----------|
| **MTM Monitor** | Portfolio-level risk | MTM target/stoploss, auto-trailing loss, MTM hide/lock, +/- adjustment, alert on trigger | 1Cliq V1/V2 |
| **Risk Panel** | Position-level risk | Per-position SL (points/%), asset-based SL (index level), trailing SL type (static/trailing), predefined defaults | 1Cliq V2, Groww |

---

## PART 4: FULL-PAGE TOOLS (7 tools)

### Tool 1: P&L Dashboard
- Calendar heatmap (daily/monthly/yearly view)
- Net P&L, trade win %, profit factor
- Winning/losing streaks
- Profit/loss day counts
- Filter by F&O / Equity / Commodities
- Date range selector
- **From:** Groww 915

### Tool 2: Strategy Builder
- Strategy picker: Bullish / Bearish / Neutral templates
- Multi-leg builder (add call/put legs with strike, qty, buy/sell)
- Payoff chart (P&L at expiry)
- Strategy stats: Max Profit, Max Loss, Breakeven, Risk/Reward, POP
- Net portfolio Greeks
- Execute as basket order
- Easy mode (templates) / Custom mode (manual legs)
- **From:** Groww 915, INDmoney Strategy, OiPulse

### Tool 3: Market Intelligence (Pulse)
Tabbed interface with 5 sub-sections (50+ tools from OiPulse):

**Tab: OI Analysis** — OI Spurt (4-quadrant), OI Stats, Trending OI, Big OI Movement, Active Strikes OI/IV, Interval-wise OI, Multiple OI Chart, OI Expiry Analysis

**Tab: Futures** — Futures OI Analysis, OI Buzz heatmap, Market Movers, Banks Analysis, EOD OI Analyzer

**Tab: Market** — Sector Heatmap, Sector Stats, Index Contribution, World Indices, VIX chart, Pre-open, Open=High/Open=Low, RRG (Relative Rotation Graph), Delivery Data

**Tab: Institutional** — FII/DII Capital Market, FII/DII Derivatives, Participant-wise OI, FII Long/Short Ratio

**Tab: Signals** — Connecting Dots (multi-signal confluence: Trend/Dow/VIX/Volume/IV/OI/VWAP/ST/RSI/Price), D.H.B. alerts, Corporate Announcements

**From:** OiPulse (49 tools), sector-rotation-map

### Tool 4: Backtest Lab
- Strategy selector (12 built-in + custom upload)
- Parameter configuration
- Date range, symbol, interval
- Run with progress bar
- Results: Sharpe, Sortino, Max DD, Win Rate, Profit Factor, CAGR
- Equity curve + drawdown chart
- Trade-by-trade table
- Walk-forward optimization
- Monte Carlo (1000 paths, confidence intervals)
- Compare strategies side-by-side
- Export (CSV, PDF report)
- **From:** FlintTrade backtest-engine, raptorbt, openengine, vectorbt

### Tool 5: Flow Builder
- n8n-like visual workflow editor
- 30+ node types: triggers (cron, webhook, price alert), conditions (if/else, AND/OR), actions (place order, send telegram, log)
- Drag-drop canvas with connections
- Schedule triggers (market open, specific time, interval)
- Conditional branching (if NIFTY > 23600 then...)
- Multi-leg option strategy nodes
- WebSocket LTP feed nodes
- Test mode (dry run)
- **From:** openalgo-flow

### Tool 6: Trade Journal
- Daily trade log with notes
- Screenshot uploads (annotated charts)
- Tag system (scalp, swing, hedge, mistake)
- Analytics: win rate by tag, by time of day, by instrument
- Emotional state tracking (tilt detection)
- P&L attribution
- **From:** trading-journal, Groww P&L Dashboard

### Tool 7: Settings
- **General:** Theme (dark/light), density, font size
- **Trading Defaults:** Segment, symbol, product type, order type, qty, SL/target defaults
- **Risk:** MTM limits, max position size, max lots, margin alerts
- **Keyboard:** Customize scalper shortcuts (only relevant inside Scalper widget)
- **API:** OpenAlgo host/port/key, WebSocket port
- **LLM:** Provider, host, model, API key
- **Telegram:** Bot token, chat ID
- **Ditto:** Multi-account mirror config (parent/child, multiplier, allocation mode)
- **Automation:** Cron jobs (login, square-off, health), webhook URLs
- **Layouts:** Manage saved layouts, import/export
- **About:** Version, licenses, credits

---

## PART 5: LAYOUT PRESETS (8 presets)

Each preset is a FlexLayout JSON model file.

| Preset | Widgets Included | Use Case |
|--------|-----------------|----------|
| **Start Fresh** | Empty canvas with [+] | Power users who build from scratch |
| **Scalper Zone** | Scalper (large) + Positions + Orders (sidebar) | Option scalping |
| **Analysis Desk** | Chart (large) + Option Chain (right) + OI Chart (bottom) + Watchlist (left) | Pre-trade analysis |
| **Volatility Trading** | Chart + Straddle + OI Chart + Option Chain + Positions | Straddle/strangle traders |
| **Market Watch** | Watchlist (left) + Chart (center) + News (right) + Ticker (bottom) | Passive monitoring |
| **Risk Monitor** | Positions (large) + MTM Monitor + Greeks + Risk Panel | Risk management focus |
| **Data Cruncher** | Option Chain (large) + OI Chart + Depth + Greeks | Deep data analysis |
| **Minimal** | Chart + Positions | Beginners, clean view |

---

## PART 6: PYTHON PACKAGES — KEEP ALL 10, ADD 1

The Python backend is the strength. **Do not consolidate.** But add one:

| Package | Status | Serves Widget(s) / Tool(s) | Changes |
|---------|--------|---------------------------|---------|
| **core** | ✅ Done | ALL (OpenAlgo client, config, workspace) | Add layout persistence to workspace |
| **engine** | ✅ Done | Scalper, Order Pad (safety, routing, scheduler) | None |
| **data** | ✅ Done | ALL (audit, ticks, storage) | Add QuestDB adapter (from openquest) |
| **historical** | ✅ Done | Chart, Backtest Lab (OHLCV download) | Add expired F&O data (from ExpiryTrack) |
| **screener** | ✅ Done | Option Chain, OI Chart, Greeks, Sector Map | Add 49 OiPulse-level analysis functions |
| **backtest-engine** | ✅ Done | Backtest Lab (simulator, metrics, Monte Carlo) | Add Backtrader adapter (from openalgo-backtrader) |
| **ai** | ✅ Done | AI Advisor, News (LLM, RAG, sentiment) | Add multi-agent framework (from TradingAgents) |
| **integration** | ✅ Done | Flow Builder, webhooks, alerts | Add openalgo-flow node types |
| **automation** | ✅ Done | Settings > Automation (cron, telegram) | None |
| **ditto** | ✅ Done | Settings > Ditto (mirror, risk) | None |
| **indicators** | 🆕 NEW | Chart, Scalper, Strategy Builder | 100+ Numba indicators (from openalgo-indicator-skills), PineTS converter |

### CLI-Anything Integration (3 packages only)

```bash
/cli-anything packages/backtest-engine    → cli-backtest
/cli-anything packages/historical         → cli-historical
/cli-anything packages/screener           → cli-screener
```

Benefits: Agent discoverability (SKILL.md), batch scripting, audit trail, auto-generated tests.
NOT for: Order execution, real-time data, stateful workflows.

---

## PART 7: REACT CONSOLIDATION & FOLDER STRUCTURE

### Delete stub packages
```
packages/dashboard/  → DELETE (absorbed into terminal)
packages/backtest/   → DELETE (absorbed into terminal)
```

### Terminal package structure

```
packages/terminal/
├── package.json
├── vite.config.js
├── index.html
├── public/
│   └── layouts/                          # Preset layout JSON files
│       ├── scalper-zone.json
│       ├── analysis-desk.json
│       ├── volatility-trading.json
│       ├── market-watch.json
│       ├── risk-monitor.json
│       ├── data-cruncher.json
│       ├── minimal.json
│       └── blank.json
├── src/
│   ├── main.jsx                          # Entry point
│   ├── App.jsx                           # Chrome shell + FlexLayout container
│   │
│   ├── chrome/                           # Layer 1: Fixed chrome (always visible)
│   │   ├── TopBar.jsx                    # Logo, clock, layout tabs, P&L, tools/widgets buttons
│   │   ├── TickerBar.jsx                 # Scrolling index prices
│   │   ├── LayoutTabs.jsx                # Multiple layout tabs with add/rename/close
│   │   ├── WidgetPicker.jsx              # WIDGETS popup (grid of 20 widget icons)
│   │   ├── ToolsDropdown.jsx             # TOOLS dropdown menu
│   │   └── ProfileMenu.jsx              # Account, broker status, logout
│   │
│   ├── layout/                           # Layer 2: FlexLayout integration
│   │   ├── LayoutManager.jsx             # FlexLayout <Layout> wrapper
│   │   ├── widgetFactory.jsx             # Maps widget type strings → React components
│   │   ├── layoutStore.js                # Save/load/manage layouts (JSON ↔ localStorage ↔ workspace)
│   │   └── presets.js                    # Default preset definitions
│   │
│   ├── widgets/                          # All 20 widgets (self-contained)
│   │   ├── trading/
│   │   │   ├── Scalper/
│   │   │   │   ├── ScalperWidget.jsx     # 3-panel chart + order buttons
│   │   │   │   ├── ChartPanel.jsx        # Single Lightweight Chart instance
│   │   │   │   ├── TradeButtons.jsx      # Buy/Sell CE/PE with colors
│   │   │   │   ├── InstrumentSelector.jsx # Symbol/expiry/strike selectors
│   │   │   │   ├── useScalperKeys.js     # Shift+arrow keyboard handler (ONLY active when focused)
│   │   │   │   └── index.js
│   │   │   ├── OrderPad/
│   │   │   │   ├── OrderPadWidget.jsx
│   │   │   │   └── index.js
│   │   │   ├── Positions/
│   │   │   │   ├── PositionsWidget.jsx
│   │   │   │   ├── PositionRow.jsx       # Per-row SL/target controls
│   │   │   │   └── index.js
│   │   │   ├── Orders/
│   │   │   ├── TradeBook/
│   │   │   └── Holdings/
│   │   │
│   │   ├── analysis/
│   │   │   ├── Chart/
│   │   │   │   ├── ChartWidget.jsx       # TradingView Advanced Chart (iframe)
│   │   │   │   └── index.js
│   │   │   ├── OptionChain/
│   │   │   │   ├── OptionChainWidget.jsx
│   │   │   │   ├── ChainTable.jsx        # CE | Strike | PE with toggle views
│   │   │   │   ├── ChainViewSelector.jsx # LTP / OI / Greeks / IV / PCR tabs
│   │   │   │   └── index.js
│   │   │   ├── Straddle/
│   │   │   ├── OIChart/
│   │   │   ├── Depth/
│   │   │   ├── Greeks/
│   │   │   └── SectorMap/
│   │   │
│   │   ├── utility/
│   │   │   ├── Watchlist/
│   │   │   ├── Ticker/
│   │   │   ├── Calculator/
│   │   │   ├── News/
│   │   │   └── AIAdvisor/
│   │   │
│   │   └── risk/
│   │       ├── MTMMonitor/
│   │       └── RiskPanel/
│   │
│   ├── tools/                            # Layer 3: Full-page tools
│   │   ├── PnLDashboard/
│   │   │   ├── PnLDashboardTool.jsx
│   │   │   ├── CalendarHeatmap.jsx
│   │   │   ├── TradeStats.jsx
│   │   │   └── index.js
│   │   ├── StrategyBuilder/
│   │   │   ├── StrategyBuilderTool.jsx
│   │   │   ├── LegBuilder.jsx
│   │   │   ├── PayoffChart.jsx
│   │   │   └── index.js
│   │   ├── MarketIntelligence/           # The "Pulse" — 50+ OiPulse tools
│   │   │   ├── MarketIntelligenceTool.jsx
│   │   │   ├── tabs/
│   │   │   │   ├── OIAnalysisTab.jsx
│   │   │   │   ├── FuturesTab.jsx
│   │   │   │   ├── MarketTab.jsx
│   │   │   │   ├── InstitutionalTab.jsx
│   │   │   │   └── SignalsTab.jsx
│   │   │   └── index.js
│   │   ├── BacktestLab/
│   │   │   ├── BacktestLabTool.jsx
│   │   │   ├── ConfigPanel.jsx
│   │   │   ├── ResultsDashboard.jsx
│   │   │   ├── EquityCurve.jsx
│   │   │   ├── MonteCarloChart.jsx
│   │   │   └── index.js
│   │   ├── FlowBuilder/
│   │   │   ├── FlowBuilderTool.jsx       # n8n-like visual editor (ReactFlow)
│   │   │   ├── nodes/                    # 30+ node type components
│   │   │   └── index.js
│   │   ├── TradeJournal/
│   │   │   ├── TradeJournalTool.jsx
│   │   │   └── index.js
│   │   └── Settings/
│   │       ├── SettingsTool.jsx
│   │       ├── sections/
│   │       │   ├── GeneralSection.jsx
│   │       │   ├── TradingSection.jsx
│   │       │   ├── RiskSection.jsx
│   │       │   ├── APISection.jsx
│   │       │   ├── DittoSection.jsx
│   │       │   ├── AutomationSection.jsx
│   │       │   ├── LayoutsSection.jsx
│   │       │   └── AboutSection.jsx
│   │       └── index.js
│   │
│   ├── services/                         # Data layer
│   │   ├── api.js                        # OpenAlgo REST client (with rate limiting)
│   │   ├── websocket.js                  # OpenAlgo WebSocket (LTP/Quote/Depth)
│   │   ├── rateLimiter.js                # Token-bucket per category (10/s orders, 50/s general)
│   │   ├── dataCache.js                  # In-memory cache to prevent duplicate API calls
│   │   └── storage.js                    # localStorage + workspace.json bridge
│   │
│   ├── hooks/                            # Shared React hooks
│   │   ├── useOpenAlgo.js                # REST API hook with caching + rate limiting
│   │   ├── useWebSocket.js               # WebSocket subscription management
│   │   ├── useMarketStatus.js            # Open/closed/pre-open detection
│   │   ├── useLayout.js                  # Layout save/load/switch
│   │   └── useWidget.js                  # Widget registration + factory
│   │
│   └── styles/
│       ├── theme.css                     # Tailwind v4 config, CSS variables
│       ├── flexlayout-overrides.css      # FlexLayout dark theme overrides
│       └── widgets.css                   # Widget-specific styles
```

---

## PART 8: API SAFETY ARCHITECTURE

### Problem: Accidentally Bombarding Broker APIs

Every widget that shows live data (Positions, Option Chain, Chart, etc.) could independently poll the API. If a user opens 8 widgets, each polling every 3 seconds = 160 requests/minute = **will get rate limited or banned.**

### Solution: Centralized Data Bus

```
                    ┌─────────────────┐
                    │   DataBus        │
                    │  (singleton)     │
                    │                  │
    ┌───────────────┤  Subscriptions:  ├───────────────┐
    │               │  - positions     │               │
    │               │  - quotes/NIFTY  │               │
    │               │  - optionchain   │               │
    │               │  - orderbook     │               │
    │               └────────┬─────────┘               │
    │                        │                         │
    │                   One fetch per                   │
    │                   data type per                   │
    │                   refresh cycle                   │
    │                        │                         │
    ▼                        ▼                         ▼
┌────────┐          ┌──────────────┐          ┌────────────┐
│Positions│          │ Option Chain │          │  OI Chart  │
│ Widget  │          │   Widget     │          │   Widget   │
└────────┘          └──────────────┘          └────────────┘
   All three share the same data. No duplicate API calls.
```

**Implementation:**

```javascript
// services/dataBus.js
class DataBus {
  subscriptions = new Map();  // topic → Set<callback>
  cache = new Map();          // topic → { data, timestamp }
  rateLimiter;                // token-bucket
  ws;                         // WebSocket connection

  subscribe(topic, callback) { /* add to subscriptions */ }
  unsubscribe(topic, callback) { /* remove */ }

  // Called on WebSocket message OR polling interval
  publish(topic, data) {
    this.cache.set(topic, { data, timestamp: Date.now() });
    this.subscriptions.get(topic)?.forEach(cb => cb(data));
  }

  // REST fallback when WebSocket unavailable
  async fetchOnce(topic) {
    if (this.rateLimiter.tryConsume(topic)) {
      const data = await api[topic]();
      this.publish(topic, data);
    }
  }
}
```

**Rate Limiting (matches OpenAlgo limits):**

| Category | Limit | Topics |
|----------|-------|--------|
| Orders | 10/sec | placeorder, modifyorder, cancelorder |
| Smart Orders | 2/sec | placesmartorder |
| General API | 50/sec | quotes, positions, orderbook, optionchain, etc. |
| WebSocket | Unlimited | LTP, Quote, Depth subscriptions |

**Data Flow Priority:**
1. **WebSocket first** — Subscribe to LTP/Quote/Depth via port 8765 (real-time, no rate limit)
2. **REST fallback** — When WebSocket unavailable or for endpoints without WS support
3. **Cache layer** — Deduplicate: if 5 widgets need positions, fetch once, broadcast to all
4. **Stale detection** — Show "stale" indicator if data is >10s old

### OpenAlgo Protection Rules

```
NEVER:
- Call any API without going through DataBus
- Poll more than once per topic per refresh cycle
- Open more than 1 WebSocket connection per session
- Send orders without Safety System check (engine package)
- Retry failed orders automatically (user must confirm)

ALWAYS:
- Rate-limit all REST calls via token-bucket
- Cache responses for minimum 1 second
- Show "connecting..." state while waiting for data
- Log all API calls to audit trail
- Respect market hours per exchange before sending orders
```

---

## PART 9: COMPLETE FEATURE INVENTORY

### Features from ALL 222 repos + 4 platforms, organized by where they live:

#### In Scalper Widget (from 1Cliq, INDmoney, Groww)
- [ ] 3-panel Lightweight Charts (Spot + CE + PE)
- [ ] Buy Call / Sell Call / Buy Put / Sell Put buttons
- [ ] Shift+Arrow keyboard shortcuts (only when Scalper focused)
- [ ] One-click trading toggle
- [ ] Lot spinner with +/- buttons
- [ ] Margin display per order
- [ ] Market Protection order (1-15% buffer)
- [ ] Limit at LTP order type
- [ ] Exit all positions button
- [ ] LTP line chart / range bar toggle

#### In Positions Widget (from all platforms)
- [ ] Symbol, Side, Net Qty, Avg Price, LTP, P&L columns
- [ ] Per-position SL (points/%)
- [ ] Per-position Target (points/%)
- [ ] Asset-based SL (exit when index hits level — 1Cliq V2)
- [ ] Asset-based Target (exit when index hits level — 1Cliq V2)
- [ ] Trailing SL (static / trailing)
- [ ] Partial exit buttons (25%, 50%, 75%, 100%)
- [ ] Close individual position
- [ ] Asset-wise grouping toggle
- [ ] Filter: All / F&O only / Equity only

#### In MTM Monitor Widget (from 1Cliq)
- [ ] MTM Target (close all when P&L hits INR amount)
- [ ] MTM Stoploss (close all when loss hits INR amount)
- [ ] MTM Hide/Lock (psychological discipline)
- [ ] Auto Trailing Loss (trail after target hit)
- [ ] +/- buttons (adjust in INR steps)
- [ ] Alert on MTM trigger
- [ ] Current MTM display with color coding

#### In Option Chain Widget (from all platforms)
- [ ] Full chain: CE side | Strike | PE side
- [ ] Toggle views: LTP | OI | Greeks | IV | PCR | Premium
- [ ] OI columns: OI, OI Change, OI%, OI Interpretation
- [ ] Greeks: Delta, Theta, Gamma, Vega per strike
- [ ] PCR per strike + overall PCR with BULLISH/BEARISH
- [ ] BUILD UP annotations (Short Build Up, Long Build Up, etc.)
- [ ] Moneyness badges (ATM/ITM/OTM)
- [ ] Add-to-basket per strike
- [ ] Max Pain calculation
- [ ] IV Smile chart
- [ ] Expiry selector
- [ ] Auto-refresh 3s during market

#### In Chart Widget (from INDmoney Terminal, Groww)
- [ ] TradingView Advanced Chart (iframe embed)
- [ ] Multi-timeframe: 1m, 5m, 15m, 1h, 1d, 1w, 1M
- [ ] Drawing tools (trendline, horizontal, fib, etc.)
- [ ] Indicator library (100+ from openalgo-indicator-skills)
- [ ] Pine Script support (via PineTS converter)
- [ ] Buy/Sell overlay on chart
- [ ] Multi-chart comparison
- [ ] Snapshot/screenshot

#### In Straddle Widget (from Groww, OiPulse)
- [ ] ATM Straddle price chart
- [ ] Overlays: Straddle / Spot / Synthetic Futures
- [ ] Expiry selector, interval selector
- [ ] CE/PE individual price readouts
- [ ] Strangle chart variant

#### In OI Chart Widget (from Groww, OiPulse)
- [ ] Bar chart: Call OI (red) / Put OI (green) per strike
- [ ] Filters: OI Increase / OI Decrease
- [ ] Time scrubber (09:15 to 15:30, 15-min intervals)
- [ ] PCR line overlay
- [ ] Strong Support / Strong Resistance labels

#### In Depth Widget (from fyers-websockets, Groww)
- [ ] 5/20/50 level DOM
- [ ] Order flow visualization (D3.js from order-flow-chart)
- [ ] Buy/sell volume at price levels
- [ ] LTP line overlay

#### In Greeks Widget (from openalgo-portfoliogreeks)
- [ ] Portfolio-level: Net Delta, Gamma, Theta, Vega, Rho
- [ ] Per-position Greeks
- [ ] IV display per position
- [ ] Lot-based vs notional toggle

#### In Watchlist Widget (from Groww, INDmoney)
- [ ] Multiple named lists
- [ ] LTP, change, change%, volume per symbol
- [ ] Click to load in Chart widget
- [ ] Drag to Scalper to change instrument
- [ ] Add/remove symbols, reorder

#### In AI Advisor Widget (from openalgo-mcp, TradingAgents)
- [ ] Natural language query ("What's the OI trend for NIFTY?")
- [ ] Trade suggestions with reasoning
- [ ] Market summary on demand
- [ ] Voice input (from openalgo-voice-based-orders)
- [ ] Multi-model support (LMStudio, Ollama, Anthropic, OpenAI)

#### In News Widget (from finnews-ai, FinSights)
- [ ] Real-time financial news feed
- [ ] Sentiment color coding (bullish/bearish/neutral)
- [ ] Keyword filter
- [ ] Stock-specific news search

#### In Sector Map Widget (from sector-rotation-map, OiPulse)
- [ ] Treemap heatmap (market cap sizing)
- [ ] % change coloring
- [ ] Drill-down to individual stocks
- [ ] RRG (Relative Rotation Graph) overlay

#### In P&L Dashboard Tool (from Groww 915)
- [ ] Calendar heatmap (12 months)
- [ ] DAY / MONTH / YEAR view toggle
- [ ] Net P&L card
- [ ] Trade Win % stat
- [ ] Winning/losing streaks
- [ ] Profit/loss day count
- [ ] Filter: F&O / Equity / Commodities

#### In Strategy Builder Tool (from Groww, INDmoney, OiPulse)
- [ ] Template strategies: Straddle, Strangle, Iron Condor, Bull Call Spread, etc.
- [ ] Multi-leg builder (add/remove legs)
- [ ] Payoff chart (P&L at expiry)
- [ ] Strategy stats: Max Profit, Max Loss, Breakeven, R:R, POP
- [ ] Net Greeks display
- [ ] Execute as basket order
- [ ] Save strategy templates

#### In Market Intelligence Tool (from OiPulse 49 tools)
- [ ] OI Spurt (4-quadrant)
- [ ] OI Stats (cumulative bar chart)
- [ ] Trending OI (aggregated net direction)
- [ ] Trending OI-PA (interval-wise)
- [ ] Big OI Movement (CE vs PE)
- [ ] Active Strikes OI/IV
- [ ] Interval-wise OI (15m/60m/daily)
- [ ] Multiple OI Chart (multi-strike overlay)
- [ ] OI Expiry Analysis (7-day comparison)
- [ ] Futures OI Analysis, OI Buzz, Market Movers, Banks Analysis, EOD Analyzer
- [ ] Sector Heatmap, Stats, Index Contribution
- [ ] World Indices (bubble map)
- [ ] VIX & Index chart
- [ ] Pre-open analysis
- [ ] Open=High/Open=Low strategy
- [ ] FII/DII flows (Capital Market + Derivatives)
- [ ] Participant-wise OI (FII/Pro/DII/Client)
- [ ] FII Long/Short Ratio
- [ ] Connecting Dots (9-signal confluence)
- [ ] D.H.B. alerts
- [ ] Historical replay mode
- [ ] Delivery data
- [ ] Corporate announcements

#### In Backtest Lab Tool (from FlintTrade backtest-engine, raptorbt)
- [ ] 12 strategy templates + custom upload
- [ ] Parameter config panel
- [ ] Date range, symbol, interval
- [ ] Sharpe, Sortino, Max DD, Win Rate, Profit Factor, CAGR
- [ ] Equity curve + drawdown chart
- [ ] Trade-by-trade table
- [ ] Walk-forward optimization
- [ ] Monte Carlo (1000 paths)
- [ ] Strategy comparison
- [ ] CSV/PDF export

#### In Flow Builder Tool (from openalgo-flow)
- [ ] ReactFlow visual canvas
- [ ] 30+ node types (triggers, conditions, actions)
- [ ] Cron triggers, webhook triggers, price alert triggers
- [ ] If/else branching
- [ ] Multi-leg strategy nodes
- [ ] WebSocket LTP feed nodes
- [ ] Place order / cancel order action nodes
- [ ] Telegram / email notification nodes
- [ ] Test mode (dry run without orders)

#### In Trade Journal Tool (from trading-journal)
- [ ] Daily trade log with notes
- [ ] Screenshot upload + annotation
- [ ] Tag system
- [ ] Analytics by tag, time, instrument
- [ ] Emotional state tracking
- [ ] P&L attribution

#### In Settings Tool
- [ ] General: Theme, density, font
- [ ] Trading: Defaults for segment, symbol, qty, order type, product
- [ ] Risk: MTM limits, max position size, max lots
- [ ] Keyboard: Scalper shortcut customization
- [ ] API: OpenAlgo config
- [ ] LLM: AI provider config
- [ ] Telegram: Bot config
- [ ] Ditto: Multi-account mirror (parent/child, multiplier, allocation modes)
- [ ] Automation: Cron jobs, webhook URLs
- [ ] Layouts: Manage, import/export saved layouts

---

## PART 10: IMPLEMENTATION ROADMAP

### Phase 1: Foundation (Week 1-2)
1. Delete `packages/dashboard/` and `packages/backtest/` stubs
2. Install `flexlayout-react` in terminal package
3. Build Chrome shell (TopBar, TickerBar, LayoutTabs)
4. Build WidgetPicker popup and ToolsDropdown
5. Create widget factory + layout store
6. Create 8 preset layout JSON files
7. Implement DataBus with rate limiting + caching
8. Connect WebSocket (OpenAlgo port 8765)

### Phase 2: Core Widgets (Week 3-5)
9. Build Scalper widget (3-panel charts, order buttons)
10. Build Positions widget (live P&L, SL/target controls)
11. Build Orders widget
12. Build Option Chain widget (LTP/OI/Greeks views)
13. Build Chart widget (TradingView iframe)
14. Build Watchlist widget
15. Implement keyboard shortcuts in Scalper (Shift+arrows)

### Phase 3: Risk & Intelligence (Week 6-8)
16. Build MTM Monitor widget (portfolio-level risk)
17. Build Risk Panel widget (per-position asset-based SL)
18. Build OI Chart widget with time scrubber
19. Build Straddle widget
20. Build Depth widget
21. Build Greeks widget
22. Build P&L Dashboard tool (calendar heatmap)

### Phase 4: Strategy & Analysis (Week 9-11)
23. Build Strategy Builder tool (multi-leg, payoff chart)
24. Build Backtest Lab tool (connect to backtest-engine)
25. Build Market Intelligence tool (OI Analysis tab first)
26. Build Sector Map widget
27. Build Calculator widget
28. Add remaining Market Intelligence tabs (Futures, Market, Institutional, Signals)

### Phase 5: Automation & AI (Week 12-14)
29. Build Flow Builder tool (ReactFlow + openalgo-flow nodes)
30. Build AI Advisor widget (connect to ai package)
31. Build News widget (connect to finnews-ai)
32. Build Trade Journal tool
33. Build Settings tool (all sections)
34. CLI-Anything integration (backtest, historical, screener)
35. Create `packages/indicators/` (100+ Numba indicators + PineTS)

### Phase 6: Polish & Deploy (Week 15-16)
36. Ticker widget, Pomodoro-style focus timer
37. Performance optimization (lazy loading, code splitting, memoization)
38. Error boundaries per widget (one crash doesn't kill others)
39. Export/import layouts between machines
40. Update ALL documentation (CLAUDE.md, PLAN.md, README.md, etc.)
41. Fix all 14 contradictions identified in MD cross-reference

---

## PART 11: DOCUMENTATION FIXES REQUIRED

| File | Fix |
|------|-----|
| CLAUDE.md | Update module count (8→widgets), remove dashboard/backtest packages, fix test count, resolve TOTP contradiction |
| PLAN.md | Complete rewrite to match this roadmap |
| README.md | Fix test count (662→current), update architecture section, remove separate React apps |
| packages/terminal/CLAUDE.md | Complete rewrite (port 3001→5173, module names, branch strategy) |
| docs/ARCHITECTURE.md | Update to single React app + widget system |
| docs/THE_PLAN.md | Move to docs/references/historical/ and mark as archived |
| docs/setup/windows.md | Fix port references |
| .reference/CAPTURE_STATUS.md | Update with 1Cliq, INDmoney capture status |
| Git infra | Clarify: submodule or subtree? Pick one, update all docs |
| TOTP | Either remove code OR update CLAUDE.md rule — cannot have both |

---

## PART 12: PERSONAS — NOT JUST TRADERS

FlintTrade is NOT a trading-only app. It serves every type of market participant:

### 16 Personas — Anyone in Finance and Markets

| Persona | What They Do | Widgets/Tools They Use | Layout Preset |
|---------|-------------|----------------------|---------------|
| **Complete Beginner** | Knows nothing, wants to learn and start investing | Learn widget, AI Advisor, Mutual Fund Explorer, SIP Calculator, News | **Beginner** preset |
| **Passive Investor** | SIPs in mutual funds, occasional stock picks, portfolio tracking | Portfolio Tracker, Mutual Fund Explorer, SIP Calculator, Holdings, Watchlist | **Investor** preset |
| **Research Investor** | Fundamental analysis, screener, annual reports before buying | Screener widget, Financials widget, Chart, Watchlist, News, Sector Map | **Research** preset |
| **Intraday Scalper** | Fast option trades, arrow key execution, 1-click | Scalper, Positions, MTM Monitor, Option Chain | **Scalper Zone** preset |
| **Positional Trader** | Swing trades (days to weeks), daily/weekly charts | Chart (daily/weekly TF), Option Chain, Strategy Builder, Positions | **Analysis Desk** preset |
| **Commodity Trader** | MCX after regular job (9pm-11:30pm), crude/gold/silver | Chart (MCX symbols), Scalper (commodity mode), Positions | **Commodity** preset |
| **Crypto Weekend Trader** | 24/7 via DELTA exchange, weekends | Chart (crypto), Scalper (crypto mode), Positions | **Crypto** preset |
| **Fund Manager** | Multiple accounts, portfolio-level Greeks, risk limits | Positions, Greeks, MTM Monitor, Risk Panel, Ditto (mirror) | **Risk Monitor** preset |
| **Strategy Researcher** | Backtesting only, no live trading at all | Backtest Lab, Strategy Builder, Chart (historical), P&L Dashboard | **Research Lab** preset |
| **Algo Developer** | Custom code, webhooks, API integration | Flow Builder, Settings (API), Chart, Positions | **Developer** preset |
| **Financial Advisor (RIA)** | Manages client portfolios, needs reporting | Portfolio Tracker, Holdings, P&L Dashboard, Risk Panel, Ditto | **Advisor** preset |
| **Tax Planner** | STCG/LTCG optimization, tax harvesting | Holdings, Trade Book, P&L Dashboard (yearly), Financials | **Tax** preset |
| **Market Educator** | Teaches trading/investing, needs demo/replay | Learn widget, Chart (historical), AI Advisor, Backtest Lab | **Educator** preset |
| **Options Learner** | Understands theory, practicing paper trading | Strategy Builder, Option Chain, Backtest Lab, AI Advisor | **Paper Trading** preset |
| **NRI Investor** | Indian + US market exposure, currency considerations | Portfolio Tracker, MF Explorer, Chart (US + Indian), Holdings | **NRI** preset |
| **Retirement Planner** | Long-term SIPs, NPS, PPF, FD tracking | Portfolio Tracker, SIP Calculator, MF Explorer, ETF Tracker | **Retirement** preset |

### Additional Widgets Needed for Investors (not just traders)

| Widget | Description | For Persona | Data Source |
|--------|-------------|-------------|-------------|
| **Mutual Fund Explorer** | Browse, compare, SIP in mutual funds | Beginner, Passive Investor | jugaad-data (has MF NAV data), AMFI API |
| **SIP Calculator** | Calculate SIP returns, lumpsum vs SIP comparison | Beginner, Passive Investor | Local calculation |
| **Portfolio Tracker** | Track all investments (stocks, MF, gold, FD) across accounts | All investors | OpenAlgo holdings + manual entry |
| **Financials** | Company fundamentals: P&L, balance sheet, ratios, peers | Research Investor | openscreener (Screener.in scraper), BSE API |
| **Stock Screener** | Filter stocks by fundamentals (PE, ROCE, debt, etc.) | Research Investor | openscreener, fluxscan |
| **Learn** | Guided tutorials, glossary, market basics | Beginner | Static content + AI Advisor |
| **ETF Tracker** | ETF comparison, sector ETFs, global ETFs | Passive Investor | etftracker patterns |
| **IPO** | Upcoming IPOs, subscription status, GMP | All | Public IPO data |

### Additional Layout Presets (total: 12)

| Preset | Widgets | Target Persona |
|--------|---------|---------------|
| **Beginner** | Learn + AI Advisor + MF Explorer + SIP Calculator | Complete beginner |
| **Investor** | Portfolio Tracker + Holdings + MF Explorer + Watchlist + News | Passive investor |
| **Research** | Financials + Stock Screener + Chart + Watchlist + News | Research investor |
| **Commodity** | Chart (MCX) + Scalper + Positions + Watchlist | Commodity trader |
| **Crypto** | Chart (DELTA) + Scalper + Positions + Watchlist | Crypto trader |
| **Research Lab** | Backtest Lab only (full page) | Strategy researcher |
| **Developer** | Flow Builder + Chart + Positions + Settings | Algo developer |
| (existing 5 from Part 5) | ... | ... |

### Why This Matters

- **TAM expansion**: Traders are a niche. Investors are a massive market.
- **User journey**: Beginner → Investor → Trader → Algo Developer (grow with the platform)
- **Retention**: Someone who only trades 2 hours/day still uses the platform for investment tracking
- **Indian market reality**: Most people start with mutual funds, not F&O

### Data Sources for Investment Features

| Data | Source | Package | Already Cloned? |
|------|--------|---------|----------------|
| Mutual Fund NAV | jugaad-data (pip install jugaad-data) | historical | ✅ Yes |
| Company Financials | openscreener (Screener.in scraper) | screener | ✅ Yes (tier2) |
| BSE Corporate Announcements | bseindiaapi (pip install bse) | screener | ✅ Yes (marketcalls) |
| Stock Screener Filters | fluxscan (custom scanner engine) | screener | ✅ Yes (marketcalls) |
| ETF Tracking | etftracker (10 dashboards) | screener | ✅ Yes (marketcalls) |
| IPO Data | Public NSE/BSE APIs | screener | Can build |
| Portfolio Tracking | OpenAlgo holdings + manual entry | core | Already have |
| News Sentiment | finnews-ai, FinSights | ai | ✅ Yes |

---

## PART 13: CLI-ANYTHING STATUS

**Note:** REPOS.md (entry #38) marks CLI-Anything as **"DROPPED — OpenClaw native skills replace this."** This was decided in an earlier planning session.

**Resolution:** CLI-Anything is dropped as a core dependency. Instead:
- Use OpenClaw native skills for agent discoverability
- Build manual Click CLIs for backtest/screener/historical where needed
- The SKILL.md pattern from CLI-Anything is still valuable — generate these manually

---

## PART 14: WHAT WE'RE NOT BUILDING (now)

- Mobile app (responsive web handles tablets; openalgo-mobile exists for later)
- Broker auth UI (OpenAlgo handles it)
- Payment/subscription system (AGPL-3.0 open source)
- Social/copy-trading
- Custom indicator language (use Pine Script via PineTS)
- Separate desktop app (Tauri later if demand exists)
- Chrome extension (openalgo-chrome exists, integrate later)
- Excel add-in (OpenAlgo-Excel exists, integrate later)
- WhatsApp bridge (wabridge exists, integrate later)
- Multi-user auth (openalgo-multiuser exists, integrate later)

---

## PART 15: MiraFish INTEGRATION

MiraFish (tier3-ai-research) is a **multi-agent swarm intelligence prediction engine** that builds parallel digital worlds from seed information.

**Integration point:** AI Advisor widget can use MiraFish as a prediction backend alongside LLM-based advisors. The swarm approach complements the single-agent LLM approach from TradingAgents.

**Architecture:**
```
AI Advisor Widget
├── LLM Provider (LMStudio / Ollama / Anthropic / OpenAI)
├── TradingAgents Framework (multi-agent: analyst, risk, portfolio)
├── MiraFish Swarm (parallel world simulation)
├── RAG Pipeline (ChromaDB knowledge base)
└── Sentiment Analyzer (finnews-ai, FinSights)
```

---

*This is the complete restructuring plan v2. Every feature from every repo, every screenshot, and every persona is accounted for. Nothing should need to be "absorbed later."*

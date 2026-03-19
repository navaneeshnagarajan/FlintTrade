# FlintTrade -- Repository-to-Feature Map

> **Generated:** 2026-03-19 by Claude Code (Opus 4.6)
> **Source:** 222 cloned repos in `.reference/repos/` scanned against AUDIT_GAPS.md, AUDIT_CODE.md, and CLAUDE.md
> **Purpose:** For every FlintTrade feature, identify the BEST cloned repo to absorb code from instead of writing from scratch.

---

## Legend

| Tag | Meaning |
|-----|---------|
| **DIRECT COPY** | Code is ready to use with minimal wiring; same tech stack, same API (OpenAlgo). Just needs import path changes. |
| **ADAPT** | Right logic and structure, but needs modification -- different framework, different data source, or different UI paradigm. |
| **REFERENCE ONLY** | Study the pattern, architecture, or algorithm. Rewrite for FlintTrade. |
| **NOT AVAILABLE** | No cloned repo covers this. Must be built from scratch. |

---

## 1. TERMINAL WIDGETS

### 1.1 Chart (ChartWidget) -- ALREADY BUILT

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chart** | `external-all/openalgo-chart/src/components/Chart/` | Full chart with LWC, indicator legends, OHLC header, multi-pane, drawing tools, measure overlay, price scale menus, context menus. 10+ chart files. | **ADAPT** |
| **openalgo-pinets** | `tier1-core/openalgo-pinets/static/js/openalgo-provider.js` | OpenAlgo data provider for LWC v5 (same library we use). Custom indicator rendering (Williams VIX Fix). | **DIRECT COPY** |
| **EquiCharts** | `tier2-ecosystem/EquiCharts/src/` | Full-featured charting library built on canvas. Widget system, extensions, i18n. TypeScript. | **REFERENCE ONLY** |
| **openalgo-chart** | `external-all/openalgo-chart/src/components/Toolbar/DrawingToolbar.tsx` | Drawing tool toolbar: lines, rays, channels, fibonacci, measure, text. Color picker, style selectors. | **ADAPT** |

**What to absorb now:** Our ChartWidget is 650 lines with basic LWC. openalgo-chart has indicator overlays, drawing tools, multi-pane support, replay mode, and snapshot export. These are the exact upgrades needed for RESTRUCTURE.md Phase 3.

**Files to study:**
- `external-all/openalgo-chart/src/components/Chart/ChartComponent.tsx` -- core chart with indicator support
- `external-all/openalgo-chart/src/components/Chart/IndicatorLegend/IndicatorLegend.tsx` -- indicator OHLC legend
- `external-all/openalgo-chart/src/components/Toolbar/DrawingToolbar.tsx` -- drawing tools
- `external-all/openalgo-chart/src/components/Replay/ReplayControls.tsx` -- chart replay
- `tier1-core/openalgo-pinets/static/js/openalgo-provider.js` -- OpenAlgo datafeed for LWC
- `tier1-core/openalgo-pinets/static/js/williams-vix-fix-indicator.js` -- custom indicator example

---

### 1.2 Option Chain (OptionChainWidget) -- ALREADY BUILT

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **option-chain** | `tier2-ecosystem/option-chain/` | Flask + OpenAlgo option chain with WebSocket live updates, expiry filtering, config management. | **ADAPT** |
| **openalgo-chart** | `external-all/openalgo-chart/src/components/OptionChainModal/` | React option chain modal with ExpiryPicker, OptionChainRow components, leg builder for multi-leg strategies. | **ADAPT** |
| **openalgo-chart** | `external-all/openalgo-chart/src/components/OptionChainPicker/` | Quick option picker with LegBuilder for straddle/strangle construction. | **ADAPT** |
| **openalgo-chart** | `external-all/openalgo-chart/src/components/QuickOptionPicker/` | Rapid ATM option selection. | **ADAPT** |

**What to absorb now:** Our OptionChainWidget has 3 views but the expiry param is broken (AUDIT_CODE bug #3). option-chain repo has proper expiry handling via WebSocket. openalgo-chart has the multi-leg builder we need for StrategyBuilder tool.

**Files to study:**
- `tier2-ecosystem/option-chain/utils/option_chain.py` -- backend option chain logic with expiry
- `tier2-ecosystem/option-chain/utils/websocket_manager.py` -- WebSocket for live OC updates
- `external-all/openalgo-chart/src/components/OptionChainPicker/components/LegBuilder.tsx` -- multi-leg strategy builder

---

### 1.3 OI Chart (OIChartWidget) -- ALREADY BUILT (PARTIAL)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chart** | `external-all/openalgo-chart/src/components/Chart/CompareOptionsDialog.tsx` | Options comparison on chart with overlays. | **REFERENCE ONLY** |

**What to absorb:** No direct OI chart equivalent found. Our implementation is the best available. Enhance with real-time OI data from option-chain WebSocket patterns.

---

### 1.4 Straddle (StraddleWidget) -- ALREADY BUILT (PARTIAL)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **algo_trading_strategies_india** | `external-all/algo_trading_strategies_india/short-straddle/` | 12 straddle strategy variants: 0920 short straddle, combined premium, fixed SL, MTM-based target, percentage SL, trailing SL. Indian market specific (NIFTY, BANKNIFTY, FINNIFTY, SENSEX). | **ADAPT** |

**What to absorb:** Our StraddleWidget shows straddle P&L visually. The algo_trading_strategies_india repo has the execution logic for automated straddle strategies with MTM-based exits -- exactly what the user requested (AUDIT_GAPS 3.1: MTM-based stoploss and target).

**Files to study:**
- `external-all/algo_trading_strategies_india/short-straddle/mtm_based_target/bank_nifty_mtm_based_short_straddle.py`
- `external-all/algo_trading_strategies_india/short-straddle/trailing_stop_loss/bank_nifty_trailing_percentage_based_stop_loss_short_straddle.py`
- `external-all/algo_trading_strategies_india/short-straddle/combined_premium/` -- all 4 index variants

---

### 1.5 Depth (DepthWidget) -- ALREADY BUILT

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chart** | `external-all/openalgo-chart/src/components/DepthOfMarket/DepthOfMarket.tsx` | Full depth of market React component. | **ADAPT** |
| **dhan-20depth** | `marketcalls-all/dhan-20depth/` | 20-level depth data from Dhan API. | **REFERENCE ONLY** |

**What to absorb:** Our DepthWidget does 5-level depth. openalgo-chart's DepthOfMarket may have better visualization patterns. dhan-20depth shows how to get deeper market data.

---

### 1.6 Watchlist (WatchlistWidget) -- ALREADY BUILT

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chart** | `external-all/openalgo-chart/src/components/Watchlist/` | Full watchlist with sections, context menu, symbol tooltips, drag-drop, multiple watchlists via selector. 6 files. | **ADAPT** |

**What to absorb:** Our WatchlistWidget (660 lines) is solid. openalgo-chart adds multiple watchlist tabs (WatchlistSelector), sections for organizing, and richer tooltips. Good for Phase 3 upgrade.

**Files to study:**
- `external-all/openalgo-chart/src/components/Watchlist/WatchlistSelector.tsx` -- multi-watchlist tabs
- `external-all/openalgo-chart/src/components/Watchlist/WatchlistSection.tsx` -- grouped sections
- `external-all/openalgo-chart/src/components/Watchlist/ContextMenu.tsx` -- right-click actions

---

### 1.7 Sector Map -- NOT BUILT (RESTRUCTURE.md planned)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **sector-rotation-map** | `tier2-ecosystem/sector-rotation-map/` | JavaScript sector rotation heatmap with Python API backend. Sector holdings JSON data. | **ADAPT** |
| **openalgo-chart** | `external-all/openalgo-chart/src/components/SectorHeatmap/SectorHeatmapModal.tsx` | React sector heatmap modal -- ready-made React component. | **DIRECT COPY** |
| **etftracker** | `marketcalls-all/etftracker/frontend/src/pages/Dashboard3_SectorRotation.tsx` | React + Plotly sector rotation visualization with India-specific sectors. | **ADAPT** |
| **etftracker** | `marketcalls-all/etftracker/frontend/src/pages/Dashboard4_IndiaSectors.tsx` | India sector-specific dashboard. | **ADAPT** |

**Best approach:** Start with openalgo-chart's SectorHeatmapModal (React, same stack). Enhance with etftracker's India-specific sector data.

---

### 1.8 Calculator -- NOT BUILT (RESTRUCTURE.md planned)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chart** | `external-all/openalgo-chart/src/components/RiskCalculatorPanel/` | Risk calculator with RiskSettings, TemplateSelector. 3 files. | **DIRECT COPY** |
| **py_vollib** | `external-all/py_vollib/py_vollib/black_scholes/` | Black-Scholes pricing, Greeks (analytical + numerical), IV calculation. | **REFERENCE ONLY** |

**Best approach:** openalgo-chart's RiskCalculatorPanel is a React component we can adapt directly. For options pricing math, py_vollib is the gold standard reference.

**Files to study:**
- `external-all/openalgo-chart/src/components/RiskCalculatorPanel/RiskCalculatorPanel.tsx`
- `external-all/openalgo-chart/src/components/RiskCalculatorPanel/RiskSettings.tsx`
- `external-all/py_vollib/py_vollib/black_scholes/greeks/analytical.py`

---

### 1.9 News -- NOT BUILT (RESTRUCTURE.md planned)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **finnews-ai** | `tier1-core/finnews-ai/` | Full Flask news app: routes for news fetching, AI-powered analysis, sharing, rate limiting, CORS. Indian market news. | **ADAPT** |

**Best approach:** finnews-ai is a standalone Flask app. Extract the news fetching and AI analysis logic, build a React widget to display it. The middleware patterns (rate limiter, CORS) are already handled by FlintTrade's DataBus.

**Files to study:**
- `tier1-core/finnews-ai/routes/news.py` -- news fetching logic
- `tier1-core/finnews-ai/main.py` -- news aggregation pipeline
- `tier1-core/finnews-ai/models.py` -- news data models

---

### 1.10 AI Advisor -- NOT BUILT (RESTRUCTURE.md planned)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chatbot** | `tier2-ecosystem/openalgo-chatbot/` | OpenAlgo documentation chatbot with RAG (vector DB), knowledge base, config-driven. | **ADAPT** |
| **openadvisor** | `tier1-core/openadvisor/` | ML-powered stock advisor: CatBoost predictions, data downloading, backtesting routes, portfolio management. | **ADAPT** |
| **TradingAgents** | `tier3-ai-research/TradingAgents/` | Multi-agent trading system: fundamentals analyst, market analyst, news analyst, social media analyst, risk manager, bull/bear researchers, debate system. LLM clients (Anthropic, OpenAI, Google). | **REFERENCE ONLY** |
| **FinMem-LLM-StockTrading** | `tier3-ai-research/FinMem-LLM-StockTrading/` | LLM with memory for stock trading: embedding-based memory, reflection, portfolio management, importance scoring. | **REFERENCE ONLY** |
| **Stockagent** | `external-all/Stockagent/` | LLM-based stock analysis agent with secretary pattern, custom prompts. | **REFERENCE ONLY** |
| **openalgo-voice-based-orders** | `tier2-ecosystem/openalgo-voice-based-orders/` | Voice-to-order pipeline using Groq. | **REFERENCE ONLY** |

**Best approach:** Layer 1: Absorb openalgo-chatbot's RAG pipeline for the "Ask AI" feature. Layer 2: Absorb openadvisor's CatBoost prediction logic for ML signals. Layer 3: Study TradingAgents for the multi-analyst architecture the user envisioned.

**Files to study:**
- `tier2-ecosystem/openalgo-chatbot/openalgo_documentation_chatbot.py` -- RAG chatbot
- `tier1-core/openadvisor/training_predictions.py` -- ML prediction pipeline
- `tier1-core/openadvisor/routes/predictions.py` -- prediction serving
- `tier3-ai-research/TradingAgents/tradingagents/agents/` -- multi-agent architecture
- `tier3-ai-research/FinMem-LLM-StockTrading/puppy/memory_functions/` -- memory scoring system

---

### 1.11 MTM Monitor -- NOT BUILT (RESTRUCTURE.md planned)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **algo_trading_strategies_india** | `external-all/algo_trading_strategies_india/broker-utilities/mtm_square_off_zerodha/` | MTM monitor with live subscription, auto square-off on MTM limits. 3 files. | **ADAPT** |
| **nifty-trading-railway** | `community-openalgo/nifty-trading-railway/baseline_v1_live/` | Position tracker, state manager, order manager, notification manager, swing detector. Production-grade live trading system. | **ADAPT** |

**Best approach:** The MTM monitor pattern from algo_trading_strategies_india is exactly what the user needs (AUDIT_GAPS 3.1). Adapt the MTM logic to work with OpenAlgo API instead of Zerodha. The nifty-trading-railway codebase has a complete position tracking + notification system.

**Files to study:**
- `external-all/algo_trading_strategies_india/broker-utilities/mtm_square_off_zerodha/zerodha_mtm_monitor.py` -- MTM calculation
- `external-all/algo_trading_strategies_india/broker-utilities/mtm_square_off_zerodha/zerodha_ltp_subscriber.py` -- live price feed
- `community-openalgo/nifty-trading-railway/baseline_v1_live/position_tracker.py` -- position tracking
- `community-openalgo/nifty-trading-railway/baseline_v1_live/notification_manager.py` -- alerts
- `community-openalgo/nifty-trading-railway/baseline_v1_live/state_manager.py` -- state persistence

---

### 1.12 Risk Panel -- NOT BUILT (RESTRUCTURE.md planned)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chart** | `external-all/openalgo-chart/src/components/RiskCalculatorPanel/` | Risk calculator UI. | **ADAPT** |
| **TradingAgents** | `tier3-ai-research/TradingAgents/tradingagents/agents/managers/risk_manager.py` | Automated risk management agent. | **REFERENCE ONLY** |
| **FinRL-Trading** | `external-all/FinRL-Trading/src/strategies/adaptive_rotation/risk_manager.py` | Portfolio risk management with position sizing. | **REFERENCE ONLY** |

**What's missing:** No cloned repo has a real-time risk panel widget that shows portfolio Greeks, margin utilization, max loss limits, and per-position risk. Needs to be built from scratch using data from our existing GreeksWidget + PositionsWidget.

---

### 1.13 Ticker (TickerBar) -- CHROME, NOT A WIDGET

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chart** | `external-all/openalgo-chart/src/components/BottomBar/BottomBar.tsx` | Bottom status bar with market info. | **REFERENCE ONLY** |

**Status:** TickerBar already exists as chrome (4 indices). RESTRUCTURE.md wanted it as a configurable widget. Absorb nothing -- just refactor existing code.

---

## 2. FULL-PAGE TOOLS

### 2.1 Flow Builder (FlowBuilderTool) -- STUB

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-flow** | `tier1-core/openalgo-flow/` | **COMPLETE flow builder** with React frontend (React Flow) + Python backend (FastAPI). 54 node types covering every OpenAlgo API endpoint. Config panel, execution log, variable system, WebSocket real-time updates. | **DIRECT COPY** |

**This is the single most valuable repo for FlintTrade.** It is a fully built visual workflow builder specifically for OpenAlgo, with node types for:
- Order nodes: PlaceOrder, SmartOrder, ModifyOrder, CancelOrder, BasketOrder, SplitOrder, OptionsOrder, OptionsMultiOrder
- Data nodes: GetQuote, MultiQuotes, GetDepth, History, OptionChain, SyntheticFuture
- Account nodes: Funds, Holdings, OrderBook, TradeBook, PositionBook, Margin
- Control nodes: AND/OR/NOT gates, Delay, TimeCondition, TimeWindow, PriceCondition, PriceAlert, WaitUntil, PositionCheck, FundCheck
- Integration nodes: WebhookTrigger, TelegramAlert, HttpRequest, Subscribe/Unsubscribe (LTP/Quote/Depth)

**Files to study:**
- `tier1-core/openalgo-flow/frontend/src/components/nodes/` -- ALL 54 node types
- `tier1-core/openalgo-flow/frontend/src/components/panels/NodePalette.tsx` -- node picker
- `tier1-core/openalgo-flow/frontend/src/components/panels/ExecutionLogPanel.tsx` -- execution log
- `tier1-core/openalgo-flow/frontend/src/stores/workflowStore.ts` -- workflow state management
- `tier1-core/openalgo-flow/backend/app/core/scheduler.py` -- workflow execution engine
- `tier1-core/openalgo-flow/backend/app/core/openalgo.py` -- OpenAlgo integration

---

### 2.2 Trade Journal (TradeJournalTool) -- STUB

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **trading-journal** | `tier2-ecosystem/trading-journal/` | **COMPLETE trade journal** with React frontend + Python FastAPI backend. CRUD for trades, portfolios, user management, CSRF protection, Indian market adaptations. Docker-ready. | **ADAPT** |

**Best approach:** The backend is FastAPI (we use Flask patterns in packages, but the CRUD logic is reusable). The frontend was React but the `frontend/src/` directory is empty -- only the backend is usable. Build our own React widget using the backend models/schemas as reference.

**Files to study:**
- `tier2-ecosystem/trading-journal/backend/app/crud/trade.py` -- trade CRUD operations
- `tier2-ecosystem/trading-journal/backend/app/crud/portfolio.py` -- portfolio CRUD
- `tier2-ecosystem/trading-journal/backend/app/models/trade.py` -- trade data model
- `tier2-ecosystem/trading-journal/backend/app/schemas/` -- API schemas

---

### 2.3 Strategy Builder (StrategyBuilderTool) -- STUB

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chart** | `external-all/openalgo-chart/src/components/PineEditor/PineScriptEditor.tsx` | Pine Script editor component (code editor for strategy writing). | **ADAPT** |
| **openalgo-chart** | `external-all/openalgo-chart/src/components/OptionChainPicker/components/LegBuilder.tsx` | Multi-leg option strategy builder (visual). | **ADAPT** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/pages/strategy/` | Strategy management pages (CRUD for strategies). | **ADAPT** |

**Best approach:** Combine the Pine Script editor from openalgo-chart with the visual leg builder. openalgo-desktop's strategy pages show how to manage strategy lifecycle (create, edit, deploy, monitor).

---

### 2.4 Backtest Lab (BacktestLabTool) -- STUB

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **trading-strategies-openalgo** | `tier2-ecosystem/trading-strategies-openalgo/app/core/` | Full backtest engine: backtest_engine.py, metrics.py, order_simulator.py, portfolio.py, tax_calculator.py. OpenAlgo-native. | **DIRECT COPY** |
| **vectorbt-backtesting-skills** | `tier2-ecosystem/vectorbt-backtesting-skills/` | VectorBT-based backtests: EMA crossover, RSI, Supertrend, MACD, dual momentum, walk-forward templates. Claude Code skills format. | **ADAPT** |
| **openengine** | `tier1-core/openengine/openengine/engine/backtester.py` | Backtesting engine with strategy base class, live trader, order manager. | **ADAPT** |
| **openadvisor** | `tier1-core/openadvisor/routes/backtest.py` | Backtest route with visualization. | **REFERENCE ONLY** |
| **AlgoTrading** | `tier3-ai-research/AlgoTrading/API/` | **59 strategy algorithms** in Python, each with backtesting. Trend, mean-reversion, volatility, volume, pattern strategies. | **ADAPT** |
| **FinRL-Trading** | `external-all/FinRL-Trading/src/backtest/backtest_engine.py` | RL-based backtest engine with data fetcher, walk-forward, performance analyzer. | **REFERENCE ONLY** |

**Best approach:** The trading-strategies-openalgo backtest engine is the most directly useful -- it's already built for OpenAlgo with metrics, tax calculation, and order simulation. For strategy templates, the AlgoTrading repo has 59 ready-made strategies. For the React UI, build our own using the metrics data format from trading-strategies-openalgo.

**Files to study:**
- `tier2-ecosystem/trading-strategies-openalgo/app/core/backtest_engine.py` -- core engine
- `tier2-ecosystem/trading-strategies-openalgo/app/core/metrics.py` -- Sharpe, Sortino, drawdown, etc.
- `tier2-ecosystem/trading-strategies-openalgo/app/core/order_simulator.py` -- order simulation
- `tier2-ecosystem/trading-strategies-openalgo/app/core/tax_calculator.py` -- Indian tax calculation
- `tier2-ecosystem/trading-strategies-openalgo/app/strategies/base_strategy.py` -- strategy base class
- `tier2-ecosystem/trading-strategies-openalgo/app/strategies/supertrend_strategy_adapter.py` -- user's preferred strategy
- `tier3-ai-research/AlgoTrading/API/0010_Super_Trend/PY/supertrend_strategy.py` -- Supertrend reference

---

### 2.5 P&L Dashboard (PnLDashboardTool) -- STUB

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/pages/PnLTracker.tsx` | P&L tracker page with live data. React + TypeScript. | **ADAPT** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/pages/SandboxPnL.tsx` | Sandbox P&L testing page. | **REFERENCE ONLY** |
| **community-openalgo/openalgo-dashboard** | `community-openalgo/openalgo-dashboard/app.py` | Flask P&L dashboard. | **REFERENCE ONLY** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/pages/Dashboard.tsx` | Dashboard page with overview metrics. | **ADAPT** |

**Best approach:** openalgo-desktop's PnLTracker.tsx is the closest match -- same-ish stack (React + TypeScript, we're JSX). Study it for P&L calculation patterns and visualization layout.

**Files to study:**
- `tier2-ecosystem/openalgo-desktop/src/pages/PnLTracker.tsx` -- main P&L UI
- `tier2-ecosystem/openalgo-desktop/src/hooks/useMarketData.ts` -- market data hook
- `tier2-ecosystem/openalgo-desktop/src/hooks/useLivePrice.ts` -- live price updates

---

### 2.6 Market Intelligence (MarketIntelligenceTool) -- STUB

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chart** | `external-all/openalgo-chart/src/components/MarketScreener/MarketScreenerPanel.tsx` | Market screener panel component. | **ADAPT** |
| **openalgo-chart** | `external-all/openalgo-chart/src/components/ANNScanner/` | ANN-based scanner with scanner items. | **ADAPT** |
| **openscreener** | `tier2-ecosystem/openscreener/src/openscreener/` | Full stock screener: screener logic, stock analysis, parsers for balance sheet, cash flow, P&L, ratios, shareholding, quarterly results, pros/cons, peers. | **ADAPT** |
| **fyers-scanner** | `marketcalls-all/fyers-scanner/` | Real-time market scanner with scheduler, database, live scanning. | **REFERENCE ONLY** |
| **chartink** | `marketcalls-all/chartink/` | ChartInk integration: real-time scanner processing, WebSocket events. | **ADAPT** |
| **etftracker** | `marketcalls-all/etftracker/frontend/src/pages/` | 10 market intelligence dashboards: Asset Quilt, Market Pulse, Sector Rotation, ETF Screener, Stock Drilldown, Risk-Return, Momentum, Correlation. | **ADAPT** |

**Best approach:** This is the richest category. For the React UI, start with openalgo-chart's MarketScreenerPanel. For backend screener logic, openscreener has comprehensive parsers for Indian stocks. For market pulse/sector views, etftracker's 10 dashboards are production-ready React code.

**Files to study:**
- `external-all/openalgo-chart/src/components/MarketScreener/MarketScreenerPanel.tsx` -- screener UI
- `tier2-ecosystem/openscreener/src/openscreener/screener.py` -- screener logic
- `tier2-ecosystem/openscreener/src/openscreener/stock.py` -- stock analysis
- `tier2-ecosystem/openscreener/src/openscreener/parsers/` -- 10 financial data parsers
- `marketcalls-all/etftracker/frontend/src/pages/Dashboard2_MarketPulse.tsx` -- market pulse
- `marketcalls-all/etftracker/frontend/src/pages/Dashboard9_Momentum.tsx` -- momentum screener
- `marketcalls-all/chartink/core/fyers/processor.py` -- scanner signal processing

---

### 2.7 Settings (SettingsTool) -- PARTIAL

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chart** | `external-all/openalgo-chart/src/components/Settings/` | Settings popup with sections: Appearance, Logging, OpenAlgo, Scales, Symbol. 5 section files. | **ADAPT** |
| **openalgo-chart** | `external-all/openalgo-chart/src/components/ShortcutsSettings/ShortcutsSettings.tsx` | Keyboard shortcuts configuration UI. | **ADAPT** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/pages/admin/` | Admin settings: ServerSettings, Holidays, MarketTimings, FreezeQty. | **REFERENCE ONLY** |

**What to absorb:** Our SettingsTool has 4 working sections + 7 stubs. openalgo-chart's ShortcutsSettings can fill the Keyboard stub. The Appearance section can reference openalgo-chart's AppearanceSection.

---

## 3. PYTHON PACKAGES

### 3.1 `packages/engine/` -- Strategy Engine

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openengine** | `tier1-core/openengine/openengine/` | Complete engine: backtester, live_trader, order_manager, broker_interface, base_strategy, config, logger. | **ADAPT** |
| **trading-strategies-openalgo** | `tier2-ecosystem/trading-strategies-openalgo/app/strategies/` | Strategy registry, base strategy, hooks, universal adapter, supertrend adapter, grid adapter. | **ADAPT** |
| **nifty-trading-railway** | `community-openalgo/nifty-trading-railway/baseline_v1_live/` | Production live trading: position tracker, order manager, state manager, swing detector, notification manager, startup health check. | **ADAPT** |

**Best approach:** openengine provides the clean architecture (backtester + live trader + broker interface). trading-strategies-openalgo has the strategy registry pattern we need. nifty-trading-railway has battle-tested live trading patterns.

---

### 3.2 `packages/backtest-engine/` -- Backtesting

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **trading-strategies-openalgo** | `tier2-ecosystem/trading-strategies-openalgo/app/core/` | backtest_engine.py, metrics.py, order_simulator.py, portfolio.py, tax_calculator.py. OpenAlgo-native. | **DIRECT COPY** |
| **AlgoTrading** | `tier3-ai-research/AlgoTrading/API/` | 59 strategy templates in Python with backtesting (MA crossover, Supertrend, MACD, Bollinger, RSI, volume, pattern strategies). | **ADAPT** |
| **vectorbt-backtesting-skills** | `tier2-ecosystem/vectorbt-backtesting-skills/` | VectorBT backtest templates: EMA crossover, RSI, Supertrend, MACD, dual momentum, walk-forward. | **ADAPT** |
| **openadvisor** | `tier1-core/openadvisor/routes/backtest.py` | Backtest route with CatBoost integration. | **REFERENCE ONLY** |
| **fully-automated-nifty-options-trading** | `external-all/fully-automated-nifty-options-trading/common/` | 10+ backtest variants: MACD, RSI, Supertrend, sideways detection. | **REFERENCE ONLY** |

---

### 3.3 `packages/screener/` -- Option Chain, OI, Greeks

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openscreener** | `tier2-ecosystem/openscreener/` | Stock screener: batch stock analysis, financial parsers (balance sheet, cash flow, P&L, ratios, shareholding, quarterly), peer comparison. Tests included. | **ADAPT** |
| **openalgo-portfoliogreeks** | `tier1-core/openalgo-portfoliogreeks/` | Portfolio Greeks calculator using OpenAlgo API. Flask app with templates. | **DIRECT COPY** |
| **py_vollib** | `external-all/py_vollib/` | Black-Scholes, Black, BSM pricing. Analytical + numerical Greeks. IV calculation. Full test suite. | **ADAPT** |
| **option-chain** | `tier2-ecosystem/option-chain/` | Option chain with OpenAlgo, WebSocket live updates. | **ADAPT** |

**Best approach:** For the screener package, openscreener provides the financial analysis framework. openalgo-portfoliogreeks is directly usable for portfolio Greeks (same API). py_vollib provides the math for IV and Greeks calculation if we need to compute them client-side.

**Files to study:**
- `tier1-core/openalgo-portfoliogreeks/app.py` -- portfolio Greeks via OpenAlgo
- `tier1-core/openalgo-portfoliogreeks/docs/greeks.py` -- Greeks calculation reference
- `external-all/py_vollib/py_vollib/black_scholes/greeks/analytical.py` -- Delta, Gamma, Theta, Vega, Rho

---

### 3.4 `packages/historical/` -- OHLCV Data Pipeline

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **historify** | `tier1-core/historify/` | Full historical data pipeline: data fetcher (chunked), rate limiter, scheduler, watchlist management, SQLite storage, charting routes. OpenAlgo-native. | **DIRECT COPY** |
| **openchart** | `tier1-core/openchart/` | Free OHLCV data from OpenChart API. Python library. | **DIRECT COPY** |
| **openquest** | `tier1-core/openquest/` | QuestDB-based tick data storage: candle aggregation, WebSocket subscription, OpenAlgo client wrapper. Real-time data pipeline. | **ADAPT** |
| **openadvisor** | `tier1-core/openadvisor/data_downloader.py` | Data downloading for ML training. | **REFERENCE ONLY** |

**Best approach:** historify IS the historical data package. openchart provides free data sourcing. openquest adds tick-level storage for real-time candle aggregation.

**Files to study:**
- `tier1-core/historify/historify/app/utils/data_fetcher_chunked.py` -- chunked OHLCV download
- `tier1-core/historify/historify/app/utils/rate_limiter.py` -- rate limiting for data fetches
- `tier1-core/historify/historify/app/utils/scheduler.py` -- automated data download scheduling
- `tier1-core/openchart/openchart/` -- free data API
- `tier1-core/openquest/candle_aggregator.py` -- tick-to-candle aggregation
- `tier1-core/openquest/questdb_client.py` -- time-series database integration

---

### 3.5 `packages/data/` -- Tick Recording, Audit Logging

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openquest** | `tier1-core/openquest/` | Tick data recording via WebSocket, candle aggregation, QuestDB storage. | **ADAPT** |
| **fyers-websockets** | `tier1-core/fyers-websockets/` | WebSocket connection for live market data with protobuf (msg.proto, msg_pb2.py). Database storage. | **REFERENCE ONLY** |

---

### 3.6 `packages/ai/` -- LLM, RAG, Signals, Sentiment

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-chatbot** | `tier2-ecosystem/openalgo-chatbot/` | RAG chatbot: vector DB, knowledge base, documentation analysis, config-driven. | **ADAPT** |
| **openadvisor** | `tier1-core/openadvisor/` | ML advisor: CatBoost predictions, data downloading, Flask routes for predictions/charts/backtest. | **ADAPT** |
| **TradingAgents** | `tier3-ai-research/TradingAgents/` | Multi-agent system: 4 analysts (fundamentals, market, news, social), 2 researchers (bull/bear), 3 debaters (aggressive/conservative/neutral), risk manager, trader. LangGraph-based. Multi-provider LLM clients. | **REFERENCE ONLY** |
| **FinMem-LLM-StockTrading** | `tier3-ai-research/FinMem-LLM-StockTrading/` | LLM with tiered memory: embedding-based retrieval, importance scoring, decay functions, reflection. | **REFERENCE ONLY** |
| **Stockagent** | `external-all/Stockagent/` | Simple LLM stock analysis agent. | **REFERENCE ONLY** |
| **llm-rl-finance-trader** | `external-all/llm-rl-finance-trader/` | LLM + RL hybrid: sentiment analysis, trading environment, model training. | **REFERENCE ONLY** |
| **PrimoGPT** | `external-all/PrimoGPT/` | FinRL with NLP: stock trading environments with stoploss, cash penalty, paper trading. Multi-data-source processing. | **REFERENCE ONLY** |
| **openalgo-mcp** | `tier1-core/openalgo-mcp/` | MCP server for OpenAlgo. | **REFERENCE ONLY** |
| **openalgo-claude-plugin** | `tier2-ecosystem/openalgo-claude-plugin/` | Claude plugin for OpenAlgo. | **REFERENCE ONLY** |

**Best approach:**
1. RAG pipeline: Absorb openalgo-chatbot for documentation/knowledge Q&A
2. ML signals: Absorb openadvisor's CatBoost prediction pipeline
3. Multi-agent architecture: Study TradingAgents for the analyst/researcher/debater pattern
4. Memory system: Study FinMem for the tiered memory architecture

---

### 3.7 `packages/integration/` -- Webhooks, ChartInk, Alerts

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **chartink** | `marketcalls-all/chartink/` | ChartInk integration: scanner processing, WebSocket events, Fyers data feed. | **ADAPT** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/pages/chartink/` | ChartInk strategy pages: configure symbols, create/view strategies. 4 files. | **ADAPT** |

---

### 3.8 `packages/automation/` -- Cron, Telegram, Post-Market

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/pages/telegram/` | Telegram integration pages. | **REFERENCE ONLY** |
| **nifty-trading-railway** | `community-openalgo/nifty-trading-railway/baseline_v1_live/telegram_notifier.py` | Telegram notification system for trading events. | **ADAPT** |
| **nifty-trading-railway** | `community-openalgo/nifty-trading-railway/baseline_v1_live/startup_health_check.py` | Health check system. | **REFERENCE ONLY** |

---

### 3.9 `packages/ditto/` -- Multi-Account Manager

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **Algomirror** | `tier1-core/Algomirror/` | Full multi-account trade mirroring system: WebSocket service, Docker, migrations, tests. The CANONICAL source for this feature. | **DIRECT COPY** |
| **1cliq** | `.reference/repos/1cliq/code/ditto-setting.html.json` | 1Cliq's Ditto feature UI (HTML/CSS/JS captured). Multi-account settings interface. | **REFERENCE ONLY** |
| **openalgo-multiuser** | `external-all/openalgo-multiuser/` | Multi-user OpenAlgo setup. | **REFERENCE ONLY** |

**Best approach:** Algomirror is literally the infra/algomirror submodule. It already does position mirroring. The packages/ditto/ package should be a thin wrapper over Algomirror's API.

---

### 3.10 `packages/indicators/` -- NOT CREATED (RESTRUCTURE.md planned)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **pyindicators** | `marketcalls-all/pyindicators/` | Clean Python indicator library: momentum (RSI, ROC, Stochastic, Williams), trend (MACD, ADX, moving averages), volatility (ATR, Bollinger, Keltner, std), volume (OBV, VWAP, MFI, CMF, AD). Streaming support, pandas wrapper, pipeline system, CLI, widgets. Tests for all categories. | **DIRECT COPY** |
| **pandas-ta** | `external-all/pandas-ta/` (if present) | 130+ indicators as pandas extension. | **REFERENCE ONLY** |
| **PineTS** | `marketcalls-all/PineTS/` | Pine Script to TypeScript/Python converter. | **ADAPT** |
| **AlgoTrading** | `tier3-ai-research/AlgoTrading/API/` | 59 strategy files, each implementing specific indicators. | **REFERENCE ONLY** |

**Best approach:** pyindicators is EXACTLY what packages/indicators/ should be. Same author (marketcalls). Already has the architecture RESTRUCTURE.md describes: categorized indicators, streaming support, pipeline system. Absorb directly and add Numba acceleration.

**Files to study:**
- `marketcalls-all/pyindicators/pyindicators/momentum/rsi.py` -- RSI implementation
- `marketcalls-all/pyindicators/pyindicators/trend/macd.py` -- MACD implementation
- `marketcalls-all/pyindicators/pyindicators/volatility/bollinger.py` -- Bollinger Bands
- `marketcalls-all/pyindicators/pyindicators/volume/vwap.py` -- VWAP
- `marketcalls-all/pyindicators/pyindicators/streaming.py` -- streaming indicator updates
- `marketcalls-all/pyindicators/pyindicators/pipeline.py` -- indicator pipeline system

---

### 3.11 `packages/core/` -- OpenAlgo Client

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-python-library** | `tier1-core/openalgo-python-library/openalgo/` | Official OpenAlgo Python library: 45+ endpoints, audit tools, examples, playground. | **DIRECT COPY** |
| **openalgo-flow** | `tier1-core/openalgo-flow/backend/app/core/openalgo.py` | OpenAlgo client with rate limiting. | **REFERENCE ONLY** |

**Status:** Our core package already wraps the OpenAlgo API. The openalgo-python-library is the canonical reference for any new endpoints.

---

## 4. INFRASTRUCTURE

### 4.1 WebSocket Handling

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **fyers-websockets** | `tier1-core/fyers-websockets/` | WebSocket with protobuf, auto-reconnect, database storage. | **REFERENCE ONLY** |
| **openquest** | `tier1-core/openquest/` | WebSocket subscription to OpenAlgo, tick aggregation. | **ADAPT** |
| **openalgo-flow** | `tier1-core/openalgo-flow/frontend/src/lib/websocket.ts` | TypeScript WebSocket client. | **REFERENCE ONLY** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/components/socket/SocketProvider.tsx` | React Socket.IO provider. | **REFERENCE ONLY** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/hooks/useSocket.ts` | Socket hook. | **REFERENCE ONLY** |

---

### 4.2 Auth & Session Management

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-flow** | `tier1-core/openalgo-flow/backend/app/core/auth.py` | JWT auth with encryption. | **ADAPT** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/components/auth/AuthSync.tsx` | Auth state sync. | **REFERENCE ONLY** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/hooks/useAutoLogout.ts` | Auto-logout on inactivity. | **REFERENCE ONLY** |

---

### 4.3 Rate Limiting

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-flow** | `tier1-core/openalgo-flow/backend/app/core/rate_limit.py` | Server-side rate limiting. | **REFERENCE ONLY** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/lib/rateLimiter.ts` | Client-side rate limiter (TypeScript). | **REFERENCE ONLY** |

**Status:** Our rateLimiter.js already implements token bucket. These are references only.

---

### 4.4 Deployment

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **Openalgo-Docker** | `community-openalgo/Openalgo-Docker/` | Docker setup for OpenAlgo. | **REFERENCE ONLY** |
| **kokamkar-openalgo-docker** | `community-openalgo/kokamkar-openalgo-docker/` | Community Docker setup. | **REFERENCE ONLY** |
| **openalgo-railway** | `community-openalgo/openalgo-railway/` | Railway deployment. | **REFERENCE ONLY** |
| **trading-journal** | `tier2-ecosystem/trading-journal/docker-compose.yml` | Docker Compose with nginx. | **REFERENCE ONLY** |

---

### 4.5 Monitoring

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/pages/monitoring/` | 3 dashboards: LatencyDashboard, SecurityDashboard, TrafficDashboard. | **ADAPT** |
| **openalgo-desktop** | `tier2-ecosystem/openalgo-desktop/src/pages/Logs.tsx` | Log viewer page. | **REFERENCE ONLY** |

---

## 5. INVESTOR/BEGINNER FEATURES

### 5.1 ETF Tracker

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **etftracker** | `marketcalls-all/etftracker/` | **COMPLETE ETF tracker** with React + Plotly: Asset Quilt, Market Pulse, Sector Rotation, India Sectors, India Quilt, ETF Screener, Stock Drilldown, Risk-Return, Momentum, Correlation. 10 dashboard pages. Backend Python API. | **DIRECT COPY** |

**This is the most feature-complete investor tool in the reference repos.** All 10 dashboards are React + TypeScript with Plotly charts. Can be absorbed as a widget or tool.

**Files to study:**
- `marketcalls-all/etftracker/frontend/src/pages/` -- all 10 dashboard pages
- `marketcalls-all/etftracker/frontend/src/components/HeatmapCell.tsx` -- heatmap component
- `marketcalls-all/etftracker/frontend/src/components/PlotlyChart.tsx` -- reusable chart
- `marketcalls-all/etftracker/frontend/src/api/client.ts` -- API client

---

### 5.2 Portfolio Tracker

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **virfolio** | `marketcalls-all/virfolio/` | Flask portfolio tracker: multi-asset portfolio management, analytics routes, stock data fetching, currency conversion, auth. | **ADAPT** |
| **openalgo-portfoliogreeks** | `tier1-core/openalgo-portfoliogreeks/` | Portfolio Greeks calculator. | **ADAPT** |

---

### 5.3 Mutual Fund Explorer & SIP Calculator

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| -- | -- | No cloned repo has Indian mutual fund data or SIP calculators. | **NOT AVAILABLE** |

---

### 5.4 Stock Screener (Fundamental)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **openscreener** | `tier2-ecosystem/openscreener/` | Complete stock screener with financial parsers. | **DIRECT COPY** |
| **companytracker** | `marketcalls-all/companytracker/` | BSE company data service. | **REFERENCE ONLY** |

---

### 5.5 Learn (Educational Resources)

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| -- | -- | No cloned repo has trading education content. | **NOT AVAILABLE** |

---

### 5.6 IPO Tracker

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| -- | -- | No cloned repo has IPO tracking. | **NOT AVAILABLE** |

---

### 5.7 Net Worth Calculator

| Repo | Path | Relevance | Type |
|------|------|-----------|------|
| **virfolio** | `marketcalls-all/virfolio/routes/analytics.py` | Portfolio analytics which could serve as net worth calculator base. | **ADAPT** |

---

## 6. STRATEGY TEMPLATES (for backtest-engine)

These are the 59+ strategy algorithms available from AlgoTrading, each with Python implementations:

### Trend Following (15)
| # | Strategy | Repo File |
|---|----------|-----------|
| 1 | MA Crossover | `AlgoTrading/API/0001_MA_CrossOver/PY/` |
| 2 | N-Day Breakout | `AlgoTrading/API/0002_NDay_Breakout/PY/` |
| 3 | ADX Trend | `AlgoTrading/API/0003_ADX_Trend/PY/` |
| 4 | Parabolic SAR | `AlgoTrading/API/0004_Parabolic_SAR_Trend/PY/` |
| 5 | Donchian Channel | `AlgoTrading/API/0005_Donchian_Channel/PY/` |
| 6 | Triple MA | `AlgoTrading/API/0006_Tripple_MA/PY/` |
| 7 | Keltner Breakout | `AlgoTrading/API/0007_Keltner_Channel_Breakout/PY/` |
| 8 | Hull MA Trend | `AlgoTrading/API/0008_Hull_MA_Trend/PY/` |
| 9 | MACD Trend | `AlgoTrading/API/0009_MACD_Trend/PY/` |
| 10 | Supertrend | `AlgoTrading/API/0010_Super_Trend/PY/` |
| 11 | Ichimoku Kumo | `AlgoTrading/API/0011_Ichimoku_Kumo_Breakout/PY/` |
| 12 | Heikin Ashi | `AlgoTrading/API/0012_Heikin_Ashi_Consecutive/PY/` |
| 13 | DMI Power Move | `AlgoTrading/API/0013_DMI_Power_Move/PY/` |
| 14 | TV Supertrend Flip | `AlgoTrading/API/0014_TradingView_Supertrend_Flip/PY/` |
| 15 | Gann Swing | `AlgoTrading/API/0015_Gann_Swing_Breakout/PY/` |

### Momentum (11)
| # | Strategy | Repo File |
|---|----------|-----------|
| 16 | RSI Divergence | `AlgoTrading/API/0016_RSI_Divergence/PY/` |
| 17 | Williams %R | `AlgoTrading/API/0017_Williams_R/PY/` |
| 18 | ROC Impulse | `AlgoTrading/API/0018_ROC_Impulce/PY/` |
| 19 | CCI Breakout | `AlgoTrading/API/0019_CCI_Breakout/PY/` |
| 20 | Momentum % | `AlgoTrading/API/0020_Momentum_Percentage/PY/` |
| 21 | Elder Impulse | `AlgoTrading/API/0023_Elder_Impulse/PY/` |
| 22 | Laguerre RSI | `AlgoTrading/API/0024_RSI_Laguerre/PY/` |
| 23 | Stochastic RSI Cross | `AlgoTrading/API/0025_Stochastic_RSI_Cross/PY/` |
| 24 | RSI Overbought/Oversold | `AlgoTrading/API/0058_RSI_Overbought_Oversold/PY/` |
| 25 | Double Bottom | `AlgoTrading/API/0056_Double_Bottom/PY/` |
| 26 | Double Top | `AlgoTrading/API/0057_Double_Top/PY/` |

### Mean Reversion (10)
| # | Strategy | Repo File |
|---|----------|-----------|
| 27 | RSI Reversion | `AlgoTrading/API/0026_RSI_Reversion/PY/` |
| 28 | Bollinger Reversion | `AlgoTrading/API/0027_Bollinger_Reversion/PY/` |
| 29 | Z-Score | `AlgoTrading/API/0028_ZScore/PY/` |
| 30 | MA Deviation | `AlgoTrading/API/0029_MA_Deviation/PY/` |
| 31 | VWAP Reversion | `AlgoTrading/API/0030_VWAP_Reversion/PY/` |
| 32 | Keltner Reversion | `AlgoTrading/API/0031_Keltner_Reversion/PY/` |
| 33 | ATR Reversion | `AlgoTrading/API/0032_ATR_Reversion/PY/` |
| 34 | MACD Zero | `AlgoTrading/API/0033_MACD_Zero/PY/` |
| 35 | Low Vol Reversion | `AlgoTrading/API/0034_Low_Vol_Reversion/PY/` |
| 36 | Bollinger %B | `AlgoTrading/API/0035_Bollinger_B_Reversion/PY/` |

### Volatility (10)
| # | Strategy | Repo File |
|---|----------|-----------|
| 37 | Bollinger Squeeze | `AlgoTrading/API/0021_Bollinger_Squeeze/PY/` |
| 38 | ADX+DI | `AlgoTrading/API/0022_ADX_DI/PY/` |
| 39 | ATR Expansion | `AlgoTrading/API/0036_ATR_Expansion/PY/` |
| 40 | VIX Trigger | `AlgoTrading/API/0037_VIX_Trigger/PY/` |
| 41 | BB Width | `AlgoTrading/API/0038_BB_Width/PY/` |
| 42 | HV Breakout | `AlgoTrading/API/0039_HV_Breakout/PY/` |
| 43 | ATR Trailing | `AlgoTrading/API/0040_ATR_Trailing/PY/` |
| 44 | Vol-Adjusted MA | `AlgoTrading/API/0041_Vol_Adjusted_MA/PY/` |
| 45 | IV Spike | `AlgoTrading/API/0042_IV_Spike/PY/` |
| 46 | VCP (Volatility Contraction) | `AlgoTrading/API/0043_VCP/PY/` |

### Volume (10)
| # | Strategy | Repo File |
|---|----------|-----------|
| 47 | ATR Range | `AlgoTrading/API/0044_ATR_Range/PY/` |
| 48 | Choppiness Index | `AlgoTrading/API/0045_Choppiness_Index_Breakout/PY/` |
| 49 | Volume Spike | `AlgoTrading/API/0046_Volume_Spike/PY/` |
| 50 | OBV Breakout | `AlgoTrading/API/0047_OBV_Breakout/PY/` |
| 51 | VWAP Breakout | `AlgoTrading/API/0048_VWAP_Breakout/PY/` |
| 52 | VWMA | `AlgoTrading/API/0049_VWMA/PY/` |
| 53 | A/D Line | `AlgoTrading/API/0050_AD/PY/` |
| 54 | Vol-Weighted Price Breakout | `AlgoTrading/API/0051_Volume_Weighted_Price_Breakout/PY/` |
| 55 | Volume Divergence | `AlgoTrading/API/0052_Volume_Divergence/PY/` |
| 56 | Volume MA Cross | `AlgoTrading/API/0053_Volume_MA_Cross/PY/` |

### Pattern + Advanced (3)
| # | Strategy | Repo File |
|---|----------|-----------|
| 57 | Cumulative Delta | `AlgoTrading/API/0054_Cumulative_Delta_Breakout/PY/` |
| 58 | Volume Surge | `AlgoTrading/API/0055_Volume_Surge/PY/` |
| 59 | Hammer Candle | `AlgoTrading/API/0059_Hammer_Candle/PY/` |

### Indian F&O Specific (from other repos)
| # | Strategy | Repo | Type |
|---|----------|------|------|
| 60 | Short Straddle (0920) | `algo_trading_strategies_india/short-straddle/0920_short_straddle/` | **ADAPT** |
| 61 | Combined Premium Straddle | `algo_trading_strategies_india/short-straddle/combined_premium/` | **ADAPT** |
| 62 | MTM-Based Target Straddle | `algo_trading_strategies_india/short-straddle/mtm_based_target/` | **ADAPT** |
| 63 | Trailing SL Straddle | `algo_trading_strategies_india/short-straddle/trailing_stop_loss/` | **ADAPT** |
| 64 | Grid Trading Bot | `trading-strategies-openalgo/strats/grid_trading_bot.py` | **DIRECT COPY** |
| 65 | Supertrend Bot | `trading-strategies-openalgo/strats/supertrend_trading_bot.py` | **DIRECT COPY** |
| 66 | Wheel Strategy | `Openalgo_Wheel_Strategy/strategy.py` | **ADAPT** |
| 67 | Nifty Baseline Live | `nifty-trading-railway/baseline_v1_live/` | **ADAPT** |

---

## 7. UI/UX REFERENCE CAPTURES

These are not code repos but captured HTML/CSS/JS from competitor platforms:

| Platform | Path | What's Captured | Use For |
|----------|------|-----------------|---------|
| **1Cliq** | `.reference/repos/1cliq/code/` | Trade window v1 + v2, orders, ditto settings, favourites, keyboard shortcuts, CSS themes | Order entry UX, multi-account UI, keyboard shortcut design |
| **INDMoney** | `.reference/repos/indmoney/code/` | Dashboard + flash trading HTML captures | Beginner/investor dashboard design, flash trading UX |
| **Groww** | (screenshots in `.reference/screenshots/`) | 915 screenshots captured per memory | Visual design reference for terminal chrome, colors, layout |

---

## 8. PRIORITY ABSORPTION ORDER

Based on AUDIT_GAPS.md priorities and what provides the most value:

### Immediate (Week 1)
1. **openalgo-chart** -- Absorb SectorHeatmapModal for Sector Map widget, RiskCalculatorPanel for Calculator widget, ShortcutsSettings for Settings Keyboard tab
2. **pyindicators** -- Bootstrap packages/indicators/ with this codebase
3. **trading-strategies-openalgo/app/core/** -- Upgrade packages/backtest-engine/ with real backtest engine

### Week 2-3
4. **openalgo-flow** -- Absorb for FlowBuilder tool (most complex tool, biggest payoff)
5. **openalgo-portfoliogreeks** -- Enhance packages/screener/ Greeks calculations
6. **algo_trading_strategies_india/short-straddle/** -- Build MTM Monitor widget
7. **etftracker** -- Build investor ETF tracker tool

### Week 4+
8. **openalgo-chatbot + openadvisor** -- Build AI Advisor widget
9. **trading-journal** -- Build Trade Journal tool
10. **historify + openchart** -- Enhance packages/historical/
11. **AlgoTrading 59 strategies** -- Add strategy templates to backtest-engine

---

## 9. REPOS WITH NO FLINT TRADE USE

These cloned repos are not directly useful for FlintTrade:

| Category | Repos | Reason |
|----------|-------|--------|
| NFT/Blockchain | OpenAlgoNFT | Not relevant to trading platform |
| Generic tools | excalidraw, daisyui, LibreChat, codex, listmonk | General-purpose tools, not trading-specific |
| Other languages | OpenAlgo.NET, OpenAlgo-Java, openalgo-go, openalgo-rust, CSharp-NT8-OrderFlowKit | Wrong language/platform |
| DevOps | autoinstall, docker-fastapi-react, flask-traefik, server-monitor-dashboard | Generic infrastructure |
| Unrelated | Age-Gender-Emotion-Analyzer, EcoLens, food-app, sketchmaker, timer | Not trading related |
| Empty/minimal | Many marketcalls-all repos with just 1-3 files | Too minimal to absorb |

---

## 10. SUMMARY STATISTICS

| Metric | Count |
|--------|-------|
| Total repos scanned | 222 |
| Repos with DIRECT COPY potential | 12 |
| Repos with ADAPT potential | 28 |
| Repos with REFERENCE ONLY value | 25 |
| Repos NOT AVAILABLE for any feature | 3 features (MF explorer, Learn, IPO) |
| Repos with no FlintTrade use | ~60 |
| Strategy templates available | 67 |
| React components absorbable | ~40+ (from openalgo-chart alone) |

### Top 5 Most Valuable Repos

1. **openalgo-chart** (external-all) -- 80+ React components covering Chart, Watchlist, OptionChain, Depth, Screener, RiskCalculator, SectorHeatmap, Settings, Alerts, Pine Editor, Position Tracker, Replay. SINGLE BIGGEST SOURCE.
2. **openalgo-flow** (tier1-core) -- Complete visual workflow/flow builder with 54 OpenAlgo node types. Direct replacement for FlowBuilder stub.
3. **trading-strategies-openalgo** (tier2-ecosystem) -- Full backtest engine + strategy framework. Direct replacement for backtest-engine stubs.
4. **pyindicators** (marketcalls-all) -- Complete indicator library. Direct bootstrap for packages/indicators/.
5. **etftracker** (marketcalls-all) -- 10 investor-grade dashboards in React. Direct bootstrap for investor features.
6. **investing-algorithm-framework** (external) -- Event-driven + vectorized backtesting, 50+ metrics (CAGR, Sharpe, drawdown, win rate), declarative TakeProfit/StopLoss rules, portfolio persistence, permutation testing for statistical significance. Apache-2.0 license. ADAPT for backtest-engine upgrade.

---

*This map should be reviewed when starting any new feature. Check here BEFORE writing code from scratch.*

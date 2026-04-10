# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased] — v0.5.0-dev

### Added — Features (Waves 1-9)
- Signals pipeline: real-time signal generation, scoring, and routing to order engine (signal_pipeline.py + signal_routes.py + useSignals hook)
- MCX commodity support: symbol normalisation, market hours, lot sizes (mcxLots.ts + 46 tests)
- Mutual Funds module: MutualFundTab in /invest with AMFI NAV lookup, SIP calculator, fund comparison (mf_routes.py)
- WhatsApp notification channel alongside existing Telegram bot (whatsapp_alerts.py + whatsapp_routes.py)
- ExpiryTrack: historical expired options tracking with expiry_tracker.py + routes
- Pine Script editor: browser-based Pine-to-Python transpiler (PineEditor.tsx + compile endpoint)
- Chrome extension: quick order entry and watchlist from any browser tab (packages/chrome-extension/)
- Tauri desktop shell: native window wrapper for the React terminal (packages/desktop/)
- Multi-user support: role-based access (admin/trader/viewer) with JWT claims (user_manager.py + user_routes.py)
- IPO Tracker: ipo_routes.py + ipo_calendar.json + IpoTab.tsx with NSE data
- FinRL reinforcement learning: rl_environment.py + rl_trainer.py + rl_features.py
- OpenClaw bridge: openclaw_bridge.py in both ai and automation packages + routes

### Added — Features (Waves 10-23)
- Multi-agent AI team: MiroFish + TradingAgents architecture (multi_agent.py)
- Risk debate: multi-perspective risk assessment engine (risk_debate.py)
- Ensemble selector: strategy ensemble voting system (ensemble_selector.py)
- Hyperopt strategy optimiser: hyperparameter optimisation for strategies (hyperopt_strategy.py)
- Fundamental screener: Screener.in integration for fundamental analysis (fundamental_screener.py)
- FII/DII tracker: NSE scraper for institutional flow data (fii_dii.py)
- RRG calculator: Relative Rotation Graph computation + SectorMap RRG view (rrg.py + useRRGData.ts)
- Portfolio backtester: VectorBT patterns for portfolio-level backtesting (vectorbt_runner.py)
- Bracket orders: bracket order support with strategy state persistence (bracket_order.py)
- Order flow inference: trade-side inference from tick data (orderflow_inference.py)
- Alert trigger log: persistent alert audit trail for compliance (alert_trigger_log.py)
- Activity log: comprehensive SEBI-compliant user action logging (activity_log.py)

### Added — Wiring & Mode System
- Server-side order safety proxy (order_routes.py) — all orders route through FlintTrade backend
- Unified mode system: Explore (sample data) / Practice (paper trading) / Live (real orders)
- useModeData hook: components receive live, mock, or paper data based on active mode
- MockDataEngine: deterministic sample data generator for Explore mode
- CSRF token middleware on all state-mutating endpoints
- Mode reset on disconnect: reverts to Explore when broker session expires
- Persona-aware setup wizard: interest matrix seeds default workspace and visible routes
- ModeIndicator component in TopBar with Practice-to-Live toggle
- Practice section in Settings with SandboxControls
- DemoChoice overlay on first /explore visit
- GoalTab wired into /invest route
- JWT secret persistence across server restarts
- SEBI disclaimer banner in practice mode

### Added — Infrastructure
- SSE log streaming: /ft-api/v1/logs/stream endpoint for real-time execution log tailing
- flask-mail integration for password reset and alert emails
- API key separation: distinct keys for OpenAlgo vs FlintTrade backend
- Docker production config: multi-stage Dockerfile with uv (10x faster pip), tini init, non-root user, start.sh
- Nginx hardening: rate limiting, CSP headers, HSTS, X-Frame-Options
- Security headers middleware: CSP, X-Frame-Options, HSTS, X-Content-Type-Options on all responses
- WebSocket handler upgrade: mode-specific subscribe, batch subscribe, reference counting
- All 3 git submodules synced (openalgo, algomirror, openclaw)

### Added — Features (Wave 24 — Absorption)
- CommandPalette (Ctrl+K): global command search with 51 commands, fuzzy search, recent history, keyboard navigation (absorbed from openalgo-chart)
- Price Alerts widget: armed/triggered/expired states, LTP polling, condition types (above/below/crosses), localStorage persistence (31st widget)
- DrawingToolbar: vertical 20-tool sidebar with 7 groups, favourites, popover selection, lock/hide/clear (absorbed from openalgo-chart)
- LegBuilder: multi-leg option strategy builder (Straddle/Strangle/Spread/Condor/Butterfly/Custom), payoff calculation, basket order execution (absorbed from openalgo-chart)
- FlowBuilder rewrite: @xyflow/react v12, Zustand store, 54 node types across 8 categories, node palette, config panel, execution log (absorbed from openalgo-flow)
- ETF Screener tab: filterable TanStack Table with 12 sortable columns, category pills (absorbed from etftracker)
- Sector Rotation tab: treemap heatmap + momentum scoreboard (absorbed from etftracker)
- Risk-Return tab: SVG scatter plot (volatility vs return, Sharpe sizing) with stats cards (absorbed from etftracker)
- Correlation Matrix tab: HTML heatmap + market regime indicator (Risk-On/Off/Rotation) + VIX/DXY badges (absorbed from etftracker)
- RouteBanner: dismissible contextual hints on /trade, /invest, /lab, /settings
- SpotlightTour: wired to /ai and /automate routes for beginners
- PositionTracker: thread-safe, DuckDB-persisted, R-multiple accounting, MTM square-off (absorbed from nifty-trading-railway)
- StateManager: 8-state strategy lifecycle with per-strategy locks, audit trail (absorbed from nifty-trading-railway)
- SwingDetector: watch-based confirmation, multi-symbol support, callbacks (absorbed from nifty-trading-railway)
- 5 new repos cloned: n8n-io/n8n, marketcalls/Vibe-Trading, openbull, upstox-api-docs, zerodha-api-docs
- absorption-status.json: 233 repos tracked (was 80)
- data-tour-target attributes added to WatchlistWidget, AIRoute sections, AutomateRoute sections
- 4 new ftApi endpoints: getEtfScreener, getSectorRotation, getRiskReturn, getCorrelationMatrix

### Added — Tests
- LearnRoute tests (3): heading, sidebar sections, default tab content
- InvestRoute tests (3): heading, tab navigation, default Dashboard tab
- AutomateRoute tests (3): heading, section tabs, sidebar rendering
- DittoRoute tests (10): header, tabs, accounts table, mirror tab, risk tab, error handling
- MCX lot sizes (46 tests), useSignals hook tests, security headers tests
- AlertsWidget tests (20), LegBuilder tests (31), FlowBuilder tests (5), ETF analytics tests (22)
- Python engine tests: position_tracker (46), state_manager (34), swing_detector (37)
- Total terminal tests: ~2,500 (Vitest, 227+ files) | Python: ~6,500 (pytest) = ~9,000 total

### Added — Features (Wave 25 — Engine + Analytics)
- Backtest engine: event-driven BacktestEngine with MARKET/LIMIT/STOP/STOP_LIMIT orders, slippage, commission (absorbed from trading-strategies-openalgo)
- Indian tax calculator: STT, stamp duty, exchange charges, SEBI fee, GST — all Decimal precision
- BaseBacktestStrategy: abstract on_bar/on_tick, enter_long/short, Signal enum, indicator proxy
- Metrics: Sharpe, Sortino, CAGR, max drawdown (amount + duration), win rate, profit factor, Calmar, VaR/CVaR, streaming Welford
- 5 streaming indicators: MACD, Bollinger Bands, Supertrend, VWAP, Cumulative Delta (absorbed from pyindicators)
- 2 batch volume functions: cumulative_delta, volume_profile with Point of Control (absorbed from pyindicators)
- Portfolio Greeks: IV percentile/rank, P&L attribution (Taylor expansion), portfolio PCR, enhanced max pain (absorbed from openalgo-portfoliogreeks)
- OI Overlay on ChartWidget: histogram pane showing net CE-PE OI imbalance
- System Health widget (32nd widget): connections, performance, security, alerts, auto-refresh

### Added — Features (Wave 26 — Strategies + AI)
- MTM straddle strategies: MTMStraddleStrategy, TrailingStopStraddle, CombinedPremiumStraddle, MTMMonitor (absorbed from algo_trading_strategies_india)
- RAG pipeline: document loader, text chunker, embedding provider (sentence-transformers/OpenAI), ChromaDB vector store (absorbed from openalgo-chatbot)
- ML advisor: LightGBM classifier (BUY/HOLD/SELL) with 11 technical features, model persistence (absorbed from openadvisor)

### Added — Features (Wave 27 — Charts + Retraining)
- Three-Panel Chart widget (33rd widget): CE|Index|PE synchronised LWC v5 charts with auto ATM strike
- IndicatorSettingsModal: two-column modal with colour picker, line style, period inputs, draft state
- Auto-retraining loop: continuous ML model retraining (daily), drift detection (KS test), atomic model swap
- Retrain API: GET /retrain/status, POST /retrain/trigger, GET /retrain/history

### Added — Features (Wave 28 — Strategies + Journal + Broker)
- 29 backtest strategy templates across 5 categories: trend following (9), mean reversion (6), momentum (6), volatility (4), composite (4) (absorbed from AlgoTrading)
- STRATEGY_REGISTRY with name-based lookup, all extending BaseBacktestStrategy
- Trade Journal: DuckDB-backed CRUD with emotions, quality ratings, tags, auto-computed P&L, CSV export, tradebook import
- Journal API: 7 endpoints under /ft-api/v1/journal/
- BrokerInterface Protocol: 10 standard operations, 9 Pydantic models, BrokerRegistry, OpenAlgoBroker implementation (absorbed from openbull)

### Added — Features (Wave 29 — Skills + Swarm + Historical)
- SkillRegistry: markdown skills with YAML frontmatter, on-demand loading, fuzzy search (absorbed from Vibe-Trading)
- 10 starter AI skills: OpenAlgo API, option chain, straddle, risk, indicators, backtest, market hours, SEBI, FII/DII, Greeks
- SwarmExecutor: async DAG task executor with topological layering, cycle detection, event emission (absorbed from Vibe-Trading)
- DataProvider Protocol: OpenAlgo, OpenChart (NSE free), yfinance (MCX) with fallback chain (absorbed from historify + openchart)
- OHLCVNormaliser: IST conversion, column aliasing, intraday cutoff, data validation
- HistoricalCache: DuckDB-backed, TTL freshness, incremental updates, batch fetch

### Added — Features (Waves 49-53 — Quality + Skills)
- WidgetPicker search: filter 80 widgets by name/description, highlight matches, live count
- 6 new workspace presets (12 total): Options Analysis, Sector View, Algo Trading, Portfolio Manager, Market Overview, Quick Scalper
- PermutationTester: statistical significance testing, Monte Carlo equity curve confidence bands
- WalkForwardAnalyser: rolling/expanding window OOS validation, 6 metrics, robustness check
- KeyboardShortcutsDialog: ? key opens reference, 15 shortcuts, platform-aware labels, searchable
- Widget descriptions: all 80 widgets have one-line description in picker
- Preset management API: CRUD endpoints /ft-api/v1/presets/ with fork, export, import
- PresetSection in Settings: card grid, create/edit/fork/delete presets, widget selector
- 15 new AI skills (30 total): scalping, bracket orders, expiry day, algo deployment, India macro,
  candlestick patterns, support/resistance, intermarket, iron condor, earnings options, margin
  optimisation, Greeks guide, trading psychology, drawdown management, portfolio hedging
- conftest.py for backtest-engine: eliminated sys.path hacks from 20 test files
- CI split: 3 parallel vitest jobs (core + trading/utility + analysis/routes/tools)

### Added — Widgets (Waves 39-48 — 80 Widget Milestone)
- CurrencyConverterWidget, EarningsCalendarWidget, GlobalIndicesWidget, StrategyTemplatesWidget, AuditTrailWidget (Wave 39)
- PivotPointsWidget, EconomicCalendarWidget, PortfolioAllocationWidget, OrderBookReplayWidget (Wave 40)
- MarketBreadthWidget, QuickTradeWidget, VolatilityConeWidget, ProfitTargetWidget (Wave 41)
- HeatCalendarWidget, VWAPBandsWidget, CorrelationPairsWidget, MultiTimeframeWidget (Wave 42)
- PCRTrendWidget, TradePerformanceWidget, InstrumentCompareWidget, SpreadViewWidget (Wave 43)
- GreeksHeatmapWidget, MarketSummaryWidget, GapAnalysisWidget, SessionStatsWidget (Wave 44)
- ImpliedMoveWidget, RiskDashboardWidget, OptionsFlowWidget, TradeLogWidget (Wave 45)
- MicrostructureWidget, ExpiryCountdownWidget, PositionSizingWidget, CorrelationMatrixWidget (Wave 46)
- IVSkewWidget, MarketClockWidget, StrategyMonitorWidget, NetPositionWidget (Wave 47)
- TradeIdeaWidget, SectorPerformanceWidget, TickSpeedWidget, OrderLadderWidget (Wave 48)
- Total: 80 widgets across 3 categories (22 Trading + 36 Analysis + 22 Utility)

### Added — Python Backends (Waves 39-42)
- Earnings calendar: NIFTY 50 quarterly events, sample data generator, 3 Flask endpoints
- Enhanced audit routes: paginated log, CSV export (100K row SEBI compliance), action stats
- Pivot calculator: 5 methods (Standard/Fibonacci/Woodie/Camarilla/DeMark)
- Economic calendar: 26 event templates across 6 countries, cadence-based generation
- Market breadth: McClellan Oscillator, breadth thrust, A/D line, sample data
- Volatility cone: rolling HV percentile bands, IV percentile scoring
- VWAP bands calculator: session-aware, single-pass running variance
- Pair correlation: 5 preset Indian pairs, z-score classification
- Multi-timeframe analyser: RSI/MACD/EMA per-TF confluence scoring

### Added — Features (Wave 49 — Quality of Life)
- WidgetPicker search: filter 80 widgets by name, highlight matches, live count
- 6 new workspace presets (12 total): Options Analysis, Sector View, Algo Trading, Portfolio Manager, Market Overview, Quick Scalper
- PermutationTester: statistical significance testing, Monte Carlo equity curve bands
- WalkForwardAnalyser: rolling/expanding window OOS validation, robustness check

### Fixed — CI (Wave 48)
- Node heap increased to 8GB (NODE_OPTIONS=--max-old-space-size=8192) for 227+ test files

### Fixed — Accessibility (Wave 39)
- 13 WCAG 2.1 AA issues fixed across 11 widgets (3 critical, 4 serious, 3 moderate)
- CommandPalette: aria-activedescendant ID linkage
- NotificationCentre: focus trap implementation
- DrawingToolbar: keyboard-operable popover items
- AlertsWidget: proper tab ARIA pattern
- TradeCopierWidget: shadcn/ui components, aria-labels
- LegBuilder: aria-pressed on BUY/SELL toggle

### Added — Features (Waves 33-35 — Deep Analytics)
- FlowBuilder: n8n-style NodeTypeDescriptor metadata, expression evaluator (safe {{variable}} interpolation), ExpressionInput with token highlighting and autocomplete
- Portfolio optimiser: Markowitz, min variance, risk parity, equal weight, Black-Litterman, efficient frontier (scipy SLSQP)
- Webhook receiver: HMAC-SHA256 verification, TradingView/ChartInk/custom parsers, async dispatch, rate limiter
- Options payoff engine: expiry/pre-expiry P&L curves, Black-Scholes Greeks, Monte Carlo POP (10k paths)
- Regime detector: 7-regime classification from VIX, returns, A/D, FII flow, breadth
- Correlation engine: pairwise Pearson, rolling correlation, regime-tagged matrix
- PayoffChart: pure SVG P&L visualisation with split green/red segments, hover tooltip
- Order analytics: fill rate, slippage (bps), execution speed (p50/p95/p99), by-hour/by-symbol
- Strategy comparator: side-by-side metrics, rankings, weighted scoring, optimal blend weights
- PositionHeatMapWidget (34th widget): squarified treemap of portfolio exposure

### Added — Features (Wave 31 — AI Refinements)
- MemoryManager: compound scoring (importance × recency_decay × relevance), exponential time decay, access boost, category defaults, pruning (absorbed from FinMem)
- TradeReflector: batch analysis every N trades, win/loss pattern extraction, rule-based + LLM paths (absorbed from LLM-TradeBot)
- NewsScheduler: pre-market 07:00, post-market 16:30, intraday 15min polls (IST), TTL dedup, async callbacks (absorbed from FinSights)

### Added — Features (Wave 32 — Simulation)
- SimulationEngine: multi-phase simulation wrapping BacktestEngine with 7 phases (warmup → crisis → recovery)
- MarketEvent injection: price shocks, volume spikes, volatility expansion, gaps
- 6 pre-built scenarios: flash crash, trend reversal, range bound, gap up, volatility expansion, liquidity crisis
- StressTestRunner: run strategy against all scenarios, generate survival report (absorbed from Stockagent)

### Added — Features (Wave 30 — Skill Variants)
- useSkillContent hook: returns skill-level-appropriate widgets (7/18/33), tools, tooltips, presets
- WidgetPicker + ToolsDropdown: filter by skill level via allowedIds props
- SkillBadge in TopBar showing current level with link to Settings

### Fixed — Code Review (Wave 24)
- AlertsWidget: fixed stale ltpMap closure causing poll data races (functional setLtpMap update)
- LegBuilder: fixed mixed UTC/local date accessors in normaliseExpiry (getUTCDate for consistent expiry symbols)
- CommandPalette: removed `as unknown as string` type lie on JSX prop
- flowStore: added structural validation before JSON.parse cast (prevents corrupt localStorage crash)
- PositionTracker: wrapped read methods and close_all in thread lock (TOCTOU fix)
- StateManager: added cache_lock for all_snapshots/strategies_in_state iteration safety
- PositionTracker + StateManager: added db_lock for DuckDB connection thread safety
- SwingDetector: all_swings now returns deepcopy (prevents mutation by _update_extreme)
- tourDefinitions: fixed target mismatch (orderpad -> order-pad)
- Ruff: removed unused imports in position_tracker.py and state_manager.py

### Fixed — Security
- JWT revocation: token blacklist on logout and password change
- Admin role enforcement: /admin route and admin API endpoints require admin JWT claim
- Scanner subprocess: additional forbidden builtins (__import__, exec, eval, compile)
- SQL injection fix: parameterised queries in DuckDB historical pipeline
- Strategy hardening: AST validation rejects os/sys/subprocess imports before execution

### Fixed — API Contracts
- 15+ endpoint request/response shapes aligned with OpenAlgo 2.0 spec
- OpenAlgo holidays/timings/intervals changed from POST to GET
- optionchain response normalised: nested greeks flattened to top-level fields
- multiquotes response: array wrapper added for consistency with quotes endpoint
- WebSocket auth error now returns structured JSON instead of plain text disconnect
- CORS preflight: OPTIONS handler added to all /ft-api routes

### Fixed — General
- Kill switch now properly awaits async coroutines (was silently failing)
- Scheduler no longer blocks equity ticks during market hours
- TOTP encryption upgraded from XOR to Fernet (AES-128-CBC + HMAC)
- API key moved from localStorage to sessionStorage
- 6 window.confirm replaced with AlertDialog (Scalper, ActionCenter, KeyboardSection)
- British English: Analyse, Behaviour, Centre, Colour (8+ locations)
- Hardcoded hex colours replaced with design tokens
- Path traversal validation uses Path.is_relative_to
- Scanner exec() sandbox expanded with additional forbidden attributes
- Lot sizes updated for SEBI Nov 2024 revision
- Cron manager silent exception swallowing replaced with logging
- Gateway bare imports fixed with relative paths

### Fixed — Accessibility
- Skip-nav link target corrected to #main-content on all routes
- Focus trap in modal dialogs (AlertDialog, Dialog) improved for screen readers
- Colour contrast ratio on muted text raised to WCAG AA minimum (4.5:1)

### Fixed — Performance
- Lazy-loaded InvestRoute tabs: 14 tabs code-split individually (~142 KB saved from initial bundle)
- TanStack Query deduplication: identical queries across widgets share a single network request
- WebSocket reconnect backoff: exponential with jitter, capped at 30 s
- WebSocket batch subscribe with reference counting (fewer messages, cleaner unsubscribe)

### Removed
- settingsStore.sandboxMode (mode now in modeStore exclusively)
- ModePill.tsx and SandboxToggle.tsx (replaced by ModeIndicator)
- Dead code: unused FlexLayoutNode imports, orphan utility functions, unreachable switch branches
- Legacy /api/v0/ route prefix (all endpoints now under /api/v1/ or /ft-api/v1/)

## [0.3.0] — 2026-03-30

v0.3.0 "Structured Calm" — Bloomberg precision + Stripe polish + Linear minimalism.

### Added — UI Redesign
- ContentShell universal centering wrapper (max-w-6xl, responsive padding)
- SectionHeader component with optional action button
- DataNumber three-tier numeric display (hero/primary/cell)
- DataDirection profit/loss indicator with color + icon + sign + sr-only text
- 4-level surface hierarchy (Base → Raised → Elevated → Floating)
- CSS custom properties for data-elevation, shadow-elevated, shadow-floating
- Graphite theme (new default) — desaturated blue-indigo accent #7c8be8
- Monochrome theme — zero-color gray accent
- Solarized Dark theme
- Theme v3 migration (6 removed themes → mapped to kept themes)
- react-resizable-panels on /trade (sidebar + Dockview + bottom panel)
- Focus ring 200ms scale-in animation
- Data update pulse (100ms background flash)

### Changed
- GlassCard defaults to solid (glass=false). Glass only on Level 3 floating elements.
- Default theme changed from emerald-night to graphite
- Price tick flash shortened to 300ms
- AnimatedCounter capped at 800ms
- Applied ContentShell to /invest, /learn, /ai, /settings, /admin, /explore, /setup, 404
- Typography scale: 24px route titles, hero numbers per route

### Removed
- 6 themes: Emerald Night, Ocean Depth, Solar Flare, Neon Pulse, Blood Moon, Cyber Dusk
- TextGenerateEffect on page headers (repeat-visit routes)
- BlurFade on section headers
- StaggeredList on card grids (replaced with 150ms container fade)
- hover:-translate-y-0.5 on cards (border-color transition only)
- @utility hover-lift from index.css
- Particles on all routes except /welcome

### Fixed (from v0.2.0-beta audit)
- 43 audit findings resolved (4 critical, 12 high, 15 medium, 12 low)
- Ticker -100% on WS disconnect (LTP=0 guard)
- Stale API key in WS singleton (updateCredentials + reactive hooks)
- Silent widget failures (error banners with retry in Orders/Positions/Holdings)
- Hardcoded dark colors in 8 chart/tool widgets → CSS var reads
- Route nav buttons → Links (WCAG 2.4.4)
- text-muted contrast brightened on all dark themes (WCAG AA)
- Dockview ARIA roles (tablist/tab/tabpanel)
- Dashboard loading skeletons
- Scalper CE/PE color inversion, shadcn/ui migration, error states
- ToolsDropdown portal rendering, Chart theme reactivity
- react-plotly.js excluded from Vite dep optimizer (prevents crash)

## [0.2.0-alpha] — 2026-03-25

OpenAlgo absorption: direct broker connections, analysis tools, platform features.

### Added — Broker Gateway (SP1)
- New packages/gateway/ package: direct connection to 31 brokers via adapter pattern
- BrokerRegistry: multi-account management, N simultaneous broker connections
- Fernet-encrypted credential storage (PBKDF2, per-account salt)
- WebSocket bridge: TickDispatcher replaces ZMQ PUB/SUB (in-process, no separate server)
- Flask auth blueprint: 10 endpoints for broker catalog, account CRUD, OAuth/TOTP/API key/OTP auth flows
- 4 OpenAlgo import shims (token_db, auth_db, config, logging) for submodule isolation
- ContractManager: per-broker master contract SQLite cache
- Startup account reconnection from encrypted credentials
- Frontend: brokerStore (Zustand), gatewayApi client, useBrokerAccounts/useBrokerAuth/useBrokerList hooks
- Setup page: BrokerPicker, ConnectedAccounts, AuthFlowAPIKey, AuthFlowTOTP components

### Added — Analysis Tools (SP2)
- 5 new Plotly.js analysis widgets: GEX Dashboard, Volatility Surface 3D, IV Smile, Straddle P&L Simulator, OI Profile
- Plotly.js integration with shared PlotlyChart wrapper (theme-aware, lazy-loaded)
- 5 backend screener modules: gex.py, vol_surface.py, iv_smile.py, straddle_pnl.py, oi_profile.py
- 6 new Flask analysis endpoints (/ft-api/v1/gex, volsurface, ivsmile, straddlepnl, oiprofile, maxpain)
- OptionChain upgrade: LTP flash animation, max pain badge, gradient OI bars
- OIChart upgrade: Plotly grouped bars replacing CSS, PCR overlay, ATM/Max Pain markers
- Widget count: 21 → 26

### Added — Platform Features (SP3)
- Sandbox paper trading engine (DuckDB, MARKET/LIMIT/SL fills, auto square-off)
- Python strategy runner (AST validation, subprocess isolation, memory limits)
- Action Center: semi-auto order approval queue with configurable TTL
- Security dashboard: IP tracking, auto-ban on threshold, threat detection
- P&L tracker: real-time tradebook P&L time series
- Historify watchlist: scheduled OHLCV download management
- Health/Traffic/Latency monitoring with circular buffer and percentile tracking
- OrderRouter sandbox integration (routes to virtual engine when account is in sandbox mode)

### Added — Infrastructure
- Weekly submodule compatibility CI check (.github/workflows/submodule-check.yml)
- Makefile: start-gateway target for single-process mode
- .env.example: gateway section (MASTER_PASSWORD, FLINTTRADE_PORT, WS_PORT)

## [0.1.0-beta] — 2026-03-24

Full repo audit + god component refactoring. Security hardened, performance optimized, WCAG accessible.

### Added — Security
- Flask API authentication (before_request hook validates API key on all 20+ endpoints)
- SQL injection prevention (table name allowlist + path validation in DuckDB pipeline)
- Telegram bot denies commands by default when chat_id not configured
- Ditto module requires DITTO_ENCRYPTION_KEY (was silently generating ephemeral key)

### Added — Accessibility (WCAG 2.2 AA)
- MotionConfig reducedMotion="user" at app root (all Framer Motion respects OS preference)
- Landmarks (<main>, <header>, <nav>) on all 5 flow routes
- useDocumentTitle hook — page title updates on every route change
- Keyboard-accessible ToolsDropdown (role="menu", Arrow/Escape navigation)
- Keyboard-accessible workspace tab context menu (Shift+F10, Escape)
- ARIA roles for sidebars (Learn, Lab, Automate), workspace tabs, accordion items
- Form labels (aria-label) on all ThemePicker, BackgroundPicker, SettingsTool inputs
- Focus management on AIRoute overlay panels
- role="alertdialog" + aria-modal on SmallScreenOverlay
- role="dialog" on InteractiveTour

### Added — Performance
- vendor-misc chunk split: 1,116 KB → 320 KB (-71%). Tremor/recharts/d3 deferred to async vendor-charts
- WebSocket tick batching via requestAnimationFrame in useWsBridge
- Zustand useShallow selectors for array/object subscriptions (TopBar, GlassCard, RiskPanel, MTMMonitor)
- Dockview layout auto-save debounced to 500ms (was every pixel of drag)
- Build target set to es2022 (smaller output, native syntax)

### Changed — Code Quality
- ChartWidget split: 3,001 → 628 lines (indicators.ts, useChartInit, useDrawingTools, useIndicators, ChartLegend, types)
- OptionChainWidget split: 1,376 → 491 lines (SymbolSearch, BasketPanel, useOptionChainData, gridConfig, formatters, types)
- AutomateRoute split: 1,338 → 81 lines (7 section components)
- SetupRoute split: 1,422 → 367 lines (8 step components)
- SettingsTool split: 1,278 → 212 lines (11 section components with aria-labels)
- getWsService return type corrected to WebSocketService | null (was null!)
- Timer leaks fixed in OrderPad + OptionChain (ref-based cleanup)
- Dead FlexLayoutNode interface removed from 6 analysis widgets
- Relative imports converted to @/ alias in 6 analysis widgets
- prev_close added to Quote type, post() body type widened (removed double casts)
- useGlobalKeys now logs errors (was silently swallowing trading action failures)

### Fixed — Security
- Flask error responses sanitized (no more str(exc) leaked to clients)
- Webhook server binds to 127.0.0.1 by default (was 0.0.0.0)
- useDuration memory leak in LabRoute (setInterval in useState never cleared)
- Dockview panel listeners now disposed on unmount

### Fixed — Accessibility
- textMuted contrast fixed in 5 dark themes (Terminal Green, Ocean Blue, Sunset, Neon, Forest)
- Solarized Dark profit color contrast improved (#859900 → #a3b900)
- WelcomeRoute skips animation when prefers-reduced-motion enabled
- DailyWelcome: <p role="button"> replaced with native <button>
- SetupRoute: misused role="tablist" removed from progress indicator
- pulse-glow CSS animation changed to opacity-only (was animating box-shadow)
- bg-[rgba(...)] replaced with bg-loss/10 design token in DailyWelcome
- Circular chunk warning eliminated (cmdk + @floating-ui moved to vendor-radix)
- Unused deps (marked, react-responsive-carousel) moved to devDependencies

### Changed
- SEBI compliance doc rewritten with full circular reference
- CONTRIBUTING.md rewritten with detailed commit guidelines
- .gitignore cleaned up
- Test counts: 979 Python + 36 Vitest = 1,015 total

### Removed
- 50 internal dev docs removed from public repo (archived locally)
- DEVLOG.md, SOP.md decommissioned (replaced by CHANGELOG + CONTRIBUTING)

## [0.1.0-alpha] — 2026-03-21

Feature-complete alpha release. 13 packages, 1,021 tests, 7 routes, 21 widgets, full-stack wiring.

### Added — UI Foundation
- Geist font (headings) + Inter (body) + JetBrains Mono (data) — 3-tier font system
- 60+ design tokens (surfaces, borders, text, trading semantics)
- 5 built-in themes: Midnight, Obsidian, Terminal Green, Ocean Blue, Light
- SVG Logo component (LogoIcon, LogoWordmark, LogoFull)
- Density modes (comfortable/compact, auto-detect on small screens)

### Added — Routes & Navigation
- 7 app routes: /learn, /invest, /trade, /lab, /automate, /ai, /settings
- Cinematic /welcome screen with pillar cards and theme switcher
- /explore demo mode with sample data previews (no broker needed)
- /setup onboarding wizard with persona x interest matrix
- Global route tabs in TopBar (Learn · Invest · Trade · Lab · Automate · AI)
- 6 workspace presets: Scalper Zone, Options Desk, Market Watch, Analysis, Risk Monitor, Investor View

### Added — Full-Stack Wiring
- 100% OpenAlgo API coverage (45+ endpoints wired to UI)
- 20 FlintTrade backend endpoints (backtest, signals, sentiment, RAG, cron, audit, safety, webhooks)
- ftApi.ts TypeScript client for FlintTrade Python backend
- Market Intelligence: 4 new tabs (GEX, IV Smile, Max Pain, OI Profile)
- Synthetic Future in OptionChain header, Margin in OrderPad
- Market status badge in TopBar, holiday-aware DailyWelcome
- REST ticker fallback when WebSocket disconnects
- AI Advisor embedded in /ai Chat section with streaming + MCP

### Added — UI Libraries
- Tremor (dashboard charts, KPI cards, sparklines, tracker)
- Magic UI (AnimatedCounter, ShimmerButton, Particles, BlurFade)
- Aceternity UI (HoverCard spotlight, TextGenerateEffect, Meteors)

### Added — Infrastructure
- ErrorBoundary wrapping entire app
- 404 catch-all route (NotFoundRoute)
- connectionStore persisted to localStorage
- Mobile/small screen warning overlay
- prefers-reduced-motion media query (WCAG 2.3.3)
- Semantic landmarks (<header>, <main>, <nav>), skip-to-content link
- ARIA roles on route tabs, sidebar navigation, icon buttons

### Fixed
- 80+ hardcoded palette colors → design tokens (text-profit/text-loss/text-warning)
- isMarketHours() deduplicated to lib/market.ts, polling now dynamic
- Dockview: slim tabs (28px), singleTabMode, hidden close buttons
- window.prompt/confirm → inline rename/delete UI
- TOOLS/WIDGETS buttons hidden on non-trade routes
- Sidebar border-l-2 jump fixed (transparent border on inactive)
- Light theme Dockview CSS uses var() tokens
- Setup wizard presets mapped to real workspace presets
- Empty Dockview state shows Add Widgets / Choose Template overlay
- DailyWelcome suggestions now clickable
- Removed unused deps (lodash, oakscriptjs)
- docker-compose: removed deleted packages, fixed ports

### Tests
- Python: 985 passed, 3 skipped
- Vitest: 36 passed (10 new ticker fallback tests)
- TypeScript: 0 errors (strict mode)
- Build: clean

## [0.0.1-dev] — 2026-03-14

### Added — Core
- async OpenAlgo client — 45+ endpoints, rate limiting (10 OPS orders,
  2 OPS smart, 50 OPS general), exponential backoff retry
- Pydantic models — Order, Position, Quote, Fund, OptionGreek, etc.
- Settings.from_env(), exceptions hierarchy
- FlintTradeApp entry point — wires all 12 packages into single startup

### Added — Engine
- 5-layer SafetySystem (OrderValidation, PositionLimits, PortfolioRisk,
  DailyPnL, KillSwitch)
- Per-exchange market hours (NFO/BFO 15:30, CDS 17:00, MCX 23:30, DELTA 24/7)
- OrderRouter wired to OpenAlgoClient + AuditLogger
- StrategyRunner + StrategyScheduler — async tick loop, deploy freeze guard
- EMACrossover — first concrete strategy with position reversal

### Added — Data & Historical
- SEBI audit trail (JSONL append-only, gzip rotation, 5-year retention)
- DuckDB storage — ticks, trades, daily summaries
- Multi-source downloader, free NSE data, DuckDB pipeline, expiry manager

### Added — Screener & Analysis
- Option chain, OI spurt, futures quadrant, portfolio Greeks, IV analysis

### Added — Backtest
- Event-driven simulator, walk-forward optimizer, 12 strategy templates
- Monte Carlo analysis, performance metrics (Sharpe, Sortino, Calmar, VaR)
- React backtest UI — config panel, results, equity curves, compare mode

### Added — AI & Integration
- LLM client (LM Studio, Ollama, Anthropic, OpenAI), RAG, ML signals
- News sentiment, MCP bridge, stock advisor
- TradingView webhooks, ChartInk, visual flow builder, alerter

### Added — Automation & Ditto
- Cron manager (5 jobs), Telegram bot with /kill switch
- Position mirroring, margin-aware allocation, trailing SL, risk manager

### Added — Frontend
- terminal: Dockview widget-composable trading terminal — 14 widgets (TSX),
  7 tools, TypeScript strict, shadcn/ui, Zustand+Jotai+TanStack Query

### Added — Infrastructure
- Docker support — docker-compose.yml for Windows/macOS/Linux/Raspberry Pi
- Cross-platform setup guides (docs/setup/)
- systemd service file, production deployment scripts
- Feature flags — ENABLE_BACKTEST, ENABLE_AI

### Added — Initial Setup
- Monorepo — 12 packages with per-package CLAUDE.md + AGENTS.md
- CI/CD — GitHub Actions (pytest, ruff, secrets check)
- SEBI compliance framework — rate limits, kill switch architecture, audit
- Infrastructure — nginx, systemd, WireGuard, fail2ban, deploy scripts
- Git-native bug tracking system
- Documentation — OpenAlgo API reference, tools guide, machine configs

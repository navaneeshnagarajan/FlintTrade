# FlintTrade v0.1.0-beta Sprint Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v0.1.0-beta by March 30, 2026 — every widget live, every tool functional, every route working, every doc accurate, every test green.

**Architecture:** Single React app (Dockview v5), 11 Python packages, OpenAlgo gateway. Three personas (/terminal, /invest, /learn). Widget-composable workspace.

**Tech Stack:** TypeScript 5.x strict, React 19, Vite 6.4, Tailwind v4, shadcn/ui, Dockview v5, LWC v5, Zustand + Jotai + TanStack Query, Python 3.12, pytest, Vitest

**Deadline:** March 30, 2026 (11 days from plan creation)

**References:**
- Approved spec: `docs/superpowers/specs/2026-03-19-flinttrade-v2-foundation-design.md`
- Design reference: `.reference/screenshots/groww/DESIGN_NOTES.md`, `.reference/screenshots/oipulse/DESIGN_NOTES.md`
- Repo absorption map: `docs/REPO_FEATURE_MAP.md`
- 222 cloned repos: `.reference/repos/`

---

## PLAN.md Sync (tick items that are already done)

Before starting any work, sync PLAN.md to reality. These Week 3-5 items have code but unchecked boxes:

- [ ] Tick: SectorMap, Calculator, MTMMonitor, RiskPanel, News, Ticker, AIAdvisor widgets (all 7 .tsx files exist)
- [ ] Tick: /setup, /invest, /learn routes (all .tsx files exist)
- [ ] Tick: All 7 tools (BacktestLab, FlowBuilder, MarketIntelligence, PnLDashboard, Settings, StrategyBuilder, TradeJournal .tsx files exist)
- [ ] Tick: Widget factory registration, WidgetPicker catalog, layout presets
- [ ] Tick: indicators package (13 indicators, 42 tests)
- [ ] Tick: EMA/Supertrend/DEMA strategy
- [ ] Update deadline from April 30 to March 30
- [ ] Update test counts to current (738)
- [ ] Commit: `chore: sync PLAN.md — tick completed items, update deadline to March 30`

---

## Task Group 1: Fix What's Broken (Critical Path)

### Task 1.1: Verify Chart History Fix

The `timestamp` field fix was applied but not tested against live OpenAlgo.

**Files:** `packages/terminal/src/types/api.ts`, `packages/terminal/src/components/Chart.tsx`, `packages/terminal/src/widgets/analysis/Chart/ChartWidget.tsx`

- [ ] Start OpenAlgo + terminal dev server (`make dev`)
- [ ] Open browser to localhost:5173/terminal
- [ ] Open Chart widget — verify NIFTY candles render
- [ ] Take Playwright screenshot as evidence
- [ ] If candles don't render: use OpenAlgo MCP to verify history response format, debug in browser console
- [ ] Test Scalper 3-panel charts (CE/Spot/PE) — verify candles in all 3
- [ ] Commit: `fix(terminal): verify chart history timestamp field — candles loading`

### Task 1.2: Fix WebSocket Tick Subscriptions

Ticker bar shows dashes. Index cards show dashes. WebSocket connects and authenticates but subscriptions don't deliver ticks.

**Files:**
- Debug: `packages/terminal/src/services/websocket.ts`
- Debug: `packages/terminal/src/hooks/useWsBridge.ts`
- Debug: `packages/terminal/src/atoms/marketAtoms.ts`
- Reference: Use OpenAlgo MCP to look up WebSocket subscribe format

- [ ] Use OpenAlgo MCP: search "WebSocket subscribe format symbols mode"
- [ ] Open browser console, check WS messages (connected? authenticated? subscribed? ticks arriving?)
- [ ] Verify subscribe payload matches OpenAlgo v2 docs exactly
- [ ] Verify useWsBridge correctly writes ticks into Jotai atoms
- [ ] Verify TickerBar reads from correct atoms
- [ ] Fix any mismatches found
- [ ] Playwright screenshot: ticker bar showing live NIFTY/SENSEX/BANKNIFTY prices
- [ ] Commit: `fix(terminal): WebSocket tick subscriptions — ticker bar + indices live`

### Task 1.3: Widget-by-Widget Live Testing

Test EVERY existing widget against Dhan Sandbox. Fix bugs as found.

**For each widget:** Open it, verify it shows live data, take Playwright screenshot.

- [ ] Dashboard — funds, margin, P&L, positions, orders (verified earlier: funds show ₹9,99,906)
- [ ] Scalper — 3-panel charts, strike selector, order buttons, keyboard shortcuts
- [ ] OrderPad — symbol search, order submission, validation
- [ ] Positions — live position table with P&L
- [ ] Orders — order book with status
- [ ] Holdings — delivery holdings
- [ ] TradeBook — trade history
- [ ] Chart — candlesticks, indicators, interval switching
- [ ] OptionChain — expiry picker, strikes, inline orders
- [ ] OIChart — horizontal bars, PCR, S/R levels
- [ ] Straddle — ATM tracking, overlays
- [ ] Depth — 5-level bid/ask
- [ ] Greeks — portfolio Delta/Gamma/Theta/Vega
- [ ] Watchlist — quote polling, sparklines, search
- [ ] SectorMap — treemap rendering
- [ ] Calculator — risk/reward calculations
- [ ] MTMMonitor — P&L tracking
- [ ] RiskPanel — margin/position/PnL progress bars
- [ ] Ticker — scrolling prices
- [ ] Place a test order through Scalper (BUY 1 SBIN MIS MARKET)
- [ ] Commit after fixing all bugs: `fix(terminal): live testing — N bugs fixed across M widgets`

---

## Task Group 2: Eliminate All Stubs

### Task 2.1: News Feed Widget — Wire to Real Data

**Files:**
- Modify: `packages/terminal/src/widgets/utility/News/NewsWidget.tsx`
- Reference: `.reference/repos/tier1-core/finnews-ai/`
- Reference: `.reference/screenshots/oipulse/41-announcement.png`

- [ ] Read finnews-ai source for RSS/API patterns
- [ ] Implement news fetch from free source (RSS feeds: MoneyControl, Economic Times, LiveMint)
- [ ] Add sentiment tagging (rule-based: bullish/bearish/neutral keywords)
- [ ] Wire to actual data — no placeholder "Configure in Settings"
- [ ] Sentiment filter buttons (All/Bullish/Bearish) functional
- [ ] Keyword search functional
- [ ] Tests for news parsing
- [ ] Commit: `feat(terminal): News widget — live RSS feeds with sentiment tagging`

### Task 2.2: AI Advisor Widget — Wire Python Backend

**Files:**
- Modify: `packages/terminal/src/widgets/utility/AIAdvisor/AIAdvisorWidget.tsx`
- Modify: `packages/core/src/app.py` — add HTTP endpoint for AI advisor
- Reference: `packages/ai/src/advisor.py`, `packages/ai/src/llm_client.py`

- [ ] Add `/api/v1/advisor` POST endpoint in app.py (Flask) that calls advisor.py
- [ ] Wire AIAdvisorWidget to call this endpoint
- [ ] `isAIConfigured()` should check workspace.json for LLM provider config
- [ ] Show "Configure LLM in Settings → AI" when not configured (not broken empty state)
- [ ] When configured: chat works, sends context (positions + market data) to LLM
- [ ] Tests for advisor endpoint
- [ ] Commit: `feat(terminal): AI Advisor — wired to Python LLM backend`

### Task 2.3: Flow Builder — Absorb Visual Canvas from openalgo-flow

**Files:**
- Modify: `packages/terminal/src/tools/FlowBuilder/FlowBuilderTool.tsx`
- Reference: `.reference/repos/tier1-core/openalgo-flow/frontend/src/pages/Editor.tsx`
- Reference: `.reference/repos/tier1-core/openalgo-flow/frontend/src/components/nodes/`
- New dep: Add `@xyflow/react` (ReactFlow) to package.json

- [ ] Read openalgo-flow Editor.tsx + BaseNode.tsx + NodePalette.tsx + ConfigPanel.tsx
- [ ] Install @xyflow/react
- [ ] Build visual canvas with drag-drop nodes (at minimum: Start, PlaceOrder, Condition, Log, Delay)
- [ ] Node palette sidebar with all 54 node type definitions
- [ ] Config panel for selected node properties
- [ ] Edge connections between nodes
- [ ] Save/load workflow as JSON
- [ ] Execute workflow (connect to Python backend for order execution)
- [ ] Tests for flow serialization
- [ ] Commit: `feat(terminal): Flow Builder — visual canvas with ReactFlow, 54 node types`

### Task 2.4: Settings — Complete All 9 Sections

**Files:**
- Modify: `packages/terminal/src/tools/Settings/SettingsTool.tsx`

- [ ] Complete: Keyboard Shortcuts section (scalper shortcuts: Shift+arrows for Buy/Sell CE/PE)
- [ ] Complete: LLM Config section (provider dropdown, host, model, API key)
- [ ] Complete: Telegram section (bot token, chat ID, enable/disable, test button)
- [ ] Complete: Ditto section (account list, allocation mode)
- [ ] Complete: Automation section (cron jobs list, enable/disable)
- [ ] Add: Restart Services button (reconnect WS, refresh API, clear query cache)
- [ ] All settings save to workspace.json
- [ ] Commit: `feat(terminal): Settings — all 9 sections complete`

---

## Task Group 3: Upgrade Existing to Reference Quality

### Task 3.1: Chart — Absorb from openalgo-chart

**Files:**
- Modify: `packages/terminal/src/widgets/analysis/Chart/ChartWidget.tsx`
- Reference: `.reference/repos/external-all/openalgo-chart/src/`

- [ ] Read openalgo-chart indicator implementations and drawing tools
- [ ] Add indicators: VWAP, Ichimoku, Pivot Points, Stochastic, ADX, ATR (from 7 to 15+)
- [ ] Add configurable indicator parameters (period, multiplier) — not hardcoded
- [ ] Add drawing tools: Trend Line, Fib Retracement, Horizontal Line, Rectangle, Text (from 2 to 7+)
- [ ] Drawing properties panel (color, line width, style)
- [ ] Multi-chart grid support (1x1, 1x2, 2x1, 2x2) — absorb from openalgo-chart ChartGrid
- [ ] Chart snapshot/screenshot button
- [ ] Commit: `feat(terminal): Chart — 15+ indicators, 7 drawing tools, multi-grid`

### Task 3.2: Option Chain — Glide Data Grid + SSE

**Files:**
- Modify: `packages/terminal/src/widgets/analysis/OptionChain/OptionChainWidget.tsx`
- Reference: `.reference/repos/tier2-ecosystem/option-chain/`

- [ ] Replace TanStack Table with Glide Data Grid for streaming performance (100K+ updates/sec)
- [ ] Add GREEKS toggle (show/hide Delta/Gamma/Theta/Vega columns)
- [ ] Add BASKET button for multi-leg order creation
- [ ] Add OI interpretation badges (Long Build Up, Short Covering, etc.) — from OiPulse patterns
- [ ] Real-time PCR calculation
- [ ] Commit: `feat(terminal): Option Chain — Glide Data Grid, Greeks toggle, OI interpretation`

### Task 3.3: Ticker Bar — Add MCX Commodities

**Files:**
- Modify: `packages/terminal/src/chrome/TickerBar.tsx`
- Modify: `packages/terminal/src/atoms/marketAtoms.ts`

- [ ] Add MCX instruments: GOLD, SILVER, CRUDEOIL, NATURALGAS (match Groww 915 ticker)
- [ ] Subscribe to WebSocket for these additional instruments
- [ ] Show all 11 instruments in scrolling ticker (not just 4 indices)
- [ ] Commit: `feat(terminal): TickerBar — 11 instruments including MCX commodities`

### Task 3.4: Python Indicators — Expand to 50+

**Files:**
- Modify: `packages/indicators/src/` (all files)
- Reference: `.reference/repos/tier1-core/openalgo-python-library/` indicators package
- Reference: `.reference/repos/marketcalls-all/pyindicators/`

- [ ] Read openalgo-python-library indicators (100+ classes)
- [ ] Add missing momentum: CCI, BOP, ROC, CMO, TRIX, StochRSI
- [ ] Add missing trend: TEMA, WMA, HULL, Ichimoku, Parabolic SAR
- [ ] Add missing volatility: Keltner Channels (done), Donchian Channel, NATR
- [ ] Add missing volume: OBV, AD, CMF, MFI
- [ ] Add Numba streaming versions for real-time calculation
- [ ] Wire new indicators into Chart widget indicator dropdown
- [ ] Tests for all new indicators
- [ ] Commit: `feat(indicators): expand to 50+ indicators, Numba streaming`

### Task 3.5: Strategies — Absorb 28 from Reference Repos

**Files:**
- Create: `packages/backtest-engine/src/strategies/` (multiple files)
- Reference: `.reference/repos/tier3-ai-research/AlgoTrading/`
- Reference: `.reference/repos/tier4-community/openalgostratagies/`

- [ ] Read AlgoTrading repo: identify top 20 strategies across Trend/Momentum/Mean-reversion/Volatility/Volume
- [ ] Read openalgostratagies: KAMA, MA Crossover, MACD, Bollinger, Indian F&O
- [ ] Implement all 28 strategies as Python classes (extending BaseStrategy)
- [ ] Tests for each strategy
- [ ] Commit: `feat(backtest-engine): 28 strategies absorbed from AlgoTrading + openalgostratagies`

---

## Task Group 4: Routes

### Task 4.1: Setup Wizard — Quick/Guided/Advanced

**Files:**
- Modify: `packages/terminal/src/routes/SetupRoute.tsx`

- [ ] Quick Setup (2 steps): OpenAlgo URL + API key → test connection → persona pick → redirect
- [ ] Guided Setup (5 steps): persona, connection test, experience level, trading defaults, done
- [ ] Advanced Setup (7 steps): Guided + LLM config + Telegram + data paths + risk limits
- [ ] All settings saved to workspace.json via settingsStore
- [ ] First-time detection: if no workspace.json, redirect to /setup
- [ ] Tests for wizard flow
- [ ] Commit: `feat(terminal): Setup wizard — Quick/Guided/Advanced modes`

### Task 4.2: Investor Route (/invest) — Full Build

**Files:**
- Modify: `packages/terminal/src/routes/InvestRoute.tsx`
- Reference: `.reference/repos/marketcalls-all/etftracker/`
- Reference: `.reference/repos/marketcalls-all/virfolio/`

- [ ] Portfolio Tracker — absorb virfolio patterns (holdings + allocation pie chart)
- [ ] Holdings view — reuse terminal Holdings widget with investor context
- [ ] Net Worth Dashboard — total across all accounts (equity + MF + gold + FD)
- [ ] Mutual Fund Explorer — jugaad-data MF NAV API
- [ ] SIP Calculator — compound interest math
- [ ] ETF Screener — from etftracker patterns
- [ ] Asset Quilt — yearly returns heatmap (from etftracker Dashboard 1)
- [ ] Sector Rotation — from etftracker + sector-rotation-map RRG
- [ ] Stock Screener — basic screener (from openscreener patterns)
- [ ] IPO Tracker — basic IPO list
- [ ] Commit: `feat(terminal): /invest route — 10 investor features`

### Task 4.3: Learn Route (/learn) — Content

**Files:**
- Modify: `packages/terminal/src/routes/LearnRoute.tsx`

- [ ] Market Basics — What are stocks, F&O, mutual funds (markdown content)
- [ ] Glossary — Trading terms dictionary (searchable)
- [ ] Strategy Library — Browse all 29+ strategies with explanations
- [ ] Paper Trading — link to Dhan Sandbox / OpenAlgo sandbox mode
- [ ] Video Hub — curated YouTube trading education links
- [ ] Commit: `feat(terminal): /learn route — Market Basics, Glossary, Strategy Library, Video Hub`

---

## Task Group 5: Market Intelligence Deep Build

### Task 5.1: Market Intelligence Tool — 10 Dashboards from etftracker

**Files:**
- Modify: `packages/terminal/src/tools/MarketIntelligence/MarketIntelligenceTool.tsx`
- Reference: `.reference/repos/marketcalls-all/etftracker/`
- Reference: `.reference/screenshots/oipulse/` (FII/DII, sector stats, sector heatmap)

- [ ] Read etftracker: all 10 dashboards
- [ ] Tab 1: Market Breadth (advances/declines/unchanged)
- [ ] Tab 2: FII/DII Flows (capital market + derivative stats) — from OiPulse pattern
- [ ] Tab 3: Sector Rotation (sortable by 1D/1W/1M/3M/6M/1Y)
- [ ] Tab 4: Sector Heatmap (treemap by market cap)
- [ ] Tab 5: Relative Rotation Graph (D3.js or Plotly, from sector-rotation-map)
- [ ] Tab 6: Global Indices (world map or table)
- [ ] Tab 7: India VIX tracker
- [ ] Tab 8: Participant-wise OI (FII/Pro/DII/Client)
- [ ] Tab 9: Delivery data
- [ ] Tab 10: Correlation matrix (VIX vs Nifty vs Gold vs Crude)
- [ ] Commit: `feat(terminal): Market Intelligence — 10 dashboards from etftracker + OiPulse`

---

## Task Group 6: Python Backend Upgrades

### Task 6.1: VectorBT Integration

**Files:**
- Modify: `packages/backtest-engine/src/simulator.py`
- Modify: `packages/backtest-engine/src/metrics.py`

- [ ] Install vectorbt
- [ ] Add VectorBT parameter sweep mode (grid search over indicator params)
- [ ] Add equity curve generation
- [ ] Add tearsheet generation (from VectorBT-Tearsheets patterns)
- [ ] Wire to BacktestLab tool via Flask endpoint
- [ ] Commit: `feat(backtest-engine): VectorBT integration for parameter sweeps + tearsheets`

### Task 6.2: Rust/PyO3 Backtest Prototype

**Files:**
- Create: `packages/backtest-engine/rust/` (Cargo project)
- Reference: `.reference/repos/marketcalls-all/raptorbt/`

- [ ] Read raptorbt source
- [ ] Create minimal Rust tick-level backtest engine
- [ ] PyO3 binding for Python interop
- [ ] Benchmark: Rust vs Python for 1M ticks
- [ ] Commit: `feat(backtest-engine): Rust/PyO3 tick-level prototype`

### Task 6.3: Ditto Package — Absorb AlgoMirror

**Files:**
- Modify: `packages/ditto/src/mirror.py`
- Reference: `docs/references/ENHANCEMENT_BLUEPRINT.md`

- [ ] Read ENHANCEMENT_BLUEPRINT.md AlgoMirror patterns
- [ ] Add WebSocket-based position mirroring (not polling)
- [ ] Add multiplier-based allocation modes
- [ ] Add broker cost metadata support in workspace.json
- [ ] Tests for mirror modes
- [ ] Commit: `feat(ditto): AlgoMirror patterns — WS mirror, multiplier allocation`

---

## Task Group 7: Logo & Branding

### Task 7.1: Logo Redesign

**Files:**
- Modify: `packages/terminal/public/logo.svg`
- Modify: `packages/terminal/public/favicon.svg`
- Modify: `docs/assets/logo.svg`

- [ ] Study OpenAlgo's logo design (clean, geometric, professional)
- [ ] Design: flint spark (sharp angular, not soft flame) + upward trading line
- [ ] Iterate 5+ versions, test at 16px (tab), 32px (favicon), 120px (README), 512px (splash)
- [ ] Ensure it works on both dark and light backgrounds
- [ ] Place in: public/logo.svg, public/favicon.svg, docs/assets/logo.svg, TopBar, README, OG meta
- [ ] Commit: `feat: FlintTrade logo v2 — sharp flint spark, tested at all sizes`

---

## Task Group 8: Performance

### Task 8.1: Code-Split TerminalRoute

TerminalRoute chunk is 1,255 KB — needs splitting.

**Files:**
- Modify: `packages/terminal/src/layout/widgetFactory.tsx`
- Modify: `packages/terminal/src/routes/TerminalRoute.tsx`

- [ ] Lazy-load each widget/tool with `React.lazy()` + `Suspense`
- [ ] Add `manualChunks` in vite.config.ts for large deps (lightweight-charts, dockview, glide-data-grid)
- [ ] Target: no chunk > 500KB
- [ ] Commit: `perf(terminal): code-split widgets + manual chunks — no chunk > 500KB`

### Task 8.2: Glide Data Grid for Option Chain

- [ ] Replace TanStack Table in OptionChainWidget with Glide Data Grid
- [ ] Canvas-rendered for 100K+ updates/sec (streaming OI/LTP)
- [ ] Commit: `perf(terminal): Option Chain — Glide Data Grid canvas-rendered`

---

## Task Group 9: Documentation (35 files)

### Task 9.1: Rewrite 5 Files

- [ ] README.md — current test count (738), 1 React app, no TOTP, correct architecture diagram, logo
- [ ] docs/ARCHITECTURE.md — submodule not subtree, Dockview not FlexLayout, Zustand/Jotai/TanStack not DataBus
- [ ] docs/references/TOOLS_AND_DEPS.md — all new deps listed

### Task 9.2: Update 18 Files

- [ ] CLAUDE.md — widget arch, 11 packages, correct test count
- [ ] AGENTS.md — remove F-key/TOTP
- [ ] CHANGELOG.md — remove TOTP claims
- [ ] CONTRIBUTING.md — correct test count, March 30 deadline
- [ ] REPOS.md (root) — sync with docs/references/REPOS.md
- [ ] docs/OPERATIONS_GUIDE.md — check stale refs
- [ ] docs/SEBI_COMPLIANCE.md — remove TOTP, add April 2026 STT rates (0.05% futures, 0.15% options)
- [ ] docs/references/REPOS.md — sync with root
- [ ] docs/references/OPENALGO_API.md — verify accuracy (ping=POST, optionchain=underlying+expiry_date)
- [ ] docs/machine-setup/QUICKSTART.md — Dockview/TS, no F1-F8
- [ ] docs/setup/linux.md, macos.md, windows.md, raspberry-pi.md — remove old module refs, fix ports
- [ ] infra/cron/README.md — remove TOTP login_job
- [ ] flint.toml — remove TOTP
- [ ] .env.example — verify 4 blank vars
- [ ] .github/ISSUE_TEMPLATE/*.md — check current

### Task 9.3: Check 10 Package READMEs

- [ ] packages/core/README.md through packages/ditto/README.md — check accuracy, remove TOTP

### Task 9.4: Archive, Delete, Mark

- [ ] Archive: docs/superpowers/plans/2026-03-18-phase1-flexlayout-foundation.md → historical/
- [ ] Delete: findings.md, task_plan.md, progress.md (temp files)
- [ ] Mark: docs/references/ENHANCEMENT_BLUEPRINT.md — "Absorbed into v2 spec"
- [ ] Remove ALL TOTP references across 9+ files (DO NOT touch infra/ submodules)

### Task 9.5: CI/CD Update

- [ ] Add `tsc --noEmit` step to GitHub Actions node-tests job
- [ ] Commit: `docs: 35-file documentation cleanup + CI tsc step`

---

## Task Group 10: Final Testing + Beta Tag

### Task 10.1: Full Regression Test

- [ ] `tsc --noEmit` — zero errors
- [ ] `npm run build` — zero warnings, all chunks < 500KB
- [ ] `npx vitest run` — all tests pass
- [ ] `make test` — 712+ Python tests pass
- [ ] `make lint` — ruff clean

### Task 10.2: Playwright Full Screenshot Suite

- [ ] Screenshot every widget (21) with live data
- [ ] Screenshot every tool (7)
- [ ] Screenshot every route (/terminal, /setup, /invest, /learn)
- [ ] Screenshot every layout preset (7)

### Task 10.3: Security Audit (SOP Step 10)

- [ ] No API keys in localStorage (sessionStorage or backend proxy)
- [ ] Rate limiters wired to all API calls
- [ ] All user inputs validated at trust boundaries
- [ ] hmac.compare_digest() for secret comparisons
- [ ] CSP header on all HTML pages
- [ ] Devtools middleware disabled in production
- [ ] Dev server bound to 127.0.0.1 not 0.0.0.0

### Task 10.4: Beta Release

- [ ] Update VERSION file to 0.1.0-beta
- [ ] Update CHANGELOG.md with beta release notes
- [ ] Final DEVLOG entry
- [ ] Git tag: `git tag -a v0.1.0-beta -m "Beta release — all widgets live, all tools functional"`
- [ ] Push tag: `git push origin v0.1.0-beta`
- [ ] Create GitHub Release with changelog

---

## Commit Sequence

Each task group gets its own commit(s) with conventional format and plan step numbers in body.

| Group | Commit prefix | Description |
|-------|--------------|-------------|
| Sync | `chore:` | PLAN.md sync |
| 1.1 | `fix(terminal):` | Chart history verification |
| 1.2 | `fix(terminal):` | WebSocket tick subscriptions |
| 1.3 | `fix(terminal):` | Live testing bug fixes |
| 2.1 | `feat(terminal):` | News widget live |
| 2.2 | `feat(terminal):` | AI Advisor wired |
| 2.3 | `feat(terminal):` | Flow Builder visual canvas |
| 2.4 | `feat(terminal):` | Settings complete |
| 3.1 | `feat(terminal):` | Chart upgrade |
| 3.2 | `feat(terminal):` | Option Chain Glide Data Grid |
| 3.3 | `feat(terminal):` | TickerBar MCX |
| 3.4 | `feat(indicators):` | 50+ indicators |
| 3.5 | `feat(backtest-engine):` | 28 strategies |
| 4.1 | `feat(terminal):` | Setup wizard |
| 4.2 | `feat(terminal):` | /invest route |
| 4.3 | `feat(terminal):` | /learn route |
| 5.1 | `feat(terminal):` | Market Intelligence 10 dashboards |
| 6.1 | `feat(backtest-engine):` | VectorBT |
| 6.2 | `feat(backtest-engine):` | Rust/PyO3 prototype |
| 6.3 | `feat(ditto):` | AlgoMirror patterns |
| 7.1 | `feat:` | Logo v2 |
| 8.1 | `perf(terminal):` | Code splitting |
| 8.2 | `perf(terminal):` | Glide Data Grid |
| 9.x | `docs:` | Documentation cleanup |
| 10.x | `chore:` | Beta tag |

---

*This plan includes EVERYTHING from the approved spec, PLAN.md unchecked items, Phase 10 findings, and deferred features moved to beta scope per user decision on 2026-03-19.*

# FlintTrade — Development Roadmap

> Single source of truth for what to build next.
> Every Claude Code session reads this + CLAUDE.md + SOP.md before starting.
> Approved spec: `docs/superpowers/specs/2026-03-19-flinttrade-v2-foundation-design.md`
> **Beta sprint plan: `docs/superpowers/plans/2026-03-19-beta-sprint.md`** (10 task groups, everything included)
> Deadline: **March 30, 2026 (v0.1.0-beta)**

---

## Current State (updated 2026-03-21 — post UI overhaul + onboarding session)

- **Version:** 0.1.0-alpha → beta pending user verification
- **Tests:** 36 terminal (Vitest) + 985 Python (pytest, 3 skipped) = 1,021 total
- **Terminal:** 21 widgets (TSX) + 4 tools + 7 routes + /welcome + /explore + /settings in Dockview v5 shell
- **TypeScript migration:** Complete. Zero JSX/JS files. Strict mode, zero `any` types. tsc: 0 errors.
- **Python:** 13 packages (11 + tick-engine Rust/PyO3 + indicators), 985 tests passing (3 skipped — vectorbt absent)
- **CI:** GitHub Actions green (python-tests + node-tests + secrets-check). Fixed ruff E402+F841 in app.py.
- **Packages:** 12 Python + 1 React (terminal). tick-engine: new Rust/PyO3 wheel installed.
- **Dependencies:** All v2 deps installed + Glide Data Grid 6 (lodash added), @glideapps/glide-data-grid v6.0.3. WinLibs GCC 15.2 + GNU Rust toolchain on Nitro.
- **State:** Zustand stores (4), Jotai atoms, TanStack Query hooks (6), WebSocket service with ping/pong — all wired.
- **Shell:** Dockview canvas, TopBar (global Learn/Invest/Trade route tabs), TickerBar (16 instruments incl. MCX/CDS), WidgetPicker, ToolsDropdown — all TSX + shadcn/ui. 13 layout presets (7 original + 6 new).
- **Performance:** TerminalRoute 1,251KB → 19KB. vendor-glide 196KB. All chunks < 500KB.
- **Option Chain:** Glide DataGrid canvas-rendered (replaced DOM table). 3 tabs: LTP/OI/GREEKS. ATM highlight, basket actions, OI bars. Searchable stock symbol combobox.
- **Chart:** 23 indicators total (15 from prior sprint + 8 new: Williams %R, CCI, DEMA, Hull MA, Parabolic SAR, OBV, Keltner, VWMA). 7 drawing tools. Configurable indicator periods.
- **Python indicators API:** POST /api/v1/indicators/compute (23 tests). NaN→null, per-indicator error isolation.
- **Rust tick-engine:** packages/tick-engine/ — TickSimulator + EMA crossover + Sharpe/drawdown metrics (25 tests, maturin abi3-py312 wheel).
- **Phase 1A (UI Foundation) COMPLETE:** Geist font (headings) + Inter (body) + JetBrains Mono (data). 60+ design tokens. SVG Logo component. 1,182 arbitrary values replaced with tokens across 29 files. Density modes.
- **Phase 1B (Onboarding + Navigation) COMPLETE:** Global route tabs (Learn/Invest/Trade) in TopBar. Cinematic /welcome screen (6-pillar CSS animation). Setup wizard interest matrix (6 cards). Daily Welcome card (context-aware). Interactive Tour (6 pulsing dots). Workspace dropdown menu (New Blank/Clone/Template + rename/delete). Smart redirect (first-time→/welcome, returning→persona route).
- **Phase 2 (Widget Redesigns) COMPLETE:** All 26 widget/tool/route files restyled with design tokens. Zero arbitrary text-[Npx]/bg-[#hex]/border-[#hex] values remaining.
- **Session stats:** 27+ commits, 6 DEVLOG entries. MCX ticker fix, option chain v2, UI overhaul, onboarding, navigation, lint fixes.
- **Beta sprint:** 24/24 tasks complete + 3 additional (Glide, 8 indicators, Rust). Task 10 (beta tag) awaiting user verification.

---

## Phase Status

- [x] Phase 1: Foundation Setup (TS 5.9, Dockview 5.1, shadcn/ui, all deps)
- [x] Phase 2: State Architecture (Zustand stores, Jotai atoms, TanStack Query hooks, API service, WebSocket service)
- [x] Phase 3: Shell + Layout (App.tsx, chrome components, widgetFactory, 7 presets)
- [x] Phase 4: Widget Migration (14 widgets + 7 tools + Chart + useWebSocket → TSX/TS)
- [x] Phase 5: Verification (tsc clean, build clean, 26/26 tests, spec review fixes applied)
- [x] Phase 6: New Widgets + Absorption (7 new widgets — SectorMap, Calculator, MTMMonitor, RiskPanel, News, Ticker, AIAdvisor)
- [x] Phase 7: Tools Build-Out (6 stub tools → functional — TradeJournal, PnLDashboard, StrategyBuilder, BacktestLab, MarketIntelligence, FlowBuilder)
- [x] Phase 8: Routes (/setup wizard with Quick/Guided/Advanced, /invest with holdings+SIP, /learn placeholder)
- [x] Phase 9: Python Upgrades (indicators package — 13 indicators, 42 tests; EMASuperTrendDEMA strategy)
- [ ] Phase 10: Testing + Beta Release (966 tests green, Glide DataGrid + indicators wired + Rust tick-engine — tag v0.1.0-beta pending user verification)

---

## Week 1-2: Foundation Sprint (Days 1-14) — from spec Section 12

### Days 1-3: Foundation Setup
- [x] Install all new deps (typescript, dockview, shadcn/ui, zustand, jotai, @tanstack/react-query, @tanstack/react-table, @glideapps/glide-data-grid, react-hook-form, zod, date-fns)
- [x] Remove old deps (flexlayout-react, recharts, autoprefixer, postcss)
- [x] Configure tsconfig.json (strict mode), shadcn/ui init, Dockview dark theme CSS
- [x] Delete packages/dashboard/ and packages/backtest/
- [x] Commit package-lock.json (remove from .gitignore)
- [x] Fix .env.example (4 blank vars only — root has 4, terminal has 3 VITE_ vars)
- [x] Verify React 19 + Dockview v5 compatibility

### Days 4-6: State Architecture
- [x] Create Zustand stores (connection, layout, settings, trading)
- [x] Create Jotai atoms (per-instrument LTP, quote, depth)
- [x] Wire TanStack Query hooks (usePositions, useOrders, useHoldings, useFunds, useOptionChain, useTradebook)
- [x] Migrate WebSocket service to TypeScript, add ping/pong heartbeat
- [x] Migrate API service to TypeScript, fix 3 critical bugs (ping GET, closePosition, optionchain expiry)
- [x] Remove DataBus, dataBus.js, useDataBus.js — replaced by Zustand/Jotai/TanStack

### Days 7-8: Shell + Layout Migration
- [x] Rewrite App.tsx with Dockview (replace FlexLayout)
- [x] Rewrite all chrome/ components (TopBar, TickerBar, WidgetPicker, ToolsDropdown) in TSX + shadcn/ui
- [x] Convert 7 layout presets from FlexLayout JSON to Dockview serialization format
- [x] Rewrite layoutStore.ts for Dockview API

### Days 9-12: Widget Migration (TypeScript + shadcn/ui) — COMPLETE
- [x] Batch 1 — Trading widgets (7 files JSX→TSX):
  - [x] DashboardWidget.jsx → DashboardWidget.tsx
  - [x] ScalperWidget.jsx → ScalperWidget.tsx
  - [x] PositionsWidget.jsx → PositionsWidget.tsx
  - [x] OrdersWidget.jsx → OrdersWidget.tsx
  - [x] HoldingsWidget.jsx → HoldingsWidget.tsx
  - [x] TradeBookWidget.jsx → TradeBookWidget.tsx
  - [x] OrderPadWidget.jsx → OrderPadWidget.tsx
- [x] Batch 2 — Analysis widgets (6 files JSX→TSX):
  - [x] ChartWidget.jsx → ChartWidget.tsx
  - [x] OptionChainWidget.jsx → OptionChainWidget.tsx (wire Glide Data Grid)
  - [x] OIChartWidget.jsx → OIChartWidget.tsx
  - [x] StraddleWidget.jsx → StraddleWidget.tsx
  - [x] DepthWidget.jsx → DepthWidget.tsx
  - [x] GreeksWidget.jsx → GreeksWidget.tsx
- [x] Batch 3 — Utility widgets (1 file JSX→TSX):
  - [x] WatchlistWidget.jsx → WatchlistWidget.tsx
- [x] Batch 4 — Tools (7 files JSX→TSX):
  - [x] SettingsTool.jsx → SettingsTool.tsx
  - [x] BacktestLabTool.jsx → BacktestLabTool.tsx
  - [x] FlowBuilderTool.jsx → FlowBuilderTool.tsx
  - [x] MarketIntelligenceTool.jsx → MarketIntelligenceTool.tsx
  - [x] PnLDashboardTool.jsx → PnLDashboardTool.tsx
  - [x] StrategyBuilderTool.jsx → StrategyBuilderTool.tsx
  - [x] TradeJournalTool.jsx → TradeJournalTool.tsx
- [x] Batch 5 — Legacy JS cleanup:
  - [x] Delete components/Chart.jsx (superseded by ChartWidget)
  - [x] Delete hooks/useWebSocket.js (superseded by services/websocket.ts)
- [x] Replace ALL raw HTML inputs/buttons/dialogs with shadcn/ui components across all widgets
- [x] Ensure every widget uses TanStack Query hooks (not raw fetch) for REST data
- [x] Ensure every widget uses Jotai atoms (not direct WS) for real-time data

### Days 13-14: Verification + Doc Cleanup
- [x] `tsc --noEmit` passes (zero type errors)
- [x] `npm run build` passes (zero warnings)
- [x] `npx vitest run` — all tests pass
- [x] All 14 widgets render in Dockview panels
- [x] Visual test with Playwright — 7 screenshots captured (beta-sprint-01 through 07) — screenshot every widget
- [x] Documentation cleanup (see Documentation section below)

### Week 1-2 Exit Criteria
- [x] TypeScript strict mode, zero `any` types
- [x] Dockview panels for all 14 widgets
- [x] shadcn/ui components everywhere (no raw HTML controls)
- [x] Zustand + Jotai + TanStack Query wired and working in every widget
- [x] All documentation contradictions resolved
- [x] Live OpenAlgo sandbox test during market hours

---

## Week 3: Widget Absorption + New Widgets — from spec Section 13

### New Widgets (7 planned)
- [x] SectorMap widget — absorb from openalgo-chart SectorHeatmapModal (treemap heatmap)
- [x] Calculator widget — absorb from openalgo-chart RiskCalculatorPanel (brokerage, margin, P&L)
  - [x] Use April 2026 STT rates: 0.05% futures, 0.15% options
- [x] MTM Monitor widget — absorb from algo_trading_strategies_india (portfolio MTM SL/Target)
- [x] Risk Panel widget — build new (max position, margin usage, daily limits)
- [x] News Feed widget — UI built, needs live RSS data wiring
- [x] Ticker widget — built (customizable scrolling prices)
- [x] AI Advisor widget — UI built, needs Python backend wiring

### Setup Wizard
- [x] Create /setup route (react-router-dom already installed)
- [x] Quick Setup mode (2 steps): OpenAlgo URL + API key test, persona pick
- [x] Guided Setup mode (5 steps): persona, connection, experience, trading defaults, done
- [x] Advanced Setup mode (7 steps): all of Guided + LLM config + Telegram/data/risk
- [x] All settings saved to workspace.json, changeable in Settings tool

### Widget Factory Updates
- [x] Register all 7 new widgets in widgetFactory.tsx
- [x] Add new widgets to WidgetPicker catalog
- [x] Update layout presets to include new widgets where appropriate

---

## Week 4: Tools + Investor Route — from spec Section 13

### Tool Build-Out (6 stubs → functional)
- [x] P&L Dashboard tool — calendar heatmap, trade stats (absorbed etftracker patterns)
- [x] Strategy Builder tool — multi-leg builder, payoff chart, Greeks (absorbed Algomirror patterns)
- [x] Trade Journal tool — analytics, screenshots, review (absorbed trading-journal patterns)
- [x] Flow Builder tool — visual canvas with 54 nodes, drag-drop, SVG edges, save/load, 3 templates
- [x] Market Intelligence tool — 10 dashboards: Breadth, FII/DII, Sector Rotation, Heatmap, India VIX, Global Indices, Participant OI, Delivery, Correlation, Announcements
- [x] Backtest Lab tool — config form + results view + VectorBT runner wired (port 5001)

### Investor Route (/invest)
- [x] Create /invest route with lazy-loaded module
- [x] Portfolio Tracker — live useFunds + useHoldings, allocation bar
- [x] Holdings view — TanStack Table with sort, P&L, avg cost
- [x] Net Worth Dashboard — equity + cash breakdown
- [x] Mutual Fund Explorer — SEBI categories, v0.2.0 live data
- [x] SIP Calculator — compound interest formula + split bar
- [x] Asset Quilt — CSS heatmap 7 asset classes × 6 years
- [x] Sector Rotation — sortable multi-timeframe table
- [x] Stock Screener — search + filter with PlaceholderTab (v0.2.0)
- [x] ETF Tracker — PlaceholderTab with feature bullets (v0.2.0)
- [x] IPO Tracker — PlaceholderTab with feature bullets (v0.2.0)

### /learn Route
- [x] Create /learn route with lazy-loaded module
- [x] Market Basics content — 6 articles (Stocks, F&O, MF, Index, Risk, SEBI)
- [x] Glossary (searchable) — 24 terms A–V
- [x] Strategy Library (browse 29+ strategies) — 12 strategies, 6 categories, difficulty badges
- [x] Paper Trading guide — Dhan Sandbox step-by-step guide
- [x] Video Hub (curated YouTube) — 6 curated education links

---

## Week 5: Python Upgrades + Strategies — from spec Section 13

### New Package: packages/indicators/
- [x] Create package — EMA, SMA, DEMA, Supertrend, VWAP, RSI, MACD, Stochastic, Williams %R, ATR, Bollinger Bands, Keltner Channels (pure NumPy, 42 tests)
- [x] Add Numba streaming indicators (absorbed pyindicators patterns, 31 total) (absorb pyindicators)
- [x] Wire into Chart widget for indicator overlays — 8 new indicators (Williams %R, CCI, DEMA, Hull MA, Parabolic SAR, OBV, Keltner, VWMA) + POST /api/v1/indicators/compute Python API (23 tests)

### Backtest Engine Upgrade
- [x] Integrate VectorBT for parameter sweeps and exploration — VectorBTRunner, tearsheet, optimize
- [x] Start Rust/PyO3 backtest prototype (raptorbt pattern) — tick-engine package: TickSimulator, EMA crossover built-in, Sharpe/drawdown metrics, 25/25 tests, maturin wheel installed

### Strategy Implementation
- [x] Implement EMA 20/50 + Supertrend 10/3 + DEMA 15 strategy (EMASuperTrendDEMA — static→dynamic SL, 5-candle rule, lot sizes, target at DEMA 15)
- [x] Absorb 28 strategies from AlgoTrading + openalgostratagies from AlgoTrading repo (of 59 total; rest in v0.2.0):
  - [x] Trend strategies (7 absorbed: EMA crossover, Supertrend, DEMA, Hull MA, ADX, Parabolic SAR, Breakout)
  - [x] Momentum strategies (5 absorbed: RSI, MACD, Stochastic, CCI, Momentum)
  - [x] Mean-reversion strategies (4 absorbed: Bollinger, Keltner, VWAP, Mean Reversion)
  - [x] Volatility strategies (5 absorbed: ATR, IV Rank, Straddle Buyer, Iron Condor, Wheel)
  - [x] Volume strategies (3 absorbed: OBV, CMF, Volume Breakout)
- [x] Absorb 8 strategies from openalgostratagies (included in 28 total) (KAMA, MA Crossover, MACD, Bollinger, Indian F&O)

### Ditto Package Upgrade
- [x] Absorb AlgoMirror patterns from ENHANCEMENT_BLUEPRINT.md
  - [x] WebSocket service for position mirroring — PositionWatcher daemon thread
  - [x] Multiplier-based allocation modes — AllocationMode.MULTIPLIER, get_multiplier()
  - [x] Broker cost metadata support in workspace.json — BrokerCostMetadata, cheapest_account()

---

## Week 6: Testing + Beta Release — from spec Section 13

### Testing
- [x] Aggressive live testing with Dhan Sandbox — Dashboard, Chart, Scalper, Watchlist, OptionChain verified during market hours
  - [ ] Every widget: Dashboard, Scalper, Positions, Orders, Holdings, TradeBook, OrderPad
  - [ ] Every widget: Chart, OptionChain, OIChart, Straddle, Depth, Greeks, Watchlist
  - [ ] Every new widget: SectorMap, Calculator, MTM Monitor, Risk Panel, News Feed, Ticker, AI Advisor
  - [ ] Every tool: Settings, P&L Dashboard, Strategy Builder, Trade Journal, Flow Builder, Market Intelligence, Backtest Lab
  - [ ] Every route: /terminal, /setup, /invest
- [ ] Test with Kotak Neo sandbox if available
- [ ] Fix all bugs found during testing
- [x] Performance optimization — Glide Data Grid for option chain (canvas-rendered, 100K+ updates/sec) — DataEditor replaces custom table, ATM row highlight, action cells, scrollTo ATM
- [ ] /learn route — basic content only (Market Basics, Glossary, Strategy Library browse)

### Beta Release Checklist
- [ ] All widgets render and display live data
- [ ] All tools are functional (no stubs)
- [ ] Setup wizard works end-to-end
- [ ] /invest route has Portfolio Tracker + Holdings + Net Worth
- [ ] `tsc --noEmit` — zero errors
- [ ] `npm run build` — zero warnings
- [ ] `vitest run` — all tests pass
- [ ] `make test` — 712+ Python tests pass
- [ ] Update all documentation (CLAUDE.md, README.md, CONTRIBUTING.md, packages/terminal/CLAUDE.md)
- [ ] Clean up git history
- [ ] Tag v0.1.0-beta
- [ ] Publish to GitHub

---

## Documentation Cleanup — from spec Section 15

> Tracked here. Do alongside Phase 4-5 (Week 1-2) or as separate focused session.

### Files to REWRITE completely (5)
- [x] PLAN.md — this file (rewritten)
- [x] README.md — fix: 662→696 tests, 3 React apps→1, remove TOTP, fix architecture diagram
- [x] packages/terminal/CLAUDE.md — fix: port 3001→5173, F1-F9→Dockview widgets, TradePulse→removed
- [x] docs/ARCHITECTURE.md — already correct (submodule, Dockview, Zustand/Jotai/TanStack)
- [x] docs/references/TOOLS_AND_DEPS.md — already has all new deps

### Files to UPDATE (18)
- [x] CLAUDE.md — already accurate (11 packages, correct test count, 4 .env vars)
- [x] AGENTS.md — test count updated to 944
- [x] CHANGELOG.md — test count updated to 944
- [x] CONTRIBUTING.md — test count 944, DEVLOG machine name fixed
- [x] REPOS.md (root) — identical to docs/references/REPOS.md, already in sync
- [x] docs/OPERATIONS_GUIDE.md — already clean
- [x] docs/SEBI_COMPLIANCE.md — Options STT buy side, April 2026 rates updated
- [x] docs/references/REPOS.md — already in sync with root
- [x] docs/references/OPENALGO_API.md — ping POST, WS auth format, 4 endpoint paths fixed
- [x] docs/machine-setup/QUICKSTART.md — already clean
- [x] docs/setup/linux.md — already clean
- [x] docs/setup/macos.md — already clean
- [x] docs/setup/windows.md — already clean
- [x] docs/setup/raspberry-pi.md — already clean
- [x] infra/cron/README.md — already clean (no TOTP login_job)
- [x] flint.toml — already clean
- [x] .env.example — root correct (4 blank); terminal fixed to 3 canonical VITE_ vars
- [x] .github/ISSUE_TEMPLATE/*.md — already clean

### Package READMEs to CHECK (10)
- [x] packages/core/README.md — clean
- [x] packages/engine/README.md — clean
- [x] packages/data/README.md — clean
- [x] packages/historical/README.md — clean
- [x] packages/screener/README.md — clean
- [x] packages/backtest-engine/README.md — updated (VectorBTRunner + Monte Carlo)
- [x] packages/ai/README.md — clean
- [x] packages/integration/README.md — clean
- [x] packages/automation/README.md — clean (no TOTP present)
- [x] packages/ditto/README.md — updated (AllocationMode.MULTIPLIER + BrokerCostMetadata)

### Files to ARCHIVE (move to docs/references/historical/)
- [x] RESTRUCTURE.md → docs/references/historical/RESTRUCTURE_V1.md
- [x] docs/THE_PLAN.md → docs/references/historical/THE_PLAN_V1.md
- [x] docs/references/MASTER_BLUEPRINT.md → docs/references/historical/
- [x] docs/superpowers/plans/2026-03-18-phase1-flexlayout-foundation.md → docs/references/historical/

### Files to DELETE
- [x] findings.md (temp file from planning-with-files skill)
- [x] task_plan.md (temp file from planning-with-files skill)
- [x] progress.md (temp file from planning-with-files skill)

### Files to MARK as absorbed
- [x] docs/references/ENHANCEMENT_BLUEPRINT.md — add header "Absorbed into v2 spec"

### TOTP Cleanup
- [x] Remove ALL TOTP references across 9+ non-submodule files (CLAUDE.md, AGENTS.md, CHANGELOG.md, automation/cron_manager.py, etc.)
- [ ] Do NOT touch infra/openalgo/ or infra/openclaw/ (submodules)

### CI/CD Update
- [x] Update GitHub Actions to include `tsc --noEmit` step for TypeScript

---

## Deferred Features (Post-Beta) — from spec Section 17

These are tracked, not forgotten. Every one gets built eventually.

| # | Feature | Source Repo | Target Version |
|---|---------|-------------|---------------|
| 0 | **Live Market Signals Pipeline** | packages/ai (BUILT), packages/indicators (BUILT) | **v0.2.0** |
|   | → WebSocket ticks → indicator calc → signal generation → notification/execution | | |
|   | → User-configurable: instruments, indicators, thresholds, actions (notify/alert/auto-execute) | | |
|   | → AI: 12 providers (local/cloud/both), overnight optimization + morning validation | | |
|   | → Approval workflow: AI suggests → user reviews → one-click execute | | |
|   | → Self-learning loop: results feed back into training data | | |
| 1 | Chrome Extension | openalgo-chrome | v0.2.0 |
| 2 | Excel Integration | OpenAlgo-Excel | v0.2.0 |
| 3 | WhatsApp Alerts | wabridge | v0.2.0 |
| 4 | Kotak Neo Cost Routing | — | v0.2.0 |
| 5 | Dhan Rolling Option API | — | v0.2.0 |
| 6 | Historical Expired Options | ExpiryTrack | v0.2.0 |
| 7 | CLI Tools (Click) | CLI-Anything pattern | v0.2.0 |
| 8 | DDNS Auto-update | infra scripts | v0.2.0 |
| 9 | MCX Full Support | — | v0.2.0 |
| 10 | QuestDB Tick Aggregation | openquest | v0.2.0 |
| 11 | Mutual Fund Explorer | jugaad-data | v0.2.0 |
| 12 | SIP Calculator | — | v0.2.0 |
| 13 | ETF Tracker | etftracker | v0.2.0 |
| 14 | Stock Screener | openscreener | v0.2.0 |
| 15 | IPO Tracker | — | v0.2.0 |
| 16 | /learn route (full) | — | v0.2.0 |
| 17 | OpenClaw bridge testing | — | v0.2.0 |
| 18 | Desktop App (Tauri) | fastscalper-tauri, openalgo-desktop | v0.3.0 |
| 19 | Pine Script Indicator Editor | PineTS | v0.3.0 |
| 20 | Multi-user Auth | openalgo-multiuser | v0.3.0 |
| 21 | Blue-green Deployment | — | v0.3.0 |
| 22 | Crypto (Delta Exchange) | ccxt | v0.3.0 |
| 23 | Voice Orders | openalgo-voice-based-orders | v0.3.0 |
| 24 | Mobile App | openalgo-mobile | v0.4.0 |
| 25 | FinRL Reinforcement Learning | FinRL | v0.4.0 |
| 26 | Multi-agent AI (TradingAgents) | TradingAgents | v0.4.0 |
| 27 | Unsloth QLoRA Fine-tuning | — | v0.5.0 |

---

## Previously Completed (pre-v2 migration)

- [x] Monorepo structure (11 Python + 1 React packages)
- [x] All 11 Python packages: source code + tests (738 passing)
- [x] Terminal: professional dark theme, live OpenAlgo API
- [x] Core: OpenAlgo client with 45+ endpoint wrappers
- [x] Core: Workspace config system (~/.flinttrade/workspace.json)
- [x] Core: FlintTradeConfig (two-tier: .env + workspace.json)
- [x] Engine: 5-layer safety system, order router, scheduler, strategy registry
- [x] Engine: EMACrossover strategy, per-exchange market hours
- [x] Data: SEBI audit logger (JSONL append-only), DuckDB storage, tick recorder
- [x] Historical: downloader, free NSE data, DuckDB pipeline, expiry manager
- [x] Screener: option chain, OI analysis, futures quadrant, Greeks, IV
- [x] Backtest-engine: event-driven simulator, 12 templates, optimizer, metrics
- [x] AI: LLM client, RAG pipeline, ML signals, news sentiment
- [x] Integration: TradingView webhooks, ChartInk, flow builder, alerter
- [x] Automation: cron scheduler, Telegram bot, OpenClaw bridge, post-market
- [x] Ditto: account manager, position mirroring, margin calc, trailing SL
- [x] Infrastructure: Makefile, setup.sh, systemd templates, health-check.sh
- [x] Git submodules: openalgo, algomirror, openclaw
- [x] First sandbox trade placed successfully
- [x] CI: GitHub Actions (python-tests, node-tests, secrets-check, claude-review)
- [x] .env.example: 4 blank vars only (root), 3 VITE_ vars (terminal)
- [x] package-lock.json tracked in git
- [x] Stub packages deleted (dashboard/, backtest/)

---

## Known OpenAlgo Bugs (work around these)

1. **Sandbox sends real orders** — verify isolation before testing
2. **closeposition ignores strategy** — track positions per-strategy ourselves
3. **WebSocket drops without heartbeat** — implemented ping/pong in our client
4. **PNL calculation incorrect for some brokers** — calculate ourselves
5. **MCX symbol format inconsistency** — normalize in our symbol resolver
6. **SQLite concurrent access** — never touch OpenAlgo's DB directly

---

## Quick Reference

| What | Where |
|------|-------|
| Approved spec | `docs/superpowers/specs/2026-03-19-flinttrade-v2-foundation-design.md` |
| Project rules | `CLAUDE.md` |
| Repo feature map | `docs/REPO_FEATURE_MAP.md` |
| Best-in-class verdicts | `docs/BEST_IN_CLASS_2026.md` |
| Enhancement patterns | `docs/references/ENHANCEMENT_BLUEPRINT.md` |
| All 222 repos | `docs/references/REPOS.md` |

---

*This plan supersedes the previous PLAN.md, RESTRUCTURE.md, and all prior roadmap documents.*
*Aligned with approved spec dated 2026-03-19.*

# FlintTrade — Development Roadmap

> Single source of truth for what to build next.
> Every Claude Code session reads this + CLAUDE.md + SOP.md before starting.
> Approved spec: `docs/superpowers/specs/2026-03-19-flinttrade-v2-foundation-design.md`
> Deadline: **April 30, 2026 (v0.1.0-beta)**

---

## Current State (updated 2026-03-19)

- **Version:** 0.1.0-alpha
- **Tests:** 26 terminal (Vitest) + 712 Python (pytest) = 738 total
- **Terminal:** 21 widgets (TSX) + 7 tools (all functional) + 4 routes in Dockview v5 shell
- **TypeScript migration:** Complete. Zero JSX/JS files. ~90 TS/TSX files.
- **Python:** 12 packages (10 original + indicators + strategies sub-package), 712 tests passing
- **CI:** GitHub Actions green (python-tests + node-tests + secrets-check)
- **Packages:** 11 Python + 1 React (terminal). Stub packages `dashboard/` and `backtest/` deleted.
- **Dependencies:** All v2 deps installed (Dockview 5.1, Zustand 5, Jotai, TanStack Query 5, Glide Data Grid 6, shadcn/ui, react-hook-form, zod). Old deps removed (FlexLayout, recharts, postcss).
- **State:** Zustand stores (4), Jotai atoms, TanStack Query hooks (6), WebSocket service with ping/pong — all wired.
- **Shell:** Dockview canvas, TopBar, TickerBar, WidgetPicker, ToolsDropdown — all TSX + shadcn/ui. 7 layout presets.

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
- [ ] Phase 10: Testing + Beta Release (live testing, performance, tag v0.1.0-beta)

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
- [ ] Visual test with Playwright — screenshot every widget
- [ ] Documentation cleanup (see Documentation section below)

### Week 1-2 Exit Criteria
- [x] TypeScript strict mode, zero `any` types
- [x] Dockview panels for all 14 widgets
- [x] shadcn/ui components everywhere (no raw HTML controls)
- [x] Zustand + Jotai + TanStack Query wired and working in every widget
- [ ] All documentation contradictions resolved
- [ ] Live OpenAlgo sandbox test during market hours

---

## Week 3: Widget Absorption + New Widgets — from spec Section 13

### New Widgets (7 planned)
- [ ] SectorMap widget — absorb from openalgo-chart SectorHeatmapModal (treemap heatmap)
- [ ] Calculator widget — absorb from openalgo-chart RiskCalculatorPanel (brokerage, margin, P&L)
  - [ ] Use April 2026 STT rates: 0.05% futures, 0.15% options
- [ ] MTM Monitor widget — absorb from algo_trading_strategies_india (portfolio MTM SL/Target)
- [ ] Risk Panel widget — build new (max position, margin usage, daily limits)
- [ ] News Feed widget — absorb from finnews-ai (sentiment-tagged financial news)
- [ ] Ticker widget — build new (customizable scrolling prices)
- [ ] AI Advisor widget — absorb from openalgo-chatbot + openalgo-voice (LLM chat, voice input)

### Setup Wizard
- [ ] Create /setup route (react-router-dom already installed)
- [ ] Quick Setup mode (2 steps): OpenAlgo URL + API key test, persona pick
- [ ] Guided Setup mode (5 steps): persona, connection, experience, trading defaults, done
- [ ] Advanced Setup mode (7 steps): all of Guided + LLM config + Telegram/data/risk
- [ ] All settings saved to workspace.json, changeable in Settings tool

### Widget Factory Updates
- [ ] Register all 7 new widgets in widgetFactory.tsx
- [ ] Add new widgets to WidgetPicker catalog
- [ ] Update layout presets to include new widgets where appropriate

---

## Week 4: Tools + Investor Route — from spec Section 13

### Tool Build-Out (6 stubs → functional)
- [ ] P&L Dashboard tool — calendar heatmap, trade stats (absorb etftracker patterns)
- [ ] Strategy Builder tool — multi-leg builder, payoff chart, Greeks (absorb Algomirror patterns)
- [ ] Trade Journal tool — analytics, screenshots, review (absorb trading-journal patterns)
- [ ] Flow Builder tool — visual automation (absorb openalgo-flow, 54 node types)
- [ ] Market Intelligence tool — FII/DII, sector rotation, RRG (absorb etftracker dashboards)
- [ ] Backtest Lab tool — parameter config, equity curve, trade log (connect to backtest-engine)

### Investor Route (/invest)
- [ ] Create /invest route with lazy-loaded module
- [ ] Portfolio Tracker — absorb virfolio patterns
- [ ] Holdings view — reuse terminal Holdings widget adapted for investor context
- [ ] Net Worth Dashboard — build from scratch

### Investor Route — Deferred to v0.2.0
The following are designed but not needed for beta:
- Mutual Fund Explorer (jugaad-data MF NAV API)
- SIP Calculator
- Asset Quilt (etftracker)
- Sector Rotation (etftracker + sector-rotation-map)
- Stock Screener (openscreener + screener-scraper)
- ETF Tracker (etftracker)
- IPO Tracker

### /learn Route — Deferred to v0.2.0
Not needed for beta. Basic content only if time permits in Week 6.

---

## Week 5: Python Upgrades + Strategies — from spec Section 13

### New Package: packages/indicators/
- [x] Create package — EMA, SMA, DEMA, Supertrend, VWAP, RSI, MACD, Stochastic, Williams %R, ATR, Bollinger Bands, Keltner Channels (pure NumPy, 42 tests)
- [ ] Add Numba streaming indicators (absorb pyindicators)
- [ ] Wire into Chart widget for indicator overlays

### Backtest Engine Upgrade
- [ ] Integrate VectorBT for parameter sweeps and exploration
- [ ] Start Rust/PyO3 backtest prototype (raptorbt pattern) — proof of concept only

### Strategy Implementation
- [x] Implement EMA 20/50 + Supertrend 10/3 + DEMA 15 strategy (EMASuperTrendDEMA — static→dynamic SL, 5-candle rule, lot sizes, target at DEMA 15)
- [ ] Absorb 20 highest-priority strategies from AlgoTrading repo (of 59 total; rest in v0.2.0):
  - [ ] Trend strategies (top 5 of 15)
  - [ ] Momentum strategies (top 4 of 11)
  - [ ] Mean-reversion strategies (top 4 of 10)
  - [ ] Volatility strategies (top 4 of 10)
  - [ ] Volume strategies (top 3 of 10)
- [ ] Absorb 8 strategies from openalgostratagies (KAMA, MA Crossover, MACD, Bollinger, Indian F&O)

### Ditto Package Upgrade
- [ ] Absorb AlgoMirror patterns from ENHANCEMENT_BLUEPRINT.md
  - [ ] WebSocket service for position mirroring
  - [ ] Multiplier-based allocation modes
  - [ ] Broker cost metadata support in workspace.json (for future Kotak Neo cost routing)

---

## Week 6: Testing + Beta Release — from spec Section 13

### Testing
- [ ] Aggressive live testing with broker sandbox during market hours
  - [ ] Every widget: Dashboard, Scalper, Positions, Orders, Holdings, TradeBook, OrderPad
  - [ ] Every widget: Chart, OptionChain, OIChart, Straddle, Depth, Greeks, Watchlist
  - [ ] Every new widget: SectorMap, Calculator, MTM Monitor, Risk Panel, News Feed, Ticker, AI Advisor
  - [ ] Every tool: Settings, P&L Dashboard, Strategy Builder, Trade Journal, Flow Builder, Market Intelligence, Backtest Lab
  - [ ] Every route: /terminal, /setup, /invest
- [ ] Test with Kotak Neo sandbox if available
- [ ] Fix all bugs found during testing
- [ ] Performance optimization — Glide Data Grid for option chain (canvas-rendered, 100K+ updates/sec)
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
- [ ] README.md — fix: 662→696 tests, 3 React apps→1, remove TOTP, fix architecture diagram
- [ ] packages/terminal/CLAUDE.md — fix: port 3001→5173, F1-F9→Dockview widgets, TradePulse→removed
- [ ] docs/ARCHITECTURE.md — fix: subtree→submodule, FlexLayout→Dockview, DataBus→Zustand/Jotai/TanStack
- [ ] docs/references/TOOLS_AND_DEPS.md — add: dockview, shadcn, zustand, jotai, tanstack, glide-data-grid

### Files to UPDATE (18)
- [ ] CLAUDE.md — fix: widget arch, 11 packages not 13, test count, 4 .env vars
- [ ] AGENTS.md — remove F-key/TOTP references
- [ ] CHANGELOG.md — remove TOTP claims
- [ ] CONTRIBUTING.md — test count 662→696, canonical DEVLOG format
- [ ] REPOS.md (root) — sync with docs/references/REPOS.md
- [ ] docs/OPERATIONS_GUIDE.md — check for stale references
- [ ] docs/SEBI_COMPLIANCE.md — remove TOTP cron ref, add April 2026 STT rates
- [ ] docs/references/REPOS.md — sync with root REPOS.md
- [ ] docs/references/OPENALGO_API.md — check for accuracy
- [ ] docs/machine-setup/QUICKSTART.md — remove F1-F8, update for Dockview/TS
- [ ] docs/setup/linux.md — remove old module references
- [ ] docs/setup/macos.md — remove old module references
- [ ] docs/setup/windows.md — fix port 3000 reference
- [ ] docs/setup/raspberry-pi.md — remove old module references
- [ ] infra/cron/README.md — remove TOTP login_job reference
- [ ] flint.toml — remove TOTP from automation description
- [ ] .env.example — verify 4 blank vars only (root: done, terminal: has 3 VITE_ vars)
- [ ] .github/ISSUE_TEMPLATE/*.md — check templates are current

### Package READMEs to CHECK (10)
- [ ] packages/core/README.md — check for TOTP references
- [ ] packages/engine/README.md — check for stale module references
- [ ] packages/data/README.md — check accuracy
- [ ] packages/historical/README.md — check accuracy
- [ ] packages/screener/README.md — check accuracy
- [ ] packages/backtest-engine/README.md — check accuracy
- [ ] packages/ai/README.md — check accuracy
- [ ] packages/integration/README.md — check accuracy
- [ ] packages/automation/README.md — check for TOTP reference (known)
- [ ] packages/ditto/README.md — check accuracy

### Files to ARCHIVE (move to docs/references/historical/)
- [x] RESTRUCTURE.md → docs/references/historical/RESTRUCTURE_V1.md
- [x] docs/THE_PLAN.md → docs/references/historical/THE_PLAN_V1.md
- [x] docs/references/MASTER_BLUEPRINT.md → docs/references/historical/
- [ ] docs/superpowers/plans/2026-03-18-phase1-flexlayout-foundation.md → docs/references/historical/

### Files to DELETE
- [ ] findings.md (temp file from planning-with-files skill)
- [ ] task_plan.md (temp file from planning-with-files skill)
- [ ] progress.md (temp file from planning-with-files skill)

### Files to MARK as absorbed
- [ ] docs/references/ENHANCEMENT_BLUEPRINT.md — add header "Absorbed into v2 spec"

### TOTP Cleanup
- [ ] Remove ALL TOTP references across 9+ non-submodule files (CLAUDE.md, AGENTS.md, CHANGELOG.md, automation/cron_manager.py, etc.)
- [ ] Do NOT touch infra/openalgo/ or infra/openclaw/ (submodules)

### CI/CD Update
- [ ] Update GitHub Actions to include `tsc --noEmit` step for TypeScript

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

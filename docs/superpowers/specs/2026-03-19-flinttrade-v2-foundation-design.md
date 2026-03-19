# FlintTrade v2 Foundation — Design Spec

> **Date:** 2026-03-19
> **Status:** APPROVED by user
> **Scope:** Complete tech stack migration + architecture rebuild
> **Deadline:** April 30, 2026 (beta)

---

## 1. Vision

FlintTrade is an open-source, institutional-grade trading and investment platform built on OpenAlgo (30+ Indian brokers). It serves three personas from a single application:

- **Trader** — Intraday F&O scalping, options analysis, real-time execution
- **Investor** — Mutual funds, SIPs, portfolio tracking, net worth
- **Beginner** — Guided learning, paper trading, market education

One app. One port. Route-based separation. Widget-composable workspace.

---

## 2. Tech Stack (Locked)

### Frontend
| Category | Choice | Version | Why |
|----------|--------|---------|-----|
| Language | TypeScript | 5.x | Type safety for financial app, every reference repo uses it |
| Framework | React | 19 | Auto-memoization compiler, best for real-time UIs |
| Build | Vite | 6.4+ | Fastest DX, upgrade to 8/Rolldown when stable |
| CSS | Tailwind CSS | v4 | @tailwindcss/vite plugin, zero runtime |
| Components | shadcn/ui | latest | Radix accessibility, copy-paste ownership, Tailwind-native |
| Layout/Docking | Dockview | v5 | Floating, popout, tabs, serialize, zero deps |
| Charting | Lightweight Charts | v5 | 35KB, Apache 2.0, multi-pane, plugins |
| Data Grid | Glide Data Grid | latest | Canvas-rendered, 100K+ updates/sec for option chain |
| Data Grid (static) | TanStack Table | v8 | Headless, sortable, filterable for positions/orders |
| State (global) | Zustand | v5 | 1KB, selectors, middleware, devtools |
| State (market data) | Jotai | latest | Per-instrument atoms, derived atoms for calculations |
| State (REST cache) | TanStack Query | v5 | Auto-cache, refetch, loading/error states |
| Forms | react-hook-form + zod | latest | Validation, type-safe, performant |
| Icons | lucide-react | latest | Tree-shakable, shadcn/ui default |
| Dates | date-fns | latest | IST formatting, lightweight |

### Backend (Python)
| Category | Choice | Why |
|----------|--------|-----|
| Runtime | Python 3.12 | Stable, OpenAlgo ecosystem |
| Indicators | TA-Lib (batch) + Numba (streaming) | pandas-ta archiving July 2026 |
| Backtesting | VectorBT (exploration) + Rust/PyO3 (tick-level) | Speed for options |
| Data | DuckDB (analytics) + QuestDB (ticks, future) | Columnar + time-series |
| AI/ML | LM Studio + ChromaDB + FinRL (future) | Local-first AI |

### Infrastructure
| Category | Choice |
|----------|--------|
| Broker Gateway | OpenAlgo v2.0.0.1 (git submodule) |
| Real-time | WebSocket port 8765 (LTP/Quote/Depth modes) |
| Config | Bootstrap `.env` (3 vars) + in-app Settings (workspace.json) |
| Deployment | systemd (Ubuntu), local dev (Nitro/Mac) |

---

## 3. Application Routes

```
localhost:5173/
├── /setup          → First-time wizard (Quick / Guided / Advanced)
├── /terminal       → Trader workspace (Dockview canvas)
├── /invest         → Investor dashboard
├── /learn          → Beginner center
└── /settings       → Full settings (also accessible as tool overlay)
```

All routes share: design system, API layer, auth state, WebSocket connection.
Each route lazy-loads its own module. No cross-route code in the initial bundle.

---

## 4. First-Time Setup Wizard

Three modes presented as cards on `/setup`:

**Quick Setup (2 steps)**
1. OpenAlgo URL + API key → test connection
2. Pick persona → land in app

**Guided Setup (5 steps)**
1. Welcome + persona pick (Trader/Investor/Learner)
2. OpenAlgo connection + test
3. Experience level → default layout
4. Trading defaults (exchange, product, qty)
5. Done → personalized workspace

**Advanced Setup (7 steps)**
1. All of Guided, plus:
6. LLM config (provider, model, host)
7. Telegram, data paths, risk limits

All settings saved to `workspace.json`. Changeable anytime in Settings.

---

## 5. Terminal Architecture (Trader Route)

### Shell (always visible)
```
┌─────────────────────────────────────────────────────────────┐
│ FT │ [Layout Tabs] [+] │ P&L: +₹X │ TOOLS WIDGETS │ 🟢 IST │  ← TopBar
├─────────────────────────────────────────────────────────────┤
│ NIFTY 23,581 ▲0.74% │ SENSEX 76,070 ▲0.75% │ BANKNIFTY...│  ← TickerBar
├─────────────────────────────────────────────────────────────┤
│                                                             │
│              Dockview Canvas                                │
│              (user-composable workspace)                    │
│                                                             │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐                  │
│   │  Chart   │ │ Option   │ │ Watchlist │  ← Dockable      │
│   │          │ │ Chain    │ │          │     panels         │
│   └──────────┘ └──────────┘ └──────────┘                  │
│   ┌──────────────────┐ ┌──────────────┐                    │
│   │   Positions      │ │   Orders     │                    │
│   └──────────────────┘ └──────────────┘                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Widgets (20+ available from picker)

**Trading (8):**
| Widget | Source | Type |
|--------|--------|------|
| Scalper | Built (adapt to TS) | 3-panel CE/Spot/PE + order buttons |
| Order Pad | Built (adapt to TS) | Full order entry form |
| Positions | Built (adapt to TS) | Live positions + P&L |
| Orders | Built (adapt to TS) | Order book |
| Holdings | Built (adapt to TS) | Delivery holdings |
| Trade Book | Built (adapt to TS) | Trade history |
| MTM Monitor | NEW (from algo_trading_strategies_india) | Portfolio MTM SL/Target |
| Risk Panel | NEW (build) | Max position, margin usage, daily limits |

**Analysis (9):**
| Widget | Source | Type |
|--------|--------|------|
| Chart | Built (adapt to TS) | LWC v5, indicators, drawing tools |
| Option Chain | Built (adapt to TS) | Full chain, OI/LTP/Greeks, Glide Data Grid |
| OI Chart | Built (adapt to TS) | Horizontal OI bars, PCR, S/R |
| Straddle | Built (adapt to TS) | ATM tracking, overlays |
| Depth | Built (adapt to TS) | 5-level bid/ask |
| Greeks | Built (adapt to TS, register in factory) | Portfolio Delta/Gamma/Theta/Vega |
| Sector Map | NEW (from openalgo-chart SectorHeatmapModal) | Treemap heatmap |
| News Feed | NEW (from finnews-ai) | Sentiment-tagged financial news |
| Calculator | NEW (from openalgo-chart RiskCalculatorPanel) | Brokerage, margin, P&L |

**Utility (4):**
| Widget | Source | Type |
|--------|--------|------|
| Watchlist | Built (adapt to TS) | Live quotes, sparklines, search |
| Dashboard | Built (adapt to TS) | Account overview, indices, P&L |
| Ticker | NEW (build) | Customizable scrolling prices |
| AI Advisor | NEW (from openalgo-chatbot + voice) | LLM chat, voice input |

### Tools (7 full-page views)
| Tool | Source | Status |
|------|--------|--------|
| P&L Dashboard | NEW (absorb etftracker patterns) | Calendar heatmap, trade stats |
| Strategy Builder | NEW (absorb Algomirror patterns) | Multi-leg, payoff chart, Greeks |
| Flow Builder | ABSORB openalgo-flow | 54 node types, visual automation |
| Market Intelligence | NEW (absorb etftracker dashboards) | FII/DII, sector rotation, RRG |
| Backtest Lab | UPGRADE (add VectorBT + Jupyter) | Tick-level options backtesting |
| Trade Journal | ABSORB trading-journal patterns | Analytics, screenshots, review |
| Settings | Built (adapt to TS) | In-app config, restart button |

### Layout Presets (6)
| Preset | Description |
|--------|-------------|
| Start Fresh | Empty canvas |
| Scalper Zone | 3-panel chart + order pad + positions |
| Volatility Trading | Straddle + OI Chart + Option Chain + Positions |
| Market Watch | Chart + Watchlist + News + Sector Map |
| Options Desk | Option Chain + Greeks + OI Chart + Calculator |
| Investor View | Dashboard + Holdings + Watchlist |

---

## 6. State Architecture

```
┌─────────────────────────────────────────┐
│              WebSocket                   │
│         (port 8765, LTP/Quote/Depth)    │
└──────────────┬──────────────────────────┘
               │ ticks
               ▼
┌─────────────────────────────────────────┐
│           Jotai Atoms                    │
│  niftyAtom, bankniftyAtom, sensexAtom   │
│  Per-instrument: ltp, change, volume    │
│  Derived: pcr, straddle price, greeks   │
└──────────────┬──────────────────────────┘
               │ reads
               ▼
┌─────────────────────────────────────────┐
│          Zustand Stores                  │
│  connectionStore: host, apiKey, status  │
│  layoutStore: active layout, presets    │
│  settingsStore: workspace.json mirror   │
│  tradingStore: positions, orders, P&L   │
└──────────────┬──────────────────────────┘
               │ API calls
               ▼
┌─────────────────────────────────────────┐
│        TanStack Query                    │
│  usePositions(), useOrders()            │
│  useHoldings(), useFunds()              │
│  useOptionChain(symbol, expiry)         │
│  Auto-refetch, stale-while-revalidate  │
└─────────────────────────────────────────┘
```

Rate limiting built into the query layer:
- Orders: 10 req/s
- Smart orders: 2 req/s
- General API: 50 req/s

---

## 7. Code Absorption Plan

### Direct Absorption (fork + adapt to TS/shadcn/Dockview)
| Repo | What | Target |
|------|------|--------|
| openalgo-flow | Complete flow builder (React Flow + 54 nodes) | Flow Builder tool |
| openalgo-chart | SectorHeatmapModal, RiskCalculatorPanel, AlertsPanel | Sector Map, Calculator, Alerts widgets |
| trading-journal | Trade journal with analytics | Trade Journal tool |
| pyindicators | 100+ Numba indicators | packages/indicators/ |
| trading-strategies-openalgo | Backtest engine + grid strategies | packages/backtest-engine/ upgrade |
| etftracker | 10 React dashboards | /invest route + Market Intelligence tool |
| openalgo-portfoliogreeks | Greeks calculator | Greeks widget enhancement |
| option-chain | Real-time chain + PCR | Option Chain widget reference |

### Strategy Absorption (59+ strategies)
| Source | Count | Categories |
|--------|-------|-----------|
| AlgoTrading repo | 59 | Trend(15), Momentum(11), Mean-reversion(10), Volatility(10), Volume(10), Pattern(3) |
| openalgostratagies | 8 | KAMA, MA Crossover, MACD, Bollinger, Indian F&O specific |
| User's personal | 1 | EMA 20/50 + Supertrend 10/3 + DEMA 15 (specific SL/target logic) |
| Total | 68 | |

### Python Library Integration
| Library | Purpose | Package |
|---------|---------|---------|
| TA-Lib | 150+ indicators (batch, C speed) | packages/indicators/ |
| VectorBT | Backtesting + parameter sweeps | packages/backtest-engine/ |
| py_vollib | Black-Scholes, Greeks | packages/screener/ |
| jugaad-data | NSE equity + mutual fund NAV | packages/historical/ |
| ccxt | Crypto exchange data (Delta Exchange) | packages/data/ |
| PineTS | Pine Script → JS indicator conversion | packages/indicators/ |

---

## 8. Investor Route (/invest)

Absorbed from etftracker + virfolio + jugaad-data:

| Feature | Source |
|---------|--------|
| Portfolio Tracker | virfolio patterns |
| Mutual Fund Explorer | jugaad-data MF NAV API |
| SIP Calculator | Build from scratch (math only) |
| Asset Quilt | etftracker |
| Sector Rotation | etftracker + sector-rotation-map |
| Stock Screener | openscreener + screener-scraper |
| ETF Tracker | etftracker |
| IPO Tracker | Build from scratch |
| Net Worth Dashboard | Build from scratch |

---

## 9. Beginner Route (/learn)

| Feature | Description |
|---------|-------------|
| Market Basics | What are stocks, F&O, mutual funds |
| Paper Trading | Sandbox mode with guided tutorial |
| Strategy Library | Browse 68 strategies with explanations |
| Glossary | Trading terms dictionary |
| Video Hub | Curated YouTube content |

---

## 10. Configuration Architecture

### Bootstrap (.env — 4 vars, matching CLAUDE.md locked decision)
```
OPENALGO_HOST=
OPENALGO_PORT=
OPENALGO_API_KEY=
OPENALGO_WS_PORT=
```
All other configuration is in-app via Settings → saved to workspace.json.
Broker vars, LLM, Telegram, WIREGUARD, DDNS, MACHINE vars all move to workspace.json.
The 31-var .env is replaced by these 4 + workspace.json.

### Runtime (workspace.json — everything else, configured in-app)
```json
{
  "connection": { "host": "...", "port": 5000, "apiKey": "...", "wsPort": 8765 },
  "persona": "trader",
  "trading": { "defaultExchange": "NFO", "defaultProduct": "MIS", "defaultQty": 1 },
  "risk": { "maxPositionLots": 10, "mtmStoploss": 5000, "mtmTarget": 10000, "maxOrdersPerMin": 30 },
  "ui": { "theme": "dark", "density": "compact", "activeLayout": "scalper-zone" },
  "llm": { "provider": "lmstudio", "host": "http://127.0.0.1:1234", "model": "qwen-3.5-9b" },
  "telegram": { "token": "", "chatId": "", "enabled": false },
  "data": { "fastPath": "~/data/fast", "archivePath": "~/data/archive" },
  "sebi": { "maxOps": 10, "auditRetentionYears": 5 }
}
```

Settings tool has a **Restart Services** button that:
1. Saves workspace.json
2. Reconnects WebSocket
3. Re-initializes API client with new host/key
4. Refreshes all TanStack Query caches

---

## 11. SOP (Standard Operating Procedure)

Every Claude Code session follows this workflow:

```
READ → PLAN → APPROVE → BUILD → VERIFY → TEST → FIX → UPDATE → COMMIT
```

### Enforced by hooks:
- **PostToolUse (Write|Edit):** Auto build check on TS/React files
- **Stop:** Remind to run tests and check SOP
- **PreToolUse (Bash):** Block destructive commands

### Rules:
1. Read MEMORY.md + CLAUDE.md + PLAN.md before any work
2. Check REPO_FEATURE_MAP.md before writing any new code — absorb first
3. Get user approval for non-trivial changes
4. Use context7 MCP before guessing library APIs
5. Use Playwright for visual verification of UI changes
6. TypeScript strict mode — no `any` types
7. shadcn/ui components — no raw HTML buttons/inputs/dialogs
8. Every widget is a Dockview panel — no fixed layouts
9. Test with live OpenAlgo sandbox before claiming done
10. Conventional commits, specific file staging, never `git add -A`

---

## 12. Migration Plan (Weeks 1-2: Foundation Sprint)

> Reviewer note: Original 7-day timeline was unrealistic. Extended to 14 days.
> FlexLayout→Dockview migration, DataBus→Zustand/Jotai/TanStack, JS→TS for 49 files,
> plus Glide Data Grid for option chain = realistically 10-14 days.

### Days 1-3: Foundation Setup
- [ ] Install all new deps (typescript, dockview, shadcn/ui, zustand, jotai, @tanstack/react-query, @tanstack/react-table, @glideapps/glide-data-grid, react-hook-form, zod, date-fns)
- [ ] Remove old deps (flexlayout-react, recharts, autoprefixer, postcss)
- [ ] Configure tsconfig.json (strict mode), shadcn/ui init, Dockview dark theme CSS
- [ ] Delete packages/dashboard/ and packages/backtest/
- [ ] Commit package-lock.json (remove from .gitignore)
- [ ] Fix .env.example (4 blank vars only)
- [ ] Verify React 19 + Dockview v5 compatibility

### Days 4-6: State Architecture
- [ ] Create Zustand stores (connection, layout, settings, trading)
- [ ] Create Jotai atoms (per-instrument LTP, quote, depth)
- [ ] Wire TanStack Query hooks (usePositions, useOrders, useHoldings, useFunds, useOptionChain)
- [ ] Migrate WebSocket service to TypeScript, add ping/pong heartbeat
- [ ] Migrate API service to TypeScript, fix 3 critical bugs (ping GET, closePosition, optionchain expiry)
- [ ] Remove DataBus, dataBus.js, useDataBus.js — replaced by above

### Days 7-8: Shell + Layout Migration
- [ ] Rewrite App.tsx with Dockview (replace FlexLayout)
- [ ] Rewrite all chrome/ components (TopBar, TickerBar, WidgetPicker, ToolsDropdown) in TSX + shadcn/ui
- [ ] Convert 7 layout presets from FlexLayout JSON to Dockview serialization format
- [ ] Rewrite layoutStore.ts for Dockview API

### Days 9-12: Widget Migration (TypeScript + shadcn/ui)
- [ ] Batch 1 (Trading): Scalper, OrderPad, Positions, Orders, Holdings, TradeBook (6 widgets)
- [ ] Batch 2 (Analysis): Chart, OptionChain (Glide Data Grid), OIChart, Straddle, Depth, Greeks (6 widgets)
- [ ] Batch 3 (Utility + remaining): Dashboard, Watchlist (2 widgets)
- [ ] Register GreeksWidget in factory
- [ ] All raw HTML inputs/buttons/dialogs → shadcn/ui components

### Days 13-14: Verification + Doc Cleanup
- [ ] `tsc --noEmit` passes (zero type errors)
- [ ] `npm run build` passes (zero warnings)
- [ ] `npx vitest run` all tests pass
- [ ] All 14 widgets render in Dockview panels
- [ ] Visual test with Playwright — screenshot every widget
- [ ] Rewrite PLAN.md, packages/terminal/CLAUDE.md, README.md
- [ ] Remove all TOTP references (9+ files)
- [ ] Archive THE_PLAN.md and MASTER_BLUEPRINT.md
- [ ] Update CI/CD for TypeScript (tsc --noEmit step)

### Week 1-2 Exit Criteria:
- [ ] TypeScript strict mode, zero `any` types
- [ ] Dockview panels for all 14 widgets
- [ ] shadcn/ui components everywhere (no raw HTML controls)
- [ ] Zustand + Jotai + TanStack Query wired and working
- [ ] All documentation contradictions resolved
- [ ] Live OpenAlgo sandbox test during market hours

---

## 13. Weeks 3-6 Roadmap

### Week 3: Widget Absorption + New Widgets
- Absorb openalgo-chart components (Sector Map, Calculator, Alerts)
- Build MTM Monitor, Risk Panel, News Feed
- Build first-time setup wizard (/setup route with Quick/Guided/Advanced)
- Absorb openalgo-flow as Flow Builder tool
- Update Calculator widget with new STT rates (April 1, 2026: 0.05% futures, 0.15% options)

### Week 4: Tools + Investor Basics
- Build P&L Dashboard tool (calendar heatmap, absorb etftracker patterns)
- Build Strategy Builder tool (multi-leg, payoff, absorb Algomirror patterns)
- Absorb trading-journal as Trade Journal tool
- Start /invest route — Portfolio Tracker + Holdings only for beta (MF Explorer, SIP Calc, IPO → v0.2.0)
- /learn route deferred to v0.2.0 (not needed for beta)

### Week 5: Python Upgrades + Strategies
- Create packages/indicators/ (TA-Lib + Numba, absorb pyindicators)
- Integrate VectorBT into backtest-engine
- Implement user's EMA 20/50 + Supertrend 10/3 + DEMA 15 strategy (with specific SL/target logic)
- Absorb 20 highest-priority strategies from AlgoTrading repo (not all 59 — rest in v0.2.0)
- Absorb AlgoMirror patterns into ditto package (from ENHANCEMENT_BLUEPRINT.md)
- Start Rust/PyO3 backtest prototype (raptorbt pattern)

### Week 6: Testing + Beta Release
- Aggressive live testing with broker sandbox during market hours (every widget, every tool)
- Test with Kotak Neo sandbox if available
- Fix all bugs found during testing
- Performance optimization (Glide Data Grid for option chain)
- /learn route (basic content)

### Week 6: Beta Release
- Fix remaining bugs
- Update all documentation (CLAUDE.md, README.md, CONTRIBUTING.md)
- Clean up git history
- Tag v0.1.0-beta
- Publish to GitHub

---

## 14. TOTP Resolution

**REMOVED PERMANENTLY.** OpenAlgo handles broker authentication. FlintTrade never touches TOTP. All TOTP references across 14+ files will be deleted.

---

## 15. Documentation Cleanup (Week 1-2) — COMPLETE LIST (35 files)

> Note: infra/openalgo/ and infra/openclaw/ are submodules — DO NOT TOUCH.

### Files to REWRITE completely (5):
| File | Why |
|------|-----|
| PLAN.md | Completely stale — F-key modules, separate React apps, items already done |
| README.md | 662 tests, 3 React apps, TOTP reference, wrong architecture diagram |
| packages/terminal/CLAUDE.md | Port 3001, F1-F9 modules, TradePulse v0.3, branch strategy — ALL wrong |
| docs/ARCHITECTURE.md | subtree→submodule, single React app, Dockview, new state arch |
| docs/references/TOOLS_AND_DEPS.md | New deps (dockview, shadcn, zustand, jotai, tanstack, glide-data-grid, etc.) |

### Files to UPDATE (18):
| File | What to fix |
|------|------------|
| CLAUDE.md | Widget arch, 11 packages not 13, correct test count, 4 .env vars |
| AGENTS.md | Remove any F-key/TOTP references |
| CHANGELOG.md | Remove TOTP claims |
| CONTRIBUTING.md | Test count 662→670, canonical DEVLOG format |
| REPOS.md (root) | Sync with docs/references/REPOS.md |
| docs/OPERATIONS_GUIDE.md | Check for stale references |
| docs/SEBI_COMPLIANCE.md | Remove TOTP cron ref, add April 2026 STT rates |
| docs/references/REPOS.md | Sync with root |
| docs/references/OPENALGO_API.md | Check for accuracy |
| docs/machine-setup/QUICKSTART.md | Remove F1-F8, update for Dockview/TS |
| docs/setup/linux.md | Remove old module references |
| docs/setup/macos.md | Remove old module references |
| docs/setup/windows.md | Fix port 3000 reference |
| docs/setup/raspberry-pi.md | Remove old module references |
| infra/cron/README.md | Remove TOTP login_job reference |
| flint.toml | Remove TOTP from automation description |
| .env.example | Blank all values, 4 vars only |
| .github/ISSUE_TEMPLATE/*.md | Check templates are current |

### Files to CHECK (package READMEs — 10):
| File | Check for |
|------|-----------|
| packages/core/README.md | TOTP references |
| packages/engine/README.md | Stale module references |
| packages/data/README.md | Accuracy |
| packages/historical/README.md | Accuracy |
| packages/screener/README.md | Accuracy |
| packages/backtest-engine/README.md | Accuracy |
| packages/ai/README.md | Accuracy |
| packages/integration/README.md | Accuracy |
| packages/automation/README.md | TOTP reference (known) |
| packages/ditto/README.md | Accuracy |

### Files to ARCHIVE (4):
| File | Destination |
|------|------------|
| RESTRUCTURE.md | docs/references/historical/RESTRUCTURE_V1.md |
| docs/THE_PLAN.md | docs/references/historical/THE_PLAN_V1.md |
| docs/references/MASTER_BLUEPRINT.md | docs/references/historical/ |
| docs/superpowers/plans/2026-03-18-phase1-flexlayout-foundation.md | docs/references/historical/ |

### Files to DELETE (3):
| File | Why |
|------|-----|
| findings.md | Temp file from planning-with-files skill |
| task_plan.md | Temp file from planning-with-files skill |
| progress.md | Temp file from planning-with-files skill |

### Files to KEEP (mark as "absorbed"):
| File | Note |
|------|------|
| docs/references/ENHANCEMENT_BLUEPRINT.md | Has valuable detail on AlgoMirror + Kotak Neo. Mark header as "Absorbed into v2 spec" |

### DEVLOG canonical format (use everywhere):
```
## YYYY-MM-DD HH:MM IST | Machine | @username | IDE/Tool | AI Model/Agent | Branch | Summary
```
- CI/CD GitHub Actions — update for TypeScript (tsc --noEmit in CI)

Files to archive:
- docs/THE_PLAN.md → docs/references/historical/
- docs/references/MASTER_BLUEPRINT.md → docs/references/historical/

Files to delete:
- packages/dashboard/ (entire directory)
- packages/backtest/ (entire directory)
- All TOTP references across 9+ files

## 15b. Additional Items from FINAL_SWEEP

### STT Rate Increase (April 1, 2026)
- STT increasing to 0.05% futures (+150%) and 0.15% options (+50%)
- Calculator widget MUST use new rates after April 1
- Affects all brokerage/cost calculations in the platform

### Kotak Neo Cost-Based Routing
- Ditto package enhancement: when multiple brokers connected, route orders to cheapest
- Kotak Neo has 0 brokerage for API orders — should be preferred for execution
- Deferred to v0.2.0 but architecture must support it (broker cost metadata in workspace.json)

### Stub Tool Visibility
- User explicitly said: show all tools with descriptions + "Notify me when ready"
- Do NOT hide unbuilt tools — show what's coming, every one gets built

### package-lock.json Strategy
- Commit package-lock.json to git (remove from .gitignore)
- Ensures reproducible installs across 3 machines (Nitro, Mac, Ubuntu)

### DEVLOG Format (canonical)
- Use CLAUDE.md 7-field format everywhere
- Update global ~/.claude/CLAUDE.md to match

### OpenClaw Bridge
- Existing bridge in packages/automation/src/openclaw_bridge.py is untested
- Deferred to v0.2.0 — listed in Section 17
- PLAN.md item 9 is superseded by this spec

### AlgoMirror Patterns
- Ditto package should absorb architecture patterns from ENHANCEMENT_BLUEPRINT.md
- Includes: WebSocket service, position mirroring with multipliers, allocation modes
- Week 4 task when upgrading ditto

### Testing Strategy
- Unit: Vitest (existing)
- Integration: MSW (Mock Service Worker) for API mocking
- E2E: Playwright (already installed as MCP server)
- Test pyramid: many unit, some integration, few E2E
- CI: `tsc --noEmit && vitest run && playwright test`

### State Management Boundary Rules
- **Jotai atoms**: WebSocket real-time data ONLY (LTP, quote, depth per instrument)
- **TanStack Query**: REST API responses ONLY (positions, orders, holdings, funds, optionchain)
- **Zustand stores**: Derived/UI state ONLY (connection status, active layout, settings, aggregated P&L)
- Rule: data enters through ONE path only, never duplicated across stores

---

## 16. Known OpenAlgo Bugs to Work Around

From GitHub issues + Discord:
1. **Sandbox sends real orders** — verify isolation before testing
2. **closeposition ignores strategy** — track positions per-strategy ourselves
3. **WebSocket drops without heartbeat** — implement ping/pong in our client
4. **PNL calculation incorrect for some brokers** — calculate ourselves
5. **MCX symbol format inconsistency** — normalize in our symbol resolver
6. **SQLite concurrent access** — never touch OpenAlgo's DB directly

---

## 17. Deferred Features (Post-Beta, tracked not forgotten)

| Feature | Source Repo | Target Version |
|---------|-------------|---------------|
| Chrome Extension | openalgo-chrome | v0.2.0 |
| Excel Integration | OpenAlgo-Excel | v0.2.0 |
| Desktop App (Tauri) | fastscalper-tauri, openalgo-desktop | v0.3.0 |
| WhatsApp Alerts | wabridge | v0.2.0 |
| Mobile App | openalgo-mobile | v0.4.0 |
| Multi-user Auth | openalgo-multiuser | v0.3.0 |
| Blue-green Deployment | .env vars exist | v0.3.0 |
| QuestDB Tick Aggregation | openquest | v0.2.0 |
| FinRL Reinforcement Learning | FinRL | v0.4.0 |
| Multi-agent AI (TradingAgents) | TradingAgents | v0.4.0 |
| Unsloth QLoRA Fine-tuning | — | v0.5.0 |
| Kotak Neo Cost Routing | — | v0.2.0 |
| Dhan Rolling Option API | — | v0.2.0 |
| Historical Expired Options | ExpiryTrack | v0.2.0 |
| Pine Script Indicator Editor | PineTS | v0.3.0 |
| CLI Tools (Click) | CLI-Anything pattern | v0.2.0 |
| DDNS Auto-update | infra scripts | v0.2.0 |
| MCX Full Support | — | v0.2.0 |
| Crypto (Delta Exchange) | ccxt | v0.3.0 |
| Voice Orders | openalgo-voice-based-orders | v0.3.0 |

---

*This spec supersedes RESTRUCTURE.md, PLAN.md, and all previous architecture documents.*

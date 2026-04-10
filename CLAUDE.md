# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Single source of truth. Every Claude Code session on every machine starts here.
> After reading this, read PLAN.md to know what to build next.

## Quick Commands

```bash
# Terminal (React) — run from packages/terminal/
npm install                                    # install deps
npm run dev                                    # dev server at localhost:5173
npm run build                                  # tsc --noEmit + vite build
npm run typecheck                              # tsc --noEmit only
npx vitest run                                 # all tests (~1,696)
npx vitest run src/path/to/file.test.ts        # single test file
npx vitest run -t "test name"                  # single test by name

# Python — run from repo root
make test                                      # all pytest tests (~3,900)
make test-fast                                 # stop on first failure
python -m pytest packages/core/tests/test_foo.py -v              # single file
python -m pytest packages/core/tests/test_foo.py::test_name -v   # single test
make lint                                      # ruff check

# Services
make start                                     # start OpenAlgo
make stop                                      # stop OpenAlgo
make dev                                       # terminal dev + OpenAlgo
make status                                    # check services
make health                                    # health check

# CI (GitHub Actions — 3 jobs: python-tests, node-tests, secrets-check)
gh run list --limit 1                          # check latest CI
gh run view <id> --log-failed                  # diagnose failure
```

## What This Is

Open-source modular trading and investment platform for Indian F&O, commodities, and crypto.
Built on OpenAlgo (33 broker gateway). 16 packages (12 Python + 1 React + 1 Rust/PyO3 + 1 Chrome Extension + 1 Desktop/Tauri), monorepo, AGPL-3.0.
Repo: https://github.com/navaneeshnagarajan/FlintTrade

Serves three personas from a single application:
- **Trader** — Intraday F&O scalping, options analysis, real-time execution
- **Investor** — Mutual funds, SIPs, portfolio tracking, net worth
- **Beginner** — Guided learning, paper trading, market education

One app. One port. Route-based separation. Widget-composable workspace.

## Architecture

FlintTrade sits ON TOP of OpenAlgo. Never modifies it.

- **OpenAlgo:** Broker connections (33 brokers), REST API port 5000, WebSocket port 8765
- **FlintTrade:** Single React app (Dockview workspace) + Python backend (strategy engine, backtesting, AI, data pipelines, screener, multi-account orchestration)
- **Git submodules:** `infra/openalgo`, `infra/algomirror`, `infra/openclaw`
- Every machine runs its own OpenAlgo instance for development and testing. You CANNOT write correct code without testing against a live OpenAlgo.

```
FlintTrade (React + Python) ──── REST/WS ────> OpenAlgo (Flask, port 5000) ──> Broker API
```

### Application Routes

```
localhost:5173/
├── /welcome        → First-time cinematic welcome (smart redirect)
├── /explore        → Demo mode with sample data (no broker needed)
├── /setup          → First-time wizard (Quick / Guided / Advanced)
├── /settings       → Standalone settings page
├── /trade          → Trader workspace (Dockview canvas, 30 widgets)
├── /invest         → Investor dashboard (holdings, net worth, SIPs)
├── /learn          → Beginner center (courses, glossary, strategies)
├── /lab            → Strategy Lab (backtest, forward test, optimize)
├── /automate       → Automation Hub (flows, cron, monitors, logs)
├── /ai             → AI Center (chat, signals, sentiment, RAG)
├── /ditto          → Multi-account management (mirror, margin, risk)
├── /admin          → Admin panel (security, health, traffic, audit)
└── *               → 404 catch-all
```

All routes share: design system, API layer, auth state, WebSocket connection.
Each route lazy-loads its own module. No cross-route code in the initial bundle.

## Tech Stack

### Frontend (locked)

| Category | Choice | Version |
|----------|--------|---------|
| Language | TypeScript | 5.x (strict mode) |
| Framework | React | 19 |
| Build | Vite | 6.4+ |
| CSS | Tailwind CSS | v4 (`@tailwindcss/vite` plugin) |
| Components | shadcn/ui | latest (Radix accessibility, copy-paste ownership) |
| Layout/Docking | Dockview | v5.1 (floating, popout, tabs, serialize) |
| Charting | Lightweight Charts | v5 (35KB, multi-pane, plugins) |
| Data Grid (streaming) | Glide Data Grid | latest (canvas-rendered, 100K+ updates/sec) |
| Data Grid (static) | TanStack Table | v8 (headless, sortable, filterable) |
| State (global/UI) | Zustand | v5 (selectors, middleware, devtools) |
| State (market data) | Jotai | latest (per-instrument atoms, derived atoms) |
| State (REST cache) | TanStack Query | v5 (auto-cache, refetch, loading/error) |
| Forms | react-hook-form + zod | latest |
| Icons | lucide-react | latest (tree-shakable) |
| Dates | date-fns | latest (IST formatting) |
| Router | react-router-dom | latest |

### Backend (Python)

| Category | Choice |
|----------|--------|
| Runtime | Python 3.12 |
| HTTP Client | httpx (async) |
| Models | pydantic |
| Storage | DuckDB (analytics), QuestDB (ticks, future) |
| AI/ML | LM Studio + ChromaDB + LightGBM |
| Indicators | TA-Lib (batch) + Numba (streaming) — `indicators` package |
| Backtesting | VectorBT (exploration) + Rust/PyO3 (tick-level, future) |
| Linting | ruff |
| Testing | pytest (importlib mode) |

### Infrastructure

| Category | Choice |
|----------|--------|
| Broker Gateway | OpenAlgo (git submodule at `infra/openalgo`) |
| Real-time | WebSocket port 8765 (LTP/Quote/Depth modes) |
| Config | `.env` (4 vars) + in-app Settings (`workspace.json`) |
| Deployment | systemd (Ubuntu), local dev (Nitro/Mac) |

## State Architecture

```
WebSocket (port 8765)
    │ ticks
    ▼
Jotai Atoms ← WS real-time data ONLY (LTP, quote, depth per instrument)
    │ reads
    ▼
Zustand Stores ← Derived/UI state ONLY (connection, layout, settings, aggregated P&L)
    │ API calls
    ▼
TanStack Query ← REST API responses ONLY (positions, orders, holdings, funds, optionchain)
```

**Boundary rules — data enters through ONE path only, never duplicated across stores:**
- **Jotai atoms:** WebSocket real-time data ONLY (per-instrument LTP, quote, depth, derived PCR/straddle/greeks)
- **TanStack Query:** REST API responses ONLY (positions, orders, holdings, funds, option chain)
- **Zustand stores:** Derived/UI state ONLY (connection status, active layout, settings mirror, aggregated P&L, mode — `modeStore` with `explore | practice | live`)

Rate limiting built into the query layer: Orders 10/s, Smart orders 2/s, General API 50/s.

## Configuration

Two-tier config. No exceptions.

| Layer | File | What goes here |
|---|---|---|
| Infrastructure | `.env` | `OPENALGO_HOST`, `OPENALGO_PORT`, `OPENALGO_API_KEY`, `OPENALGO_WS_PORT` |
| User preferences | `~/.flinttrade/workspace.json` | Storage paths, enabled modules, LLM config, Telegram, theme, SEBI settings |

- `.env.example` has ALL values blank (open-source rule)
- Broker credentials are in OpenAlgo's own `.env` (`infra/openalgo/.env`), never in FlintTrade
- TOTP auto-login NOT implemented. OpenAlgo handles broker auth.
- API keys as env vars or workspace.json `_ref` fields, never hardcoded
- Cross-platform workspace: `~/.flinttrade/` (Linux), `~/Library/Application Support/flinttrade/` (macOS), `%APPDATA%/flinttrade/` (Windows)
- `~/.flinttrade/jwt_secret` is auto-generated on first startup (used for JWT auth tokens)
- All other config (LLM, Telegram, risk, data paths) is in workspace.json, configured in-app via Settings

## Monorepo Structure

### Python packages (12)

| Package | Description |
|---|---|
| `gateway` | Direct broker connections (33 brokers), adapter pattern, encrypted credentials, WebSocket bridge |
| `core` | Framework, OpenAlgo client (45+ endpoints), config, workspace, models, exceptions |
| `engine` | 5-layer safety system, order router, scheduler, base strategy, strategy registry |
| `data` | Tick recorder, audit logger (SEBI 5yr), trade logger, DuckDB storage |
| `historical` | OHLCV downloader, free data (OpenChart/yfinance), DuckDB pipeline, expiry manager |
| `screener` | Option chain, OI analysis, PCR, max pain, futures quadrant, portfolio Greeks, IV |
| `backtest-engine` | Simulator, metrics (Sharpe/Sortino/DD), walk-forward, Monte Carlo, 101 strategies |
| `ai` | LLM client (multi-provider), RAG (ChromaDB), signals, sentiment, MCP bridge, advisor |
| `integration` | TradingView webhooks, ChartInk, custom webhooks, flow builder, alerter |
| `automation` | Cron manager, Telegram bot with kill switch, OpenClaw bridge, post-market analysis |
| `ditto` | Multi-account manager, position mirror, margin calculator, trailing SL, risk manager |
| `indicators` | TA-Lib (batch, 150+ indicators) + Numba (streaming) + PineTS (Pine Script conversion) |

### Rust/PyO3 package (1)

| Package | Description |
|---|---|
| `tick-engine` | High-performance tick processing engine (Rust core with Python bindings via PyO3) |

### React package (1)

| Package | Port | Description |
|---|---|---|
| `terminal` | 5173 | Single React app. Dockview workspace, route-based personas, widget-composable layout. |

### Additional packages (2)

| Package | Description |
|---|---|
| `chrome-extension` | Browser extension for quick trading from any page |
| `desktop` | Tauri-based native desktop app wrapper |

The `dashboard` and `backtest` stub packages were deleted. Everything is in `terminal` now.

## Terminal — Widgets & Tools

30 widgets (all TSX) + 7 tools + 6 workspace presets. Widgets registered in `src/layout/widgetFactory.tsx`.

- **Widgets:** `src/widgets/` — Trading (10: dashboard, scalper, positions, orders, holdings, tradebook, orderpad, mtmmonitor, riskpanel, actioncenter), Analysis (14: chart, optionchain, oichart, straddle, depth, greeks, sectormap, gex, volsurface, ivsmile, straddlepnl, oiprofile, orderflow, depthheatmap), Utility (6: watchlist, calculator, news, ticker, aiadvisor, scanner)
- **Tools:** `src/tools/` — Canvas overlays (3: P&L Dashboard, Market Intelligence, Trade Journal) + Full-page tools (3: Backtest Lab, Flow Builder, Strategy Builder) + Settings
- **Full-page routes:** /lab (Backtest + Forward Test), /automate (Flows + Cron + Monitors), /ai (Chat + Signals + Sentiment + RAG)
- **Workspace presets:** Scalper Zone, Options Desk, Market Watch, Analysis, Risk Monitor, Investor View. Serialized via Dockview API.

## Current State

- **Version:** 0.5.0-dev — Post-Wave 53 (build sessions 2026-04-07/08/09/10)
- **Tests:** ~2,500 terminal (Vitest, 227+ files) + ~6,500 Python (pytest) = ~9,000 total
- **CI:** 5 parallel jobs (python-tests, node-core-tests, node-widget-tests-1, node-widget-tests-2, secrets-check)
- **Terminal:** 80 widgets (TSX) + 7 tools + 13 routes + 12 workspace presets in Dockview v5.1 shell
- **AI Skills:** 30 markdown files covering trading, analysis, execution, compliance, options, psychology domains
- **Strategies:** 29 backtest templates + 4 MTM straddle + Wheel + 101 engine strategies
- **AI:** RAG pipeline, ML advisor, auto-retraining, memory manager, trade reflection, news scheduler, skill system (10 skills), swarm executor
- **Analytics:** Options payoff engine, regime detector, correlation matrix, portfolio optimiser, order analytics, strategy comparator, multi-phase simulation
- **Mode system:** 3 modes (Explore/Practice/Live) with server-side order enforcement
- **Auth:** argon2id passwords, Fernet TOTP, JWT with daily 8AM IST expiry
- **TypeScript migration:** Complete. Zero JSX/JS files. Strict mode, no `any` types.
- **UI Foundation:** Geist font, SVG logo, 60+ design tokens, 3 cinematic themes (Graphite/Midnight/Ember) with dark/light/system variants, density modes, zero arbitrary values
- **UI Libraries:** Tremor (dashboards), Magic UI (animations), Aceternity UI (visual effects)
- **Onboarding:** Cinematic /welcome, /explore demo mode, setup wizard with persona × interest matrix
- **Routes:** 13 total — 8 app modules (Learn/Invest/Trade/Lab/Automate/AI/Ditto/Settings) + /welcome + /explore + /setup + /admin + 404
- **Full-stack wiring:** 100% OpenAlgo API coverage (45+ endpoints), 20 FlintTrade backend endpoints
- **Accessibility:** WCAG AA landmarks, skip-nav, ARIA tabs, prefers-reduced-motion
- **OpenAlgo:** Tested with broker sandbox, first trade placed
- **Shell:** TopBar (route tabs, market status, IST clock, ModeIndicator), TickerBar (16 instruments), WidgetPicker, PresetPicker, ToolsDropdown
- **State:** 7 Zustand stores (connection, layout, settings, trading, theme, skill, mode — connection persisted), Jotai market atoms, 15 TanStack Query hooks, WebSocket + REST fallback
- **Infrastructure:** Makefile, Docker Compose, systemd templates, GitHub Actions CI (3 jobs)
- **Workspace:** `~/.flinttrade/workspace.json`, cross-platform

## Decisions Made — DO NOT REVISIT

- No TOTP auto-login (OpenAlgo handles broker auth)
- Storage paths configurable via workspace.json, not hardcoded
- `.env` has only 4 vars
- Port: Terminal 5173 (single app, no other React ports)
- `.env.example` values ALL BLANK
- No personal hostnames, IPs, or provider names in committed code
- FlintTrade (capital T) in display text, `flinttrade` lowercase in paths/packages
- Tailwind CSS v4 with `@tailwindcss/vite` plugin
- Terminal theme: #0a0a0f bg, #16161f cards (was #12121a), #2a2a3a borders (was #1e1e2e)
- Font: Geist (headings) + Inter (body) + JetBrains Mono (numbers/data) — 3-tier system
- Route tabs: Learn / Invest / Trade order in TopBar (global navigation)
- Cinematic welcome at /welcome for first-time users (smart redirect)
- Pre-release (v0.x): all commits to main, no PRs required
- Dockview v5 for layout (NOT FlexLayout)
- Single React app with routes (NOT 3 separate apps)
- Widget-composable workspace (NOT F1-F8 fixed modules)
- shadcn/ui for all UI components (no raw HTML buttons/inputs/dialogs)
- TypeScript strict mode — no `any` types
- package-lock.json committed to git (reproducible installs across machines)

## OpenAlgo API Reference

### Orders (all POST)
`placeorder`, `placesmartorder`, `modifyorder`, `cancelorder`, `cancelallorder`, `closeposition`, `openposition`, `orderstatus`, `optionsorder`, `optionsmultiorder`, `basketorder`, `splitorder`

### Accounts (POST unless noted)
`funds`, `orderbook`, `tradebook`, `positionbook`, `holdings`, `margin`, `ping` (**POST**), `analyzer` (**POST**), `analyzer/toggle` (**POST**), `pnl/symbols` (**POST**)

### Data (POST unless noted)
`quotes`, `multiquotes`, `depth`, `history`, `optionchain`, `optiongreeks`, `multioptiongreeks`, `optionsymbol`, `symbol`, `search`, `expiry`, `intervals` (**GET**), `syntheticfuture`, `ticker`, `instruments` (**GET**), `gex`, `iv_smile`, `max_pain`, `oi_profile`, `chart` (**GET/POST** — chart preferences)

### Utilities
`holidays` (**POST**), `timings` (**POST**), `telegram` (POST)

### Broker Management (added OpenAlgo 2.0.0.2)
**NOTE:** These are session-authenticated, NOT under `/api/v1/`.
`/api/broker/capabilities` (**GET**), `broker/credentials` (**GET/POST**), `/leverage/api/current` (**GET**)

### WebSocket (port 8765)
Modes: 1=LTP, 2=Quote, 4=Depth (50 levels in v2; was mode 3 in v1)
Auth: `{ "action": "authenticate", "api_key": "<key>" }`
Subscribe: `{ "action": "subscribe", "symbols": [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}], "mode": "LTP" }`
Tick data arrives nested: `{ "type": "market_data", "data": { "ltp": ..., "symbol": ... } }`

### FlintTrade Backend Endpoints (/ft-api/v1/)
**Analysis (GET):** `gex`, `volsurface`, `ivsmile`, `straddlepnl`, `oiprofile`, `maxpain`
**Gateway (POST):** `broker/catalog`, `broker/accounts`, `broker/connect`, `broker/disconnect`, `broker/auth/apikey`, `broker/auth/totp`, `broker/auth/oauth`, `broker/auth/otp`, `broker/auth/callback`, `broker/reconnect`

### Rate limits
Orders: 10/sec | Smart orders: 2/sec | General API: 50/sec

### Known OpenAlgo Bugs to Work Around
1. Sandbox sends real orders — verify isolation before testing
2. closeposition ignores strategy — track positions per-strategy ourselves
3. WebSocket drops without heartbeat — implement ping/pong in our client
4. PNL calculation incorrect for some brokers — calculate ourselves
5. MCX symbol format inconsistency — normalize in our symbol resolver
6. SQLite concurrent access — never touch OpenAlgo's DB directly

## Available Tools and Skills

Claude Code on every machine has these installed globally:

**Skills:** superpowers (brainstorm/write-plan/execute-plan/TDD/debugging/code-review/git-worktrees/parallel-agents), frontend-design, vercel-react-best-practices, web-design-guidelines, planning-with-files, find-skills, gstack, firecrawl, deploy-to-vercel, vercel-composition-patterns, vercel-react-native-skills

**Plugins:** superpowers, frontend-design, VoltAgent subagents (meta, lang), claude-md-management, skill-creator

**Agents:** 172 agency-agents (engineering, design, testing, product, strategy, marketing, sales, etc.) installed in `~/.claude/agents/`

**MCP Servers:** context7 (live library docs), playwright (browser testing), sequential-thinking, github, firecrawl

For the complete list of all 222 repositories, libraries, skills, and tools, see `docs/REFERENCES.md`

### USE THESE ACTIVELY
- `/brainstorm` before starting any major feature
- `/write-plan` to create structured implementation plans
- `/execute-plan` to build from plans
- `frontend-design` skill when building any UI component
- `vercel-react-best-practices` for React code
- `context7` MCP to look up latest library APIs instead of guessing
- `playwright` MCP to test UI changes in a real browser
- `/simplify` after completing a feature
- `/code-review` before marking any task done
- Check `.local/reference/REPO_FEATURE_MAP.md` before writing new code — absorb from existing repos first
- Use specialized agents (e.g., engineering, testing) over general-purpose ones

## Code Standards

- **TypeScript:** Strict mode, no `any` types, all new terminal code in `.ts`/`.tsx`. Path alias `@` → `packages/terminal/src/`
- **React:** Functional components, hooks, Tailwind CSS v4, shadcn/ui components, lucide-react icons
- **Python:** PEP 8, ruff, type hints, Google docstrings, absolute imports
- **Tests:** pytest (Python, `--import-mode=importlib` required for flat package layout) + Vitest (terminal). Every new function needs a test.
- **Vite proxy (dev):** `/api` → OpenAlgo:5000, `/ft-api` → FlintTrade backend:5100, `/ws` → ws://127.0.0.1:8765. Port 5100 avoids conflict with OpenAlgo multi-instance (5000-5009). In dev mode `api.ts` uses relative paths (empty base); production uses full host from connectionStore. Don't bypass the proxy in dev.
- **Git:** Conventional commits (`feat(pkg):`, `fix(pkg):`, `docs:`, `test:`, `chore:`)
- **Branch:** main only (pre-alpha)
- **Widgets:** Every widget is a Dockview panel registered in `widgetFactory.tsx`
- **Forms:** react-hook-form + zod for validation
- **Data grids:** Glide Data Grid for streaming data (option chain), TanStack Table for static data (positions, orders)

## Development Workflow

1. Read CLAUDE.md and PLAN.md
2. Pick the next unchecked task from PLAN.md
3. Check `docs/REFERENCES.md` — absorb before building
4. Use `/brainstorm` and `/write-plan` for non-trivial tasks
5. Implement — full permissions: create, edit, delete, refactor as needed
6. Run: `make test` (must pass 3,900+ Python) and `npx vitest run` in terminal (must pass 1,696+)
7. For React: `npm run build` in `packages/terminal` (must build clean)
8. Mark task done in PLAN.md
9. Update CHANGELOG.md [Unreleased] section for notable changes
10. Commit with detailed conventional message (see CONTRIBUTING.md)

Workflow: `READ → PLAN → APPROVE → BUILD → VERIFY → TEST → UPDATE → COMMIT`

## Machine Setup

Every machine (Nitro, Mac, Ubuntu, or new contributor) can:
- Run OpenAlgo locally for development and testing
- Write, create, delete, refactor ANY code
- Run all tests and build all packages
- Commit and push
- Use all skills, plugins, MCP servers, and agents

To set up a new machine:
1. `git clone --recursive https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `make setup`
3. `cp .env.example .env` and set `OPENALGO_API_KEY`
4. Configure `infra/openalgo/.env` with broker credentials
5. `make start` (starts OpenAlgo)
6. `make test` (verify 3,900+ pass)
7. `cd packages/terminal && npm install && npm run build` (verify clean build, 1,696+ vitest pass)
8. Read PLAN.md, pick a task, start building

See `docs/machine-setup/QUICKSTART.md` for detailed instructions.

## Do NOT

- Modify files inside `infra/openalgo/`, `infra/openclaw/`, `infra/algomirror/` (submodules)
- Hardcode API keys, hostnames, IPs, provider names, or personal values
- Use mock/placeholder/fake data in terminal or any UI
- Commit `.env` files (only `.env.example` with blank values)
- Use port 3000/3001/3002 for anything
- Add TOTP auto-login
- Duplicate functionality that OpenAlgo already provides
- Bypass hooks with `--no-verify` or `dangerouslySkipPermissions`
- Write new code without checking `.local/reference/REPO_FEATURE_MAP.md` first — absorb, don't reinvent
- Use general-purpose agents when specialized ones exist (e.g., use engineering agent for code, testing agent for tests)
- Skip spec review or code review for non-trivial changes
- Use raw HTML buttons/inputs/dialogs — use shadcn/ui
- Use `any` type in TypeScript
- Create fixed layouts — every widget must be a Dockview panel
- Include private data in commit messages (fund amounts, order IDs, broker names)

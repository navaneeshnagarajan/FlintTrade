# FlintTrade

> Single source of truth. Every Claude Code session on every machine starts here.
> After reading this, read PLAN.md to know what to build next.

## What This Is

Open-source modular trading and investment platform for Indian F&O, commodities, and crypto.
Built on OpenAlgo (30+ broker gateway). 12 packages (11 Python + 1 React), monorepo, AGPL-3.0.
Repo: https://github.com/navaneeshnagarajan/FlintTrade

Serves three personas from a single application:
- **Trader** — Intraday F&O scalping, options analysis, real-time execution
- **Investor** — Mutual funds, SIPs, portfolio tracking, net worth
- **Beginner** — Guided learning, paper trading, market education

One app. One port. Route-based separation. Widget-composable workspace.

## Architecture

FlintTrade sits ON TOP of OpenAlgo. Never modifies it.

- **OpenAlgo:** Broker connections (30+ brokers), REST API port 5000, WebSocket port 8765
- **FlintTrade:** Single React app (Dockview workspace) + Python backend (strategy engine, backtesting, AI, data pipelines, screener, multi-account orchestration)
- **Git submodules:** `infra/openalgo`, `infra/algomirror`, `infra/openclaw`
- Every machine runs its own OpenAlgo instance for development and testing. You CANNOT write correct code without testing against a live OpenAlgo.

```
FlintTrade (React + Python) ──── REST/WS ────> OpenAlgo (Flask, port 5000) ──> Broker API
```

### Application Routes

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
- **Zustand stores:** Derived/UI state ONLY (connection status, active layout, settings mirror, aggregated P&L)

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
- All other config (LLM, Telegram, risk, data paths) is in workspace.json, configured in-app via Settings

## Monorepo Structure

### Python packages (11)

| Package | Description |
|---|---|
| `core` | Framework, OpenAlgo client (45+ endpoints), config, workspace, models, exceptions |
| `engine` | 5-layer safety system, order router, scheduler, base strategy, strategy registry |
| `data` | Tick recorder, audit logger (SEBI 5yr), trade logger, DuckDB storage |
| `historical` | OHLCV downloader, free data (OpenChart/yfinance), DuckDB pipeline, expiry manager |
| `screener` | Option chain, OI analysis, PCR, max pain, futures quadrant, portfolio Greeks, IV |
| `backtest-engine` | Simulator, metrics (Sharpe/Sortino/DD), walk-forward, Monte Carlo, 12 strategies |
| `ai` | LLM client (multi-provider), RAG (ChromaDB), signals, sentiment, MCP bridge, advisor |
| `integration` | TradingView webhooks, ChartInk, custom webhooks, flow builder, alerter |
| `automation` | Cron manager, Telegram bot with kill switch, OpenClaw bridge, post-market analysis |
| `ditto` | Multi-account manager, position mirror, margin calculator, trailing SL, risk manager |
| `indicators` | TA-Lib (batch, 150+ indicators) + Numba (streaming) + PineTS (Pine Script conversion) |

### React package (1)

| Package | Port | Description |
|---|---|---|
| `terminal` | 5173 | Single React app. Dockview workspace, route-based personas, widget-composable layout. |

The `dashboard` and `backtest` stub packages were deleted. Everything is in `terminal` now.

## Terminal — Widgets

### Existing (21 widgets, all TSX)

**Trading (7):**

| Widget | Status |
|--------|--------|
| Dashboard | Built (TSX) — account overview, indices, P&L |
| Scalper | Built (TSX) — 3-panel CE/Spot/PE + order buttons |
| Order Pad | Built (TSX) — full order entry form |
| Positions | Built (TSX) — live positions + P&L |
| Orders | Built (TSX) — order book |
| Holdings | Built (TSX) — delivery holdings |
| Trade Book | Built (TSX) — trade history |

**Analysis (6):**

| Widget | Status |
|--------|--------|
| Chart | Built (TSX) — LWC v5, indicators, drawing tools |
| Option Chain | Built (TSX) — full chain, OI/LTP/Greeks |
| OI Chart | Built (TSX) — horizontal OI bars, PCR, S/R |
| Straddle | Built (TSX) — ATM tracking, overlays |
| Depth | Built (TSX) — 5-level bid/ask |
| Greeks | Built (TSX) — portfolio Delta/Gamma/Theta/Vega |

**Utility (1):**

| Widget | Status |
|--------|--------|
| Watchlist | Built (TSX) — live quotes, sparklines, search |

**New (7):**

| Widget | Status |
|--------|--------|
| Sector Map | Built (TSX) — absorbed from openalgo-chart SectorHeatmapModal |
| News Feed | Built (TSX) — absorbed from finnews-ai, sentiment-tagged |
| Calculator | Built (TSX) — absorbed from openalgo-chart RiskCalculatorPanel |
| Ticker | Built (TSX) — customizable scrolling prices |
| MTM Monitor | Built (TSX) — absorbed from algo_trading_strategies_india |
| Risk Panel | Built (TSX) — max position, margin usage, daily limits |
| AI Advisor | Built (TSX) — absorbed from openalgo-chatbot + voice |

### Tools (7 full-page views)

| Tool | Status |
|------|--------|
| P&L Dashboard | Built — calendar heatmap, trade stats (absorbed etftracker) |
| Strategy Builder | Built — multi-leg, payoff chart, Greeks (absorbed Algomirror) |
| Flow Builder | Built — 54 node types, visual automation (absorbed openalgo-flow) |
| Market Intelligence | Built — FII/DII, sector rotation, RRG (absorbed etftracker) |
| Backtest Lab | Built — tick-level options backtesting (VectorBT) |
| Trade Journal | Built — analytics, screenshots, review (absorbed trading-journal) |
| Settings | Built — in-app config, restart button |

### Layout Presets (7)

Start Fresh, Scalper Zone, Volatility Trading, Market Watch, Options Desk, Investor View, and custom user layouts. Serialized via Dockview API.

## Current State

- **Version:** 0.1.0-alpha
- **Phases 1-9 complete:** Foundation, state architecture, shell, widget migration, verification, new widgets, tools, routes, Python upgrades
- **Tests:** 26 terminal (Vitest) + 712 Python (pytest) = 738 total
- **Terminal:** 21 widgets (TSX) + 7 tools (all functional) + 4 routes in Dockview v5.1 shell
- **TypeScript migration:** Complete. Zero JSX/JS files. Strict mode, no `any` types.
- **3 critical bugs fixed:** ping GET (was POST), closePosition body, optionchain expiry param
- **OpenAlgo:** Tested with broker sandbox, first trade placed
- **Shell components (TSX):** TopBar, TickerBar, WidgetPicker, ToolsDropdown, widgetFactory
- **State layer (TS):** 4 Zustand stores, Jotai market atoms, 6 TanStack Query hooks, WebSocket service with ping/pong
- **Infrastructure:** Makefile (setup/start/stop/test/status), setup.sh, systemd templates, health-check.sh
- **Workspace:** `~/.flinttrade/workspace.json`, cross-platform, CLI: `python -m packages.core.src.cli init|status`

## Decisions Made — DO NOT REVISIT

- No TOTP auto-login (OpenAlgo handles broker auth)
- Storage paths configurable via workspace.json, not hardcoded
- `.env` has only 4 vars
- Port: Terminal 5173 (single app, no other React ports)
- `.env.example` values ALL BLANK
- No personal hostnames, IPs, or provider names in committed code
- FlintTrade (capital T) in display text, `flinttrade` lowercase in paths/packages
- Tailwind CSS v4 with `@tailwindcss/vite` plugin
- Terminal theme: #0a0a0f bg, #12121a cards, #1e1e2e borders, Inter UI, JetBrains Mono numbers
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
`funds`, `orderbook`, `tradebook`, `positionbook`, `holdings`, `margin`, `ping` (**GET**), `analyzer/status` (**GET**), `analyzer/toggle`

### Data (POST unless noted)
`quotes`, `multiquotes`, `depth`, `history`, `optionchain`, `optiongreeks`, `multioptiongreeks`, `optionsymbol`, `symbol`, `search`, `expiry`, `intervals` (**GET**), `syntheticfuture`, `ticker`, `instruments` (**GET**), `gex`, `iv_smile`, `max_pain`, `oi_profile`

### Utilities
`holidays` (**GET**), `timings` (**GET**), `telegram` (POST)

### WebSocket (port 8765)
Modes: 1=LTP, 2=Quote, 3=Depth (50 levels in v2)
Subscribe: `{ "action": "subscribe_ltp", "instruments": [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}] }`

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

For the complete list of all 222 repositories, libraries, skills, and tools, see `docs/references/REPOS.md`

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
- Check `docs/references/REPOS.md` and `docs/REPO_FEATURE_MAP.md` before writing new code — absorb from existing repos first
- Use specialized agents (e.g., engineering, testing) over general-purpose ones

## Code Standards

- **TypeScript:** Strict mode, no `any` types, all new terminal code in `.ts`/`.tsx`
- **React:** Functional components, hooks, Tailwind CSS v4, shadcn/ui components, lucide-react icons
- **Python:** PEP 8, ruff, type hints, Google docstrings, absolute imports
- **Tests:** pytest (Python, importlib mode) + Vitest (terminal). Every new function needs a test.
- **Git:** Conventional commits (`feat(pkg):`, `fix(pkg):`, `docs:`, `test:`, `chore:`)
- **Branch:** main only (pre-alpha)
- **Widgets:** Every widget is a Dockview panel registered in `widgetFactory.tsx`
- **Forms:** react-hook-form + zod for validation
- **Data grids:** Glide Data Grid for streaming data (option chain), TanStack Table for static data (positions, orders)

## Development Workflow

1. Read CLAUDE.md and PLAN.md
2. Pick the next unchecked task from PLAN.md
3. Check `docs/REPO_FEATURE_MAP.md` — absorb before building
4. Use `/brainstorm` and `/write-plan` for non-trivial tasks
5. Implement — full permissions: create, edit, delete, refactor as needed
6. Run: `make test` (must pass 712+ Python) and `npx vitest run` in terminal (must pass 26+)
7. For React: `npm run build` in `packages/terminal` (must build clean)
8. Mark task done in PLAN.md
9. Update DEVLOG.md with entry
10. Commit with conventional message

For the complete SOP: `READ → PLAN → APPROVE → BUILD → VERIFY → TEST → FIX → UPDATE → COMMIT`

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
6. `make test` (verify 712+ pass)
7. `cd packages/terminal && npm install && npm run build` (verify clean build)
8. Read PLAN.md, pick a task, start building

See `docs/machine-setup/QUICKSTART.md` for detailed instructions.

## DEVLOG Format

```
## YYYY-MM-DD HH:MM IST | Machine | @username | IDE/Tool | AI Model/Agent | Branch | Summary
```

Machines: `nitro-dev` (Windows), `mac-dev` (macOS), `ubuntu-server` (Ubuntu)

## Do NOT

- Modify files inside `infra/openalgo/`, `infra/openclaw/`, `infra/algomirror/` (submodules)
- Hardcode API keys, hostnames, IPs, provider names, or personal values
- Use mock/placeholder/fake data in terminal or any UI
- Commit `.env` files (only `.env.example` with blank values)
- Use port 3000/3001/3002 for anything
- Add TOTP auto-login
- Duplicate functionality that OpenAlgo already provides
- Skip DEVLOG entries
- Bypass hooks with `--no-verify` or `dangerouslySkipPermissions`
- Write new code without checking `docs/REPO_FEATURE_MAP.md` first — absorb, don't reinvent
- Use general-purpose agents when specialized ones exist (e.g., use engineering agent for code, testing agent for tests)
- Skip spec review or code review for non-trivial changes
- Use raw HTML buttons/inputs/dialogs — use shadcn/ui
- Use `any` type in TypeScript
- Create fixed layouts — every widget must be a Dockview panel
- Include private data in commit messages (fund amounts, order IDs, broker names)

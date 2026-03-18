# FlintTrade

> Single source of truth. Every Claude Code session on every machine starts here.
> After reading this, read PLAN.md to know what to build next.

## What This Is

Open-source modular trading platform for Indian F&O, commodities, and crypto.
Built on OpenAlgo (30+ broker gateway). 13 packages, monorepo, AGPL-3.0.
Repo: https://github.com/navaneeshnagarajan/FlintTrade

## Architecture

FlintTrade sits ON TOP of OpenAlgo. Never modifies it.

- **OpenAlgo:** Broker connections (30+ brokers), REST API port 5000, WebSocket port 8765
- **FlintTrade:** Terminal UI, strategy engine, backtesting, AI signals, data pipelines, screener, multi-account orchestration
- **Git submodules:** `infra/openalgo`, `infra/algomirror`, `infra/openclaw`
- Every machine runs its own OpenAlgo instance for development and testing. You CANNOT write correct code without testing against a live OpenAlgo.

```
FlintTrade (React + Python) ──── REST/WS ────> OpenAlgo (Flask, port 5000) ──> Broker API
```

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

## Monorepo Structure

### Python packages (10)

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

### React packages (3)

| Package | Port | Description |
|---|---|---|
| `terminal` | 5173 | Trading terminal UI. Dashboard module built, 7 more planned (F2-F8). |
| `dashboard` | 5174 | Portfolio overview app. Stub. |
| `backtest` | 5175 | Backtest config and results UI. Stub. |

## Current State

- **Version:** 0.1.0-alpha
- **Tests:** 670 passing
- **OpenAlgo:** Tested with Dhan Sandbox, first trade placed (SBIN BUY 1 MIS)
- **Terminal:** React, dashboard module with live API, professional dark theme (#0a0a0f bg, Inter + JetBrains Mono, dense layout), 8-module sidebar (F1-F8), connection indicator, market status badge. Only F1 (Dashboard) is built. F2-F8 show "Coming Soon".
- **Infrastructure:** Makefile (setup/start/stop/test/status), setup.sh auto-installs OpenAlgo deps + gunicorn + generates security keys, systemd templates, health-check.sh
- **Workspace:** `~/.flinttrade/workspace.json`, cross-platform, CLI: `python -m packages.core.src.cli init|status`

## Decisions Made — DO NOT REVISIT

- No TOTP auto-login (OpenAlgo handles broker auth)
- Storage paths configurable via workspace.json, not hardcoded
- `.env` has only 4 vars
- Ports: OpenAlgo 5000, WS 8765, Terminal 5173, Dashboard 5174, Backtest 5175
- `.env.example` values ALL BLANK
- No personal hostnames, IPs, or provider names in committed code
- FlintTrade (capital T) in display text, `flinttrade` lowercase in paths/packages
- Tailwind CSS v4 with `@tailwindcss/vite` plugin
- Terminal theme: #0a0a0f bg, #12121a cards, #1e1e2e borders, Inter UI, JetBrains Mono numbers
- Pre-release (v0.x): all commits to main, no PRs required

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

## Available Tools and Skills

Claude Code on every machine has these installed globally:

**Skills:** superpowers (brainstorm/write-plan/execute-plan/TDD/debugging), frontend-design, vercel-react-best-practices, web-design-guidelines, planning-with-files, find-skills, gstack, firecrawl (8 skills)

**Plugins:** superpowers, frontend-design, VoltAgent subagents (meta, lang)

**Agents:** 172 agency-agents (engineering, design, testing, product, strategy, marketing, sales, etc.)

**MCP Servers:** context7 (live library docs), playwright (browser testing), sequential-thinking, github, firecrawl

For the complete list of all repositories, libraries, skills, and tools, see `docs/references/REPOS.md`

### USE THESE ACTIVELY
- `/brainstorm` before starting any major feature
- `/write-plan` to create structured implementation plans
- `/execute-plan` to build from plans
- `frontend-design` skill when building any UI component
- `vercel-react-best-practices` for React code
- `context7` MCP to look up latest library APIs instead of guessing
- `playwright` MCP to test UI changes in a real browser
- `/simplify` after completing a feature

## Code Standards

- **Python:** PEP 8, ruff, type hints, Google docstrings, absolute imports
- **React:** Functional components, hooks, Tailwind CSS v4, lucide-react icons
- **Tests:** pytest with importlib mode. Every new function needs a test.
- **Git:** Conventional commits (`feat(pkg):`, `fix(pkg):`, `docs:`, `test:`, `chore:`)
- **Branch:** main only (pre-alpha)

## Development Workflow

1. Read CLAUDE.md and PLAN.md
2. Pick the next unchecked task from PLAN.md
3. Use `/brainstorm` and `/write-plan` for non-trivial tasks
4. Implement — full permissions: create, edit, delete, refactor as needed
5. Run: `make test` (must pass 670+)
6. For React: `npm run build` in the package dir (must build clean)
7. Mark task done in PLAN.md
8. Update DEVLOG.md with entry
9. Commit with conventional message
10. Push to origin main

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
6. `make test` (verify 670+ pass)
7. Read PLAN.md, pick a task, start building

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

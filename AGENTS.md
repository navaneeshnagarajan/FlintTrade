# FlintTrade — Agent Context

> For Antigravity, OpenClaw, Gemini, Copilot, and other non-Claude AI agents.
> Claude Code: read CLAUDE.md instead (more detailed).
> After this file, read PLAN.md to know what to build next.

## What This Is

Open-source modular trading platform for Indian F&O, commodities, crypto.
Built on OpenAlgo (30+ broker gateway). 12 packages (11 Python + 1 React), monorepo, AGPL-3.0.
Repo: https://github.com/navaneeshnagarajan/FlintTrade | Version: 0.1.0-alpha

## Architecture

- FlintTrade sits ON TOP of OpenAlgo (never modifies it)
- OpenAlgo: broker connections (30+ brokers), REST port 5000, WS port 8765
- FlintTrade: terminal, strategies, backtest, AI, data, screener, multi-account
- Submodules: `infra/openalgo`, `infra/algomirror`, `infra/openclaw`

## Configuration

- `.env` = 4 infrastructure vars (OPENALGO_HOST, PORT, API_KEY, WS_PORT)
- `~/.flinttrade/workspace.json` = user preferences (paths, modules, LLM, theme)
- Broker credentials in OpenAlgo's `.env`, NOT FlintTrade
- Broker auth handled entirely by OpenAlgo

## Packages

**Python (11):** core, engine, data, historical, screener, backtest-engine, ai, integration, automation, ditto, indicators
**Rust/PyO3 (1):** tick-engine
**React (1):** terminal (5173)

## Current State (v0.1.0-alpha, released 2026-03-21)

- 1,021 tests passing (985 Python + 36 terminal)
- Terminal: 21 widgets (TSX), 4 canvas tools, 10 routes, 6 workspace presets, 5 themes
- Routes: /welcome, /explore, /setup, /settings, /trade, /invest, /learn, /lab, /automate, /ai
- 20 FlintTrade backend endpoints, 100% OpenAlgo API coverage
- Read PLAN.md for next tasks

## OpenAlgo API

**Orders (POST):** placeorder, placesmartorder, modifyorder, cancelorder, cancelallorder, closeposition, openposition, orderstatus, optionsorder, optionsmultiorder, basketorder, splitorder

**Accounts:** funds, orderbook, tradebook, positionbook, holdings, margin (POST) | ping, analyzer/status (GET) | analyzer/toggle (POST)

**Data:** quotes, multiquotes, depth, history, optionchain, optiongreeks, multioptiongreeks, optionsymbol, symbol, search, expiry, syntheticfuture, ticker, gex, iv_smile, max_pain, oi_profile (POST) | intervals, instruments (GET)

**Utilities:** holidays, timings (GET) | telegram (POST)

**WebSocket (8765):** modes 1=LTP, 2=Quote, 3=Depth | Rate: 10 orders/sec, 50 API/sec

## Code Standards

- Python: ruff, type hints, pytest importlib mode
- React: functional components, Tailwind v4, lucide-react
- Conventional commits: `feat(pkg):`, `fix(pkg):`, `docs:`
- Pre-alpha: all commits to main

## Workflow

1. Read CLAUDE.md and PLAN.md
2. Pick next unchecked task from PLAN.md
3. Implement
4. Run: `python -m pytest packages/*/tests/ tests/ -v --tb=short --import-mode=importlib`
5. Update PLAN.md, DEVLOG.md
6. Commit and push

## Do NOT

- Modify submodules (`infra/openalgo/`, `infra/algomirror/`, `infra/openclaw/`)
- Hardcode credentials, IPs, hostnames
- Use mock data in terminal
- Commit `.env` files
- Use ports 3000/3001/3002
- Implement broker auth (OpenAlgo handles it)
- Duplicate what OpenAlgo already provides

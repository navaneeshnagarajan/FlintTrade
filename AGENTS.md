# FlintTrade — Agent Context

> For Antigravity, OpenClaw, Gemini, and other non-Claude AI agents.
> Claude Code: read CLAUDE.md instead (more detailed).

## What This Is

Open-source modular trading platform for Indian markets built on OpenAlgo.
13 packages, monorepo, AGPL-3.0, version 0.1.0-alpha.
Repo: https://github.com/navaneeshnagarajan/FlintTrade

## Architecture

- FlintTrade sits ON TOP of OpenAlgo (never modifies it)
- OpenAlgo: broker connections (30+ brokers), REST port 5000, WS port 8765
- FlintTrade: terminal, strategies, backtest, AI, data, screener, multi-account
- Submodules: `infra/openalgo`, `infra/algomirror`, `infra/openclaw`

## Configuration

- `.env` = 4 infrastructure vars only (OPENALGO_HOST, PORT, API_KEY, WS_PORT)
- `~/.flinttrade/workspace.json` = user preferences (paths, modules, LLM, theme)
- Broker credentials in OpenAlgo, NOT FlintTrade
- No TOTP auto-login

## Packages

**Python (10):** core, engine, data, historical, screener, backtest-engine, ai, integration, automation, ditto
**React (3):** terminal (5173), dashboard (5174), backtest (5175)

## Current State

- 670 tests passing
- Terminal: live dashboard, 8-module sidebar, dark theme
- First trade placed via Dhan Sandbox
- Read PLAN.md for next tasks

## Code Standards

- Python: ruff, type hints, pytest with importlib mode
- React: functional components, Tailwind v4, lucide-react
- Conventional commits: `feat(pkg):`, `fix(pkg):`, `docs:`
- Pre-alpha: all commits to main

## Workflow

1. Read PLAN.md
2. Pick next unchecked task
3. Implement
4. Run: `python -m pytest packages/*/tests/ tests/ -v --tb=short --import-mode=importlib`
5. Update PLAN.md, DEVLOG.md
6. Commit and push

## Do NOT

- Modify submodules (infra/openalgo/, infra/algomirror/, infra/openclaw/)
- Hardcode credentials, IPs, hostnames
- Use mock data in terminal
- Commit .env files
- Use ports 3000/3001/3002
- Reference specific brokers in package code
- Add TOTP auto-login

# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added — v2 Migration (2026-03-19)
- TypeScript strict mode migration — zero JSX/JS files remain
- Dockview v5.1 widget-composable workspace (replaced FlexLayout)
- State architecture: Zustand 5 + Jotai + TanStack Query 5 (replaced DataBus)
- 21 widgets (all TSX): 14 migrated + 7 new (SectorMap, Calculator, MTMMonitor, RiskPanel, NewsFeed, Ticker, AIAdvisor)
- 7 functional tools (zero stubs): Settings, P&L Dashboard, Strategy Builder, Trade Journal, Flow Builder, Market Intelligence, Backtest Lab
- 4 routes: /terminal, /setup (wizard), /invest (dashboard), /learn (placeholder)
- indicators package: 13 indicators, 42 tests (EMA, SMA, DEMA, Supertrend, VWAP, RSI, MACD, etc.)
- User's EMASuperTrendDEMA strategy implementation
- CI: GitHub Actions (python-tests, node-tests, secrets-check)
- shadcn/ui components throughout (no raw HTML controls)
- 738 total tests (712 Python + 26 terminal)

## [0.1.0-alpha] — 2026-03-16

First pre-release. All 12 packages built, 738 tests passing, Docker support.

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

## [0.0.1-dev] — 2026-03-14

### Added
- Monorepo — 12 packages with per-package CLAUDE.md + AGENTS.md
- CI/CD — GitHub Actions (pytest, ruff, secrets check)
- SEBI compliance framework — rate limits, kill switch architecture, audit
- Infrastructure — nginx, systemd, WireGuard, fail2ban, deploy scripts
- Git-native bug tracking system
- Documentation — OpenAlgo API reference, tools guide, machine configs

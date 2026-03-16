# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.6.0-dev] — 2026-03-16

### Added
- Docker support — docker-compose.yml for Windows/macOS/Linux/Raspberry Pi
- Cross-platform setup guides (docs/setup/)
- FlintTradeApp entry point — wires all 13 packages into single startup
- systemd service file — auto-start on boot, restart on failure
- Production deployment scripts — deploy, setup, health-check
- Feature flags — ENABLE_BACKTEST, ENABLE_AI in .env.example

### Fixed
- Vite server.host=true for Docker port binding on all 3 React apps
- jugaad-data version pin corrected (0.31.0)
- npm removed from apt install (Node 22 includes it)

## [0.5.0-dev] — 2026-03-16

### Added
- CronManager — 5 required jobs: login(08:30), health(09:10),
  square-off warning(15:20), eod logout(23:45), holiday check on startup
- TOTPLogin — pyotp + jugaad-data holiday detection, 3-retry login
- Telegram /kill wired to SafetySystem + OrderRouter + StrategyScheduler
- Telegram /status returns live positions, funds, running strategies
- async holidays load — await cron.load_holidays() in FlintTradeApp.start()

### Fixed
- backtest-engine sys.path ordering — all 51 tests now passing
- asyncio.run() inside running event loop in CronManager

## [0.4.0-dev] — 2026-03-16

### Added
- StrategyRunner — async tick loop with deploy freeze guard, market hours
  guard, auto square-off at exchange close
- StrategyScheduler — multi-strategy lifecycle management
- EMACrossover — first concrete strategy, pure Python EMA, position reversal
- DELTA exchange — 24/7 market hours, CCXT_EXCHANGES separation
- Per-exchange market hours in SafetySystem (NFO/BFO 15:30, CDS 17:00,
  MCX 23:30, DELTA 24/7)
- OrderRouter wired to OpenAlgoClient + AuditLogger
- Full E2E: strategy signal → 5 safety layers → audit → broker → audit

## [0.3.0-dev] — 2026-03-16

### Added
- terminal: 9-module React trading terminal — scalper, option chain,
  OI analysis, futures quadrant, TradingView charts, keyboard shortcuts
- dashboard: portfolio overview, P&L analytics, system status, trade journal
- backtest: backtest UI — config panel, results, equity curves, compare mode
- React 19 compatibility — lucide-react bumped to 0.577.0

## [0.2.0-dev] — 2026-03-16

### Added
- engine: 5-layer SafetySystem (OrderValidation, PositionLimits,
  PortfolioRisk, DailyPnL, KillSwitch)
- data: SEBI audit trail (JSONL append-only, gzip rotation, 5-year retention)
- data: DuckDB storage — ticks, trades, daily summaries
- historical: multi-source downloader, free NSE data, DuckDB pipeline
- screener: option chain, OI spurt, futures quadrant, portfolio Greeks, IV
- backtest-engine: event-driven simulator, walk-forward optimizer, 12
  strategy templates, Monte Carlo
- integration: TradingView webhooks, ChartInk, visual flow builder
- ai: LLM client, RAG, ML signals, news sentiment, MCP bridge
- automation: TOTP login, cron, Telegram bot, OpenClaw bridge
- ditto: position mirroring, margin-aware allocation, trailing SL

### Fixed
- OpenAlgo nested data key unwrapping — 15 response parsers corrected
- pytest-asyncio added to requirements
- openalgo_client converted to async httpx

## [0.1.0-dev] — 2026-03-16

### Added
- core: async OpenAlgo client — 39 endpoints, rate limiting (10 OPS orders,
  2 OPS smart, 50 OPS general), exponential backoff retry
- core: pydantic models — Order, Position, Quote, Fund, OptionGreek, etc.
- core: Settings.from_env(), exceptions hierarchy
- 44 tests for core package

## [0.0.1-dev] — 2026-03-14

### Added
- Monorepo — 13 packages with per-package CLAUDE.md + AGENTS.md
- CI/CD — GitHub Actions (pytest, ruff, secrets check)
- SEBI compliance framework — rate limits, kill switch architecture, audit
- Infrastructure — nginx, systemd, WireGuard, fail2ban, deploy scripts
- Git-native bug tracking system
- Documentation — OpenAlgo API reference, tools guide, machine configs

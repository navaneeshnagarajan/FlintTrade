# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.6.0-dev] — 2026-03-16

### Added
- async OpenAlgo client (39 endpoints, rate limiting, retry, 44 tests)
- 5-layer safety system (OrderValidation, PositionLimits, PortfolioRisk, DailyPnL, KillSwitch)
- Per-exchange market hours (NFO/BFO 09:15-15:30, CDS 09:00-17:00, MCX 09:00-23:30, DELTA 24/7)
- OrderRouter wired to core + data (safety → audit → broker → audit)
- StrategyRunner + StrategyScheduler (async tick loop, deploy freeze guard, auto square-off)
- EMACrossover strategy (first concrete strategy, live sandbox tested)
- Telegram /kill wired to live engine — SEBI kill switch operational
- SEBI audit trail (JSONL append-only, /data/flinttrade/audit/, gzip rotation)
- DuckDB storage (ticks, trades, daily summaries)
- 633 tests passing across 12 packages (22 pre-existing failures in backtest-engine)

### Fixed
- OpenAlgo nested data key unwrapping (15 response parsers)
- pytest-asyncio missing from requirements
- DELTA exchange support added to safety layer

### Verified Live (Dhan Sandbox)
- ping → pong ✅
- funds → ₹99,90,877.25 available ✅
- place_order RELIANCE NSE → orderid 26031649063267 ✅
- Full E2E: EMACrossover signal → 5 safety layers → audit → Dhan → audit ✅
- Telegram /kill → cancel_all + close_position + stop_all + audit ✅

## [0.1.0-dev] — 2026-03-14

### Added
- Monorepo with 13 packages (core, engine, terminal, dashboard, ai, data, historical, screener, backtest, backtest-engine, integration, automation, ditto)
- OpenAlgo and OpenClaw as managed git subtrees in infra/
- Per-package CLAUDE.md and AGENTS.md for AI-assisted development
- CI/CD with GitHub Actions (pytest, ruff, secrets check)
- SEBI compliance framework (audit logging, rate limits, kill switch)
- Infrastructure: nginx, systemd, WireGuard, fail2ban, deploy scripts
- Bug tracking: git-native single-writer-per-file system
- Documentation: OpenAlgo API reference, tools guide, architecture, operations

# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [Semantic Versioning](https://semver.org/).

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

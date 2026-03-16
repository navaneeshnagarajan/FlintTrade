# Contributing to FlintTrade

## Quick Start

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
cp .env.example .env && make setup
git checkout dev && git pull
git checkout -b feature/{package}-{description}
# develop → test → commit → push → PR to dev
```

## DEVLOG (required for every change)

Append to DEVLOG.md:
```
## YYYY-MM-DD HH:MM IST | Machine | @username | IDE/Tool | AI Model/Agent | Branch | Summary
```

Examples:
```
## 2026-03-17 19:30 IST | nitro-i5-13420H-RTX5050 | @navaneeshnagarajan | VS Code | Claude Code (claude-opus-4-6) | feature/core-client | Built OpenAlgo REST client
## 2026-03-18 10:00 IST | mac-m4-16gb | @navaneeshnagarajan | Antigravity | Antigravity/Tester (gemini-2.5-pro) | feature/core-client | Wrote tests for OpenAlgo client
## 2026-03-18 16:00 IST | ubuntu-i3-9350KF-RX6600XT | @navaneeshnagarajan | Terminal | Manual | main | Deployed v0.1.0
```

## Versioning

FlintTrade follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`

| Version | When | Meaning |
|---|---|---|
| 0.1.0-dev | Now | Foundation only. No working code. |
| 0.1.0 | core package working | First functional release. OpenAlgo client connects and places orders. |
| 0.2.0 | engine + data working | Safety layers, order routing, tick capture, audit logs. |
| 0.3.0 | terminal UI working | Manual trading possible through FlintTrade. |
| 0.4.0 | historical + screener | Data pipeline, OI analysis, Greeks. |
| 0.5.0 | backtest-engine + backtest UI | Backtesting with equity curves and metrics. |
| 0.6.0 | integration | TradingView webhooks, ChartInk, visual flow builder. |
| 0.7.0 | ai | LLM chat, RAG, ML signals. |
| 0.8.0 | automation | Telegram bot, cron, OpenClaw, TOTP auto-login. |
| 0.9.0 | dashboard + ditto | Portfolio overview, multi-account. |
| 1.0.0 | All 13 packages working | First production release. Full platform. |

**Version bumps:**
- Update `VERSION` file
- Update `CHANGELOG.md`
- Tag: `git tag v0.1.0 && git push --tags`
- GitHub Release with changelog summary (no AI/chat references)

**Patch versions (0.1.1, 0.1.2):** bug fixes within a release.
**Minor versions (0.2.0, 0.3.0):** new package/feature added.
**Major version (1.0.0):** full platform ready for production.

## Rules

- Branch: `feature/{pkg}-{name}`, `fix/{pkg}-{name}`, `hotfix/{name}`
- Commits: `feat(terminal): add scalper panel` (conventional commits)
- Always squash and merge
- PRs to dev require 1 approval from @navaneeshnagarajan
- Run `make test && make lint` before pushing
- Never commit secrets (.env, keys, tokens)
- Never reference specific brokers in package code (use OpenAlgo abstraction)
- Never mention AI tools in commit messages, PR titles, or release notes

# Contributing to FlintTrade

## Quick Start

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
cp .env.example .env && make setup
```

> **Note:** During pre-release (v0.x), all work goes directly to main.
> Feature branches and PRs activate at v1.0.0.

## DEVLOG (required for every change)

Append to DEVLOG.md:
```
## YYYY-MM-DD HH:MM IST | Machine | @username | IDE/Tool | AI Model/Agent | Branch | Summary
```

Examples:
```
## 2026-03-17 19:30 IST | nitro-i5-13420H-RTX5050 | @your-username | VS Code | Claude Code (claude-opus-4-6) | main | Built OpenAlgo REST client
## 2026-03-18 10:00 IST | mac-dev | @your-username | Antigravity | Antigravity/Tester (gemini-2.5-pro) | feature/core-client | Wrote tests for OpenAlgo client
## 2026-03-18 16:00 IST | ubuntu-server | @your-username | Terminal | Manual | main | Deployed v0.1.0
```

## Versioning

FlintTrade follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`

| Version | Status | Meaning |
|---|---|---|
| 0.0.1-dev | Done | Foundation, monorepo structure, CI/CD |
| 0.1.0-alpha | **RELEASED** (2026-03-21) | 13 packages, 1,021 tests, 10 routes, full-stack wiring, 5 themes |
| 0.1.0-beta | Next (target March 30, 2026) | All packages verified end-to-end, live trading tested |
| 0.1.0-rc.1 | Planned | Release candidate — community feedback incorporated |
| 0.1.0 | Planned | First stable release |
| 0.2.0 | Planned | Mac + Antigravity test suite, OpenAlgo submodule updated |
| 1.0.0 | Planned | Full production release, all platforms tested |

**Pre-release progression:** `alpha` → `beta` → `rc.1` → stable
**Version bumps:**
- Update `VERSION` file
- Update `CHANGELOG.md`
- Tag: `git tag -a v0.1.0-alpha -m "Foundation complete"`
- GitHub Release with changelog summary

**Patch versions (0.1.1, 0.1.2):** bug fixes within a release.
**Minor versions (0.2.0, 0.3.0):** new package/feature added.
**Major version (1.0.0):** full platform ready for production.

## Pre-release phase (v0.x — current)

- All commits go directly to main
- No PRs required until v1.0.0
- DEVLOG entry required for every commit
- Never commit .env, secrets, or private data to any branch
- AI tools (Claude Code, Antigravity) may be credited in commit bodies.
  Never include private data (order IDs, account balances, API keys)
  in commits, DEVLOG, CHANGELOG, or any file tracked by git.

## Post-release (v1.0.0 onward)

- Branch: `feature/{pkg}-{name}`, `fix/{pkg}-{name}`, `hotfix/{name}`
- PRs to dev require 1 approval from a maintainer
- Always squash and merge
- Run `make test && make lint` before pushing
- Commits: `feat(terminal): add scalper panel` (conventional commits)
- Never commit secrets (.env, keys, tokens)
- Never reference specific brokers in package code (use OpenAlgo abstraction)

# Contributing to FlintTrade

## Quick Start

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
cp .env.example .env && make setup
```

> **Note:** During pre-release (v0.x), all work goes directly to main.
> Feature branches and PRs activate at v1.0.0.

## Versioning

FlintTrade follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`

| Version | Status | Meaning |
|---|---|---|
| 0.0.1-dev | Done | Foundation, monorepo structure, CI/CD |
| 0.1.0-alpha | **RELEASED** (2026-03-21) | 13 packages, 1,018 tests, 10 routes, full-stack wiring, 5 themes |
| 0.1.0-beta | Next (target March 30, 2026) | All packages verified end-to-end, live trading tested |
| 0.1.0-rc.1 | Planned | Release candidate — community feedback incorporated |
| 0.1.0 | Planned | First stable release |
| 0.2.0 | Planned | External data sources, advanced AI integrations |
| 1.0.0 | Planned | Full production release, all platforms tested |

**Pre-release progression:** `alpha` → `beta` → `rc.1` → stable
**Version bumps:**
- Update `VERSION` file
- Update `CHANGELOG.md` following [Keep a Changelog](https://keepachangelog.com/)
- Tag: `git tag -a v0.1.0-beta -m "Beta release"`
- GitHub Release with changelog summary

**Patch versions (0.1.1, 0.1.2):** bug fixes within a release.
**Minor versions (0.2.0, 0.3.0):** new package/feature added.
**Major version (1.0.0):** full platform ready for production.

## Commit Guidelines

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(terminal): add sector rotation widget
fix(engine): rate limiter not resetting after market close
docs: update SEBI compliance matrix with April 2026 timeline
test(screener): add option chain Greeks calculation tests
chore: clean up stale gitignore entries
```

### Commit message rules

1. **Type prefix required:** `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `perf`, `ci`
2. **Scope in parentheses:** package name or area — `(terminal)`, `(engine)`, `(docs)`, `(ci)`
3. **Imperative mood:** "add feature" not "added feature" or "adding feature"
4. **Body for context:** explain WHY, not just WHAT. Reference issue numbers if applicable.
5. **Detailed messages:** each commit should fully describe the change so `git log` tells the project story
6. **Stage specific files:** never use `git add -A` or `git add .` — stage only what you changed

### What NEVER goes in commits

- API keys, tokens, passwords, secrets
- Personal hostnames, IP addresses, VPN endpoints
- Broker account names, fund amounts, order IDs
- Machine hardware specs (use generic names: `dev-machine`, `test-machine`, `server`)
- Personal file paths (use `$HOME`, `~/`, relative paths)
- Conversation references, session IDs, memory content

## Changelog

All notable changes go in [CHANGELOG.md](CHANGELOG.md) following [Keep a Changelog](https://keepachangelog.com/):

```markdown
## [Unreleased]
### Added
- New feature description
### Changed
- What changed and why
### Fixed
- Bug fix description
```

The changelog replaces per-commit dev logs. Git history (`git log --oneline`) provides the detailed timeline.

## Bug Reports

When filing bugs (issues or `bugs/` tracker), you MAY include:

- OS name and version (e.g., "Ubuntu 24.04", "Windows 11", "macOS 15")
- Node.js / Python version
- Browser name and version
- Error messages and stack traces
- Steps to reproduce

You must NOT include:

- Personal IP addresses or hostnames
- Broker account details or API keys
- Fund balances, order IDs, or trade details
- Machine serial numbers or exact hardware specs beyond what's relevant

## Development Workflow

```
READ → PLAN → APPROVE → BUILD → VERIFY → TEST → UPDATE → COMMIT
```

1. **READ** — Start every session by reading `CLAUDE.md` and `PLAN.md`
2. **PLAN** — Pick next unchecked task. For non-trivial work, plan before coding
3. **APPROVE** — Get approval for architecture changes or new files
4. **BUILD** — Use TypeScript strict, shadcn/ui, Dockview panels. Check reference repos before writing from scratch
5. **VERIFY** — `tsc --noEmit` (zero errors), `npm run build` (clean), visual check
6. **TEST** — `npx vitest run` (36+ pass), `make test` (982+ pass), `ruff check`
7. **UPDATE** — Update `CHANGELOG.md` [Unreleased] section, mark task done in `PLAN.md`
8. **COMMIT** — Conventional commit, specific file staging, push, wait for CI green

## File Creation Rules

Before creating any new file:

1. **Check if it already exists** — search the repo and `.local/` for similar files
2. **If exists and needs update** — update it in place
3. **If exists but outdated** — archive old file to `.local/archive/`, create new one with same name, include all important content from old + new updates
4. **Never duplicate** — one source of truth per topic

## CI/CD

Every push triggers 3 GitHub Actions jobs:

| Job | What it checks |
|---|---|
| `python-tests` | pytest (982+ tests) + ruff lint |
| `node-tests` | tsc strict + vitest (36+) + production build |
| `secrets-check` | Scans for leaked API keys and credentials |

**CI must be green before any new work.** If CI fails, fix immediately.

## Pre-release Phase (v0.x — current)

- All commits go directly to main
- No PRs required until v1.0.0
- CHANGELOG entry required for notable changes
- Never commit `.env`, secrets, or private data to any branch
- AI tools (Claude Code, Antigravity) may be credited in commit bodies

## Post-release (v1.0.0 onward)

- Branch: `feature/{pkg}-{name}`, `fix/{pkg}-{name}`, `hotfix/{name}`
- PRs to dev require 1 approval from a maintainer
- Always squash and merge
- Run `make test && make lint` before pushing
- Never commit secrets (`.env`, keys, tokens)
- Never reference specific brokers in package code (use OpenAlgo abstraction)

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions will be licensed under [AGPL-3.0](LICENSE).

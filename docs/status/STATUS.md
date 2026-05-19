# FlintTrade Status Report

**Generated:** 2026-04-19
**Machine:** Windows 11 dev (MINGW64_NT-10.0-26200, x86_64 Msys)
**Branch:** `docs/status-report-2026-04-17`
**Commit at report time:** `93bbaa0059685c2739f54786c4b97f9cee8f3cb6` (tip of `main`)
**VERSION file:** `0.5.0-dev`

> Raw, unedited tool output. Paraphrased summaries are clearly marked.

---

## Build Status

### Terminal (React) — `npm run build` (from `packages/terminal/`)

Completed successfully in **1m 5s**. Output (tail of `npm run build`, ANSI colour codes preserved):

```
dist/assets/SectorMapWidget-BgMJ19iB.js                            33.51 kB │ gzip:  9.77 kB
dist/assets/vendor-framer-DYwImLW3.js                              37.89 kB │ gzip: 13.19 kB
dist/assets/TradeJournalTool-BZYaADib.js                           38.80 kB │ gzip:  9.36 kB
dist/assets/LabRoute-BuWAMNGT.js                                   40.29 kB │ gzip:  9.95 kB
dist/assets/AIRoute-b2REOUNs.js                                    54.21 kB │ gzip: 12.79 kB
dist/assets/OptionChainWidget-DPwZ8op5.js                          55.34 kB │ gzip: 15.97 kB
dist/assets/TerminalRoute-DGNCbt2Y.js                              57.47 kB │ gzip: 15.58 kB
dist/assets/vendor-d3-CaUv6BcM.js                                  62.21 kB │ gzip: 20.52 kB
dist/assets/MarketIntelligenceTool-C7Xsh9Eg.js                     62.45 kB │ gzip: 14.30 kB
dist/assets/ChartWidget-B9rllMw0.js                                65.93 kB │ gzip: 17.98 kB
dist/assets/AutomateRoute-UH_Le5tT.js                              69.84 kB │ gzip: 17.33 kB
dist/assets/vendor-router-l1ZUf8hE.js                              88.05 kB │ gzip: 29.86 kB
dist/assets/vendor-forms-CvuYfpoF.js                               96.47 kB │ gzip: 28.46 kB
dist/assets/vendor-tanstack-B78bI-XM.js                           105.69 kB │ gzip: 29.49 kB
dist/assets/SettingsRoute-bnED4vqZ.js                             117.31 kB │ gzip: 29.89 kB
dist/assets/index-BH63j7kt.js                                     152.31 kB │ gzip: 45.71 kB
dist/assets/vendor-radix-B3x9QZIY.js                              156.71 kB │ gzip: 48.11 kB
dist/assets/vendor-lwc-BPcIeFFx.js                                175.10 kB │ gzip: 56.16 kB
dist/assets/vendor-glide-mO0chtyh.js                              188.23 kB │ gzip: 64.24 kB
dist/assets/vendor-react-CUedMOOm.js                              194.42 kB │ gzip: 60.78 kB
dist/assets/vendor-recharts-Ebr4DA0B.js                           298.72 kB │ gzip: 67.33 kB
dist/assets/vendor-misc-Bj-Uam3O.js                               315.63 kB │ gzip: 96.04 kB
dist/assets/vendor-tremor-DMfsddv1.js                             333.72 kB │ gzip: 92.00 kB
dist/assets/vendor-dockview-DuYZKx8Y.js                           343.09 kB │ gzip: 63.20 kB

(!) Some chunks are larger than 300 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rollupOptions.output.manualChunks to improve chunking
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 1m 5s
```

**Verdict:** Build **PASSES**. 4 chunks exceed the 300 kB warning threshold (vendor-misc, vendor-tremor, vendor-dockview, vendor-recharts).

### Rust packages

Not built in this report — no automated build was run against `packages/tick-engine/` or `packages/desktop/src-tauri/`. Status UNKNOWN.

---

## Test Status

### Python (pytest)

Running via the command pattern from `Makefile` (because `make` is not installed on this Windows host):

```
python -m pytest packages/core/tests/ packages/engine/tests/ packages/gateway/tests/ \
  packages/screener/tests/ packages/data/tests/ packages/historical/tests/ \
  packages/indicators/tests/ packages/ai/tests/ packages/automation/tests/ \
  packages/backtest-engine/tests/ packages/integration/tests/ tests/ \
  --co -q --import-mode=importlib
```

**Collection summary (tail):**

```
ERROR packages/gateway/tests/test_registry.py
ERROR packages/gateway/tests/test_session.py
ERROR packages/gateway/tests/test_startup.py
!!!!!!!!!!!!!!!!!!! Interrupted: 6 errors during collection !!!!!!!!!!!!!!!!!!!
8348 tests collected, 6 errors in 43.03s
```

**Full test run (tail):**

```
INTERNALERROR> _duckdb.IOException: IO Error: Cannot open file
"%USERPROFILE%\.flinttrade\security.db": The process cannot access the file
because it is being used by another process.
INTERNALERROR>
INTERNALERROR> File is already open in another Python process
```

**Verdict:** Python test suite **DID NOT RUN TO COMPLETION** on this machine.

- Collection reports **8,348 tests collected, 6 errors during collection** (import failures in `packages/gateway/tests/`).
- Full run aborted with a `pytest` INTERNALERROR caused by a DuckDB file lock on `~/.flinttrade/security.db` held by another Python process on the same host.
- Running Python is **3.14.3**, while `pyproject.toml` declares `target-version = "py312"` — version drift relative to project intent.

Pass/fail counts: **UNKNOWN — needs manual verification** after stopping the conflicting Python process or moving the `security.db` file.

### Terminal (Vitest)

```
cd packages/terminal && npx vitest run
```

**First attempt:** Crashed mid-run with:

```
Error: Channel closed
  ❯ target.send node:internal/child_process:753:16
  ❯ ProcessWorker.send node_modules/tinypool/dist/index.js:140:41
Serialized Error: { code: 'ERR_IPC_CHANNEL_CLOSED' }
```

This is a tinypool/vitest worker crash on Windows, not a test assertion failure.

**Second attempt:** Re-ran with `--reporter=default` piped through grep; output incomplete at report-writing time. See trailing note below.

Pass/fail counts: **UNKNOWN — needs manual verification** (re-run `npx vitest run` directly, no pipe, in a fresh shell).

### Test file inventory (static count)

- Vitest test files (`*.test.ts` / `*.test.tsx`): **259**
- Pytest test files (`test_*.py`): **272**

---

## Service Status

```
$ make status
/usr/bin/bash: line 1: make: command not found
```

`make` is not installed on this Windows machine. No service status captured.

OpenAlgo probe:

```
$ curl -s -m 2 http://127.0.0.1:5000/
(no response within 2s)
```

**OpenAlgo does not appear to be running on this host at report time.**

---

## Package Inventory

### Counts

- `find packages -name "package.json" -not -path "*/node_modules/*" | wc -l` → **2** (`packages/desktop/package.json`, `packages/terminal/package.json`)
- `find packages -name "pyproject.toml" | wc -l` → **13**
- `find packages -name "Cargo.toml" -not -path "*/target/*"` → **2** (`packages/desktop/src-tauri/Cargo.toml`, `packages/tick-engine/Cargo.toml`)
- `find packages -name "*.tsx" -not -path "*/node_modules/*" -not -path "*/dist/*" | wc -l` → **541**
- `ls packages/` (16 directories):

```
ai
automation
backtest-engine
chrome-extension
core
data
desktop
ditto
engine
gateway
historical
indicators
integration
screener
terminal
tick-engine
```

### Names & versions (extracted from each manifest)

| Directory | Manifest name | Version |
|---|---|---|
| `packages/ai` | `flint-ai` | 0.5.0 |
| `packages/automation` | `flint-automation` | 0.5.0 |
| `packages/backtest-engine` | `flint-backtest-engine` | 0.5.0 |
| `packages/chrome-extension` | `FlintTrade` (manifest.json) | 0.2.0 |
| `packages/core` | `flint-core` | 0.5.0 |
| `packages/data` | `flint-data` | 0.5.0 |
| `packages/desktop` | `@flinttrade/desktop` (npm) / `flinttrade-desktop` (cargo) | 0.1.0 / 0.5.0 |
| `packages/ditto` | `flint-ditto` | 0.5.0 |
| `packages/engine` | `flint-engine` | 0.5.0 |
| `packages/gateway` | `flint-gateway` | 0.5.0 |
| `packages/historical` | `flint-historical` | 0.5.0 |
| `packages/indicators` | `flint-indicators` | 0.5.0 |
| `packages/integration` | `flint-integration` | 0.5.0 |
| `packages/screener` | `flint-screener` | 0.5.0 |
| `packages/terminal` | `flint-terminal` | **0.3.0** (drift vs root `0.5.0-dev`) |
| `packages/tick-engine` | `tick-engine` (pyproject) / `tick-engine` (cargo) | 0.1.0 / 0.2.0 |

See `docs/status/PACKAGES.md` for fuller detail.

---

## Recent Commits (last 20)

```
93bbaa0 chore: bump algomirror + openclaw submodules to upstream tip
2741cad feat: OpenAlgo parity wave 5 — complete (314 tests across 22 items)
a0c0f29 feat: OpenAlgo parity wave 4 — 449 tests across 5 sub-waves
19a1e33 feat: OpenAlgo parity wave 3 — security + smart routing (73 tests)
8d9a38f feat: OpenAlgo parity wave 2 — analytics + orders + infra (347 tests)
3534062 feat: OpenAlgo v2.0.0.4 parity — 5 new modules, submodule updated
4de27ce docs: align .env.example with actual .env structure
1d3aef5 docs: update README badges and description to current state
d0138f2 feat: production-readiness final pass
4024c0d refactor: production-readiness pass — imports, a11y, types, lint
8e9b43e fix: full codebase audit — 27 findings across 6 domains
3a6c359 fix: full codebase audit fixes
98515af feat(ai): Phase 7 — Crawl4AI integration client
7d8650b feat: Phase 6 — pyproject.toml per package + uv workspace
2056e12 feat(terminal): Phase 4 — ticker system store persistence + settings integration
5853aa9 feat(terminal): Phase 5 — glass polish across all routes
26d027f fix(terminal): audit fixes for Command Palette
6561420 feat(terminal): Phase 2 — Unified Search + Command Palette
b86c2e9 fix(ci): resolve 5 test failures from Phase 1 push
3670407 feat: Phase 1 — Glass Adaptive shell redesign
```

---

## Uncommitted Changes

At the time this branch was created (before any files in `docs/status/` were written):

```
On branch main
Your branch is ahead of 'origin/main' by 1 commit.
  (use "git push" to publish your local commits)

nothing to commit, working tree clean
```

Note: `main` was ahead of `origin/main` by 1 commit (`93bbaa0`, the submodule bump) at report time.

---

## Recent Changelog (head of CHANGELOG.md)

```
# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased] — v0.5.0-dev

### Added — Features (Waves 1-9)
- Signals pipeline: real-time signal generation, scoring, and routing to order engine
- MCX commodity support: symbol normalisation, market hours, lot sizes (mcxLots.ts + 46 tests)
- Mutual Funds module: MutualFundTab in /invest with AMFI NAV lookup, SIP calculator
- WhatsApp notification channel alongside existing Telegram bot
- ExpiryTrack: historical expired options tracking
- Pine Script editor: browser-based Pine-to-Python transpiler
- Chrome extension: quick order entry and watchlist from any browser tab
- Tauri desktop shell: native window wrapper for the React terminal
- Multi-user support: role-based access (admin/trader/viewer) with JWT claims
- IPO Tracker
- FinRL reinforcement learning
- OpenClaw bridge

### Added — Features (Waves 10-23)
- Multi-agent AI team: MiroFish + TradingAgents architecture
- Risk debate, Ensemble selector, Hyperopt optimiser, Fundamental screener
- FII/DII tracker, RRG calculator, Portfolio backtester
- Bracket orders, Order flow inference
- Alert trigger log, Activity log

### Added — Wiring & Mode System
- Server-side order safety proxy
- Unified mode system: Explore / Practice / Live
- useModeData hook, MockDataEngine
- CSRF token middleware
- Mode reset on disconnect
- Persona-aware setup wizard
- ModeIndicator in TopBar, Practice Settings, DemoChoice overlay
- GoalTab wired into /invest
- JWT secret persistence, SEBI disclaimer banner
```

---

## Notes / Discrepancies vs documented state

1. **Python version drift:** Running Python is 3.14.3; `pyproject.toml` targets 3.12. This likely explains pytest plugin edge cases (see `INTERNALERROR` trace from pluggy).
2. **Terminal package version drift:** `packages/terminal/package.json` is at `0.3.0` while the repo `VERSION` file says `0.5.0-dev` and every Python package is `0.5.0`.
3. **`make` unavailable on Windows host:** `make test` / `make status` from CLAUDE.md do not work as-is here. Direct `pytest` / `npx vitest` invocations must be used.
4. **DuckDB file lock:** A stray Python process (PID 26840 at report time) is holding `~/.flinttrade/security.db` open and blocking the pytest run. Terminate it before re-running tests.
5. **Widget count drift vs CLAUDE.md:** CLAUDE.md says "30 widgets" in one place and "83 widgets" in another; the actual registry in `widgetFactory.tsx` references 80+ widgets, and `ls packages/terminal/src/widgets/{trading,analysis,utility}/` enumerates **82 widget directories** (22 trading + 38 analysis + 22 utility). See `docs/status/WIDGETS.md`.
6. **TSX file count (541)** is much higher than widget count because every widget is a directory containing `<Name>Widget.tsx` plus supporting subcomponents, settings panels, and test files.

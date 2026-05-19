# FlintTrade Packages

Per-package inventory derived by reading each manifest (`pyproject.toml`, `package.json`, `Cargo.toml`, `manifest.json`) and each package's `README.md`. **16 packages** total.

All counts are raw outputs of `find` / manifest parsing on the working tree at commit `93bbaa0`. Test pass-rate columns are marked UNKNOWN where the full test run did not finish on this machine (see `STATUS.md`).

| Package | Manifest name | Version | Language | Purpose (from README) | Direct deps | Source files | Test files | Status |
|---|---|---|---|---|---|---|---|---|
| `packages/ai` | `flint-ai` | 0.5.1 | Python | LLM chat, RAG, ML signals, news sentiment, autonomous trading | 14 (incl. `flint-core`, `flint-indicators`) | 41 | 32 | working (tests UNKNOWN — run aborted) |
| `packages/automation` | `flint-automation` | 0.5.1 | Python | Cron scheduler, Telegram bot, OpenClaw agent bridge, post-market analysis | 7 | 25 | 10 | working (tests UNKNOWN) |
| `packages/backtest-engine` | `flint-backtest-engine` | 0.5.1 | Python | Event-driven simulation engine, 101 strategies, VectorBTRunner sweeps, walk-forward, Monte Carlo | 10 | 123 | 26 | working (tests UNKNOWN) |
| `packages/chrome-extension` | `FlintTrade` (MV3 `manifest.json`) | 0.2.0 | JavaScript (vanilla) | Quick trade from any webpage — companion browser extension (LE/LX/SE/SX buttons) | 0 (no bundler) | 3 JS/HTML + 1 CSS | 0 | experimental |
| `packages/core` | `flint-core` | 0.5.1 | Python | Framework, CLI, OpenAlgo client, config, models, logger, Flask app server (90+ routes), admin, security, monitoring | 16 | 50 | 46 | working (tests UNKNOWN) |
| `packages/data` | `flint-data` | 0.5.1 | Python | Real-time tick capture, WS storage, trade logs, SEBI audit trails, order flow, P&L, tax reports | 7 (incl. `flint-core`) | 27 | 18 | working (tests UNKNOWN) |
| `packages/desktop` | `@flinttrade/desktop` (npm) / `flinttrade-desktop` (cargo) | 0.1.0 (npm) / 0.5.1 (cargo) | TypeScript + Rust (Tauri v2) | Native desktop wrapper for the terminal via Tauri v2 | 1 npm + 2 cargo | 6 | 0 | experimental (scaffold only) |
| `packages/ditto` | `flint-ditto` | 0.5.1 | Python | Multi-broker, multi-account trade orchestration, position mirroring, allocation modes | 6 | 7 | 5 | working (tests UNKNOWN) |
| `packages/engine` | `flint-engine` | 0.5.1 | Python | Strategy execution, order routing, 5-layer safety, kill switches, scheduler, action center, sandbox | 6 (incl. `flint-core`, `flint-data`) | 40 | 37 | working (tests UNKNOWN) |
| `packages/gateway` | `flint-gateway` | 0.5.1 | Python | Direct broker connections (33 brokers), adapter pattern, encrypted credentials, WS bridge | 5 | 29 | 16 | **broken on this machine** — `6 errors during collection` in gateway tests on Python 3.14.3 |
| `packages/historical` | `flint-historical` | 0.5.1 | Python | OHLCV downloader, free NSE data (OpenChart/yfinance/jugaad), DuckDB pipeline, expiry manager | 6 | 23 | 17 | working (tests UNKNOWN) |
| `packages/indicators` | `flint-indicators` | 0.5.1 | Python | Technical analysis — TA-Lib batch (150+), Numba streaming, Pine Script conversion | 3 (TA-Lib optional) | 16 | 14 | working (tests UNKNOWN) |
| `packages/integration` | `flint-integration` | 0.5.1 | Python | TradingView webhooks, ChartInk alerts, custom webhooks, visual flow builder (54 flow nodes), alerter | 5 | 12 | 9 | working (tests UNKNOWN) |
| `packages/screener` | `flint-screener` | 0.5.1 | Python | Market scanner, OI analysis, PCR, max pain, portfolio Greeks, GEX, IV smile, vol surface, straddle P&L, RRG, order flow | 7 | 56 | 40 | working (tests UNKNOWN) |
| `packages/terminal` | `flint-terminal` | **0.3.0** | TypeScript (React 19 + Vite 6) | Single React app (port 5173), 13 routes, Dockview v5.1 widget-composable workspace, Zustand + Jotai + TanStack Query | 33 runtime + 21 dev | 447 | **259** (inline `*.test.ts(x)`; `packages/terminal/tests/` is empty) | **build PASSES**; vitest run crashed with IPC error (Node worker), pass/fail UNKNOWN |
| `packages/tick-engine` | `tick-engine` (pyproject) / `tick-engine` (cargo) | 0.1.0 (py) / 0.2.0 (rust) | Rust (PyO3 bindings) | High-performance tick processing engine — Rust core with Python bindings; TickSimulator, EMA crossover, Sharpe/drawdown metrics | 0 Python / PyO3 + rayon + serde + chrono in Rust | 10 | 2 | experimental (Rust build not exercised in this report) |

## Package version drift

- **All Python packages:** `0.5.1`
- **Repo-level `VERSION`:** `0.5.1`
- **`packages/terminal/package.json`:** `0.5.1`
- **`packages/desktop` (npm):** `0.1.0` (independent versioning — npm shell only)
- **`packages/desktop` (cargo):** `0.5.1`
- **`packages/chrome-extension/manifest.json`:** `0.2.0`
- **`packages/tick-engine/pyproject.toml`:** `0.1.0`
- **`packages/tick-engine/Cargo.toml`:** `0.2.0`

If the repository intends a monorepo-wide SemVer, the terminal, desktop (npm side), chrome extension, and tick-engine all need a bump.

## Status legend

- **working**: manifest parses, README present, source compiles at least in CI history (per commits), last commit touched it recently.
- **experimental**: scaffolded or narrowly-used; not part of the main test matrix.
- **broken**: something observably fails today on this machine (see STATUS.md for details).

## Test status caveat

This report could not obtain authoritative pass/fail counts because:
1. `pytest` aborted with a DuckDB file-lock INTERNALERROR during the full run.
2. `npx vitest run` crashed once with `ERR_IPC_CHANNEL_CLOSED` (Windows tinypool worker), and a repeat run did not flush output before the report was written.

Per-package pass-rate therefore is **UNKNOWN — needs manual verification**. Static file counts in the "Test files" column come from `find packages/<pkg>/tests -name "test_*.py" | wc -l` and are accurate.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FlintTrade is an open-source self-hosted market workflow workspace. It runs **its own native backend first** and treats OpenAlgo as one optional (bridge) broker adapter. Monorepo of **18 package surfaces** in a fat-core 4-way nest: 13 Python, 1 Rust/PyO3 (`ticks`), 1 shared TypeScript design-system, 1 React terminal, 1 Tauri desktop shell, 1 Next.js site. Licensed AGPL-3.0. Target Python `>=3.12,<3.14`, Node `>=22`. The full architectural reference is [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); contributor mechanics are [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md); CI is [docs/CI.md](docs/CI.md); the live roadmap is [PLAN.md](PLAN.md). Read those before non-trivial work.

Version: **v0.6.0-beta** (beta restructure; not production-ready). Python tooling is **uv** (workspace lockfile `uv.lock`); JS is **pnpm** (workspace lockfile `pnpm-lock.yaml`).

## Commands

The Makefile is the canonical entry point — `make help` lists every target. Most-used:

```bash
# Tests (Python via uv; flat-package layout needs --import-mode=importlib, which the Makefile sets)
make test                                                          # all pytest
make test-fast                                                     # pytest, stop on first failure
uv run pytest packages/<group>/<pkg>/tests/ -v --import-mode=importlib              # single package
uv run pytest packages/core/core/tests/test_app.py::test_name -v --import-mode=importlib   # single test
cd packages/apps/terminal && npx vitest run                        # all Vitest
cd packages/apps/terminal && npx vitest run src/widgets/path/foo.test.tsx
cd packages/apps/terminal && npx vitest run -t "places a market order"

# Lint / typecheck
make lint                                                          # ruff over packages/ tests/
cd packages/apps/terminal && npm run typecheck                     # tsc --noEmit (strict)

# Build
cd packages/apps/terminal && npm run build                         # tsc --noEmit + vite build
cd packages/core/ticks && cargo build --release                    # Rust/PyO3 wheel
make desktop-build                                                 # native desktop installers (frontend + backend sidecar + Tauri bundle)

# Dev / run
make dev                                                           # terminal dev server + backend
make desktop-dev                                                  # run the native desktop app in dev (builds the sidecar first)
make start                                                         # FlintTrade backend (port 5100)
make docker-up | docker-down | docker-build
make full-check                                                    # tests + lint + typecheck snapshot
```

Dependencies are installed with `uv sync` (Python, incl. the dev group) and `pnpm install` (JS workspace: terminal + site + design-system).

## Architecture (essentials)

**Native backend first; OpenAlgo optional.** The terminal talks to the FlintTrade backend (port 5100) for everything, and to OpenAlgo (port 5000, external) only via the OpenAlgo **bridge adapter** for broker/market data, plus an OpenAlgo WebSocket on 8765. All three are proxied through Vite in dev:

| Dev proxy prefix | Target |
|---|---|
| `/api`     | `http://127.0.0.1:5000` (OpenAlgo) |
| `/ft-api`  | `http://127.0.0.1:5100` (FlintTrade backend) |
| `/ws`      | `ws://127.0.0.1:8765` (OpenAlgo WebSocket) |

**WSGI prefix strip.** The backend lives in [packages/core/core/src/flinttrade_core/app.py](packages/core/core/src/flinttrade_core/app.py) and binds to 5100. Middleware strips `/ft-api` before URL dispatch, so a blueprint registered at `url_prefix="/v1"` answers external `/ft-api/v1/…`. Note: most `ftApi.*` callers use the **`/api/v1`** prefix (served by the backend too) — match the prefix the frontend uses; **never double-prefix**. A blueprint at `/v1/X` that the frontend calls at `/api/v1/X` will 404 (the recurring wiring bug).

**Gated execution (the headline feature — do not bypass).** Every reachable live order traverses, in order: `SafetySystem` **L1–L5** (order validation → position limits → portfolio risk → daily P&L → kill switch) → `gate_order()` (mints a one-shot HMAC `SafetyContext` bound to a selector-bound principal) → `BrokerRouter` (re-HMAC + field-by-field match + account ACL + one-shot gate consume) → broker adapter (module-private `_ROUTER_TOKEN`). The **OpenAlgo bridge adapter** is the live-tested adapter. The four founder-broker **native adapters** (Dhan, Upstox, Kotak Neo, IndMoney) carry the full doc-grounded surface (orders + GTT/super/conditional + reads + market data + WS + reconcile) and stay dormant until SDK attestation + vault credentials — the remaining gate is live-credential testing, not implementation. New gated write verbs are routed table-driven via `BrokerRouter.execute_gated` (minted by `gate_broker_write`). If you wire a new order path (basket, webhook, agent, mirror, or a new verb), it MUST mint a `SafetyContext` through `gate_order`/`gate_broker_write` → `BrokerRouter` — `gateway/tests/test_no_legacy_order_path.py` is the grep guard.

**Three-mode state machine** (Explore / Practice / Live) enforced server-side by [packages/services/engine/src/flinttrade_engine/mode_guard.py](packages/services/engine/src/flinttrade_engine/mode_guard.py). Each transition mints a new JWT with the new `mode` claim and revokes the old `jti`. A live order on a Practice JWT returns `MODE_NOT_ALLOWED`; Practice routes to the native SandboxEngine (not OpenAlgo).

**Frontend state boundaries** (do not mix):
- **Jotai atoms** — WebSocket-driven per-instrument LTP/quote/depth and derived values.
- **TanStack Query** — REST responses (positions, orders, holdings, funds, option chain).
- **Zustand** — derived/UI state only (connection, layout, settings mirror, aggregated P&L, mode).

Each data shape enters through one path only. Duplicate it and you guarantee a bug.

**Configuration is two tiers:**
1. `.env` (repo root, never committed) — non-secret infra only: `OPENALGO_HOST`, `OPENALGO_PORT`, `OPENALGO_API_KEY`, `OPENALGO_WS_PORT`. Secrets (master password, JWT secret, API-key pepper, safety-gate secret) are file-backed + hardened under `~/.flinttrade/`, never in `.env`.
2. `workspace.json` — user preferences (storage paths, enabled modules, UI, LLM, notifications, broker routing/ACLs). Read via `flinttrade_core.config.FlintTradeConfig`. Native-adapter broker credentials live in the encrypted vault (`gateway/credentials.py`, Fernet + per-row DEK), never plaintext.

## Package map (where things live — paths are `packages/<group>/<pkg>/src/flinttrade_<pkg>/`)

| Package | Group | Lang | Role |
|---|---|---|---|
| `core` | core | Py | Flask app + blueprint registration, OpenAlgo client (45+ endpoints), config, workspace, auth/JWT, models, WSGI strip |
| `data` | core | Py | Tick capture, audit log (hash chain), trade logger, sandbox state, DuckDB/QuestDB |
| `historical` | core | Py | OHLCV downloader (OpenChart/yfinance), DuckDB/Parquet pipeline, expiry tracker |
| `indicators` | core | Py | TA-Lib (batch) + Numba (streaming) + Pine Script convert |
| `ticks` | core | Rust+PyO3 | Hot-path tick processor (was `tick-engine`) |
| `design-system` | core | TS | Shared tokens, brand primitives, layer scale, motion, React UI kit |
| `engine` | services | Py | 5-layer `SafetySystem`, `gate_order`, order router, scheduler, mode guard, sandbox executor, strategies |
| `screener` | services | Py | Option chain, OI/PCR/max-pain, IV smile, futures quadrant, portfolio Greeks, RRG, FII/DII |
| `backtest` | services | Py | Event-driven simulator, 94 templates, walk-forward, Monte Carlo, VectorBT |
| `ai` | services | Py | Multi-provider LLM client, ChromaDB RAG, ML signals, multi-agent team, sentiment, OpenClaw bridge |
| `ditto` | services | Py | Multi-account mirror, margin calc, trailing SL, risk manager (AlgoMirror patterns reimplemented natively) |
| `automation` | services | Py | Cron, Telegram bot (kill switch), post-market analysis, voice orders |
| `journal` | services | Py | Trade journal, trade logging, execution analytics, realised P&L |
| `gateway` | integrations | Py | Native broker gateway — `BrokerAdapter` protocol, `BrokerRouter`, `BROKER_CATALOG` (32 brokers), encrypted credential vault, WS bridge, OpenAlgo bridge adapter |
| `webhooks` | integrations | Py | TradingView/ChartInk/custom webhooks, flow builder, n8n + WhatsApp bridges |
| `terminal` | apps | TS/React | SPA: Dockview workspace, 95 widgets, routes — single source of truth for UI |
| `desktop` | apps | TS/Rust | Tauri 2 native shell — bundles the PyInstaller-frozen backend sidecar + built terminal into one cross-OS installer (Linux/Windows/macOS), served from a single loopback origin |
| `site` | apps | TS/Next | Next.js + fumadocs public site, generated docs, docs MCP |

(`chrome-extension` was dropped in the v0.6.0 restructure; the Tauri `desktop` shell was re-added and shipped in v0.6.0-beta — see [docs/DESKTOP.md](docs/DESKTOP.md).)

## House rules that bite

These cause real failures, not just style nits:

- **Python**: PEP 8 + `ruff` (line length 120). Type hints on every public function (`list[int]`, `X | None`). Google-style docstrings. **Absolute imports only** (`flinttrade_<pkg>....`); relative imports break the flat layout under `--import-mode=importlib`. Run `ruff check` before claiming done — `F821`/`F401` catch the import-NameError class that import-only checks miss.
- **TypeScript**: strict mode is non-negotiable — no `any`, no `@ts-ignore`, no `@ts-expect-error` without an issue link. All new code in `.ts`/`.tsx`. Functional components and hooks only. Use shadcn/ui primitives (never raw `<button>`/`<input>`/`<dialog>`) and lucide-react icons. Path alias `@` → `packages/apps/terminal/src/` (kept in sync across `tsconfig.json`, `vite.config.ts`, `vitest.config.ts`).
- **No mock/placeholder/fake data in any UI** without an explicit `isExplore`/`isConnected` guard + visible "Demo data" affordance. A widget that renders fabricated prices and lets a click place a live order is a safety bug.
- **British English** in docstrings, comments, and **user-visible strings** (behaviour, organise, colour, centred…). Code identifiers keep upstream spelling. Indian market terms always win: "expiry" (never "expiration"), "lakh", "crore", "scrip".
- **Conventional Commits** are mandatory (`feat|fix|docs|test|chore|refactor|perf|ci(scope): …`). Scope is the package name or focus area.
- **Never** `git add -A` / `git add .` — stage explicitly. Never commit `.env`, API keys, broker account names, fund amounts, order IDs, or personal hostnames/IPs. Never push without explicit permission, and never with `--no-verify` or `dangerouslySkipPermissions`.
- Every new widget is a Dockview panel registered in [packages/apps/terminal/src/layout/widgetFactory.tsx](packages/apps/terminal/src/layout/widgetFactory.tsx) with a co-located `<Name>.test.tsx`.
- **Don't touch OpenAlgo's SQLite directly** — concurrent access corrupts it. Go through the REST API; `flinttrade_core.openalgo_client` is the only path in.
- **Port 5100 is FlintTrade's backend, not OpenAlgo.** OpenAlgo uses 5000-5009. Don't propose consolidating.
- **no-overscope**: personal-use open-source (operator == user == data principal). Don't add DPDPA / §65B / CERT-In / RBI / vendor-SEBI compliance ceremony. Only AGPL licence compliance + OpenAlgo-parity observability apply.
- The pytest harness registers three markers (`unit`, `integration`, `slow`) under `--strict-markers` — a typo'd marker fails CI. Tag new tests.

## OpenAlgo quirks to work around

Apply to anyone touching the order/data path (the OpenAlgo bridge adapter):

1. Sandbox sends real orders for some brokers — verify isolation before testing live-ish flows.
2. `closeposition` ignores strategy — track positions per-strategy yourself.
3. WebSocket drops without heartbeat — `openalgo_client.py` implements ping/pong; preserve it.
4. PNL is wrong for some brokers — compute locally from `tradebook`.
5. MCX symbol format is inconsistent — normalise via `flinttrade_core.symbol_utils`.

## CI shape (so you know what's running)

`test.yml` runs seven parallel Ubuntu jobs on push to `main`/`dev` and non-draft PRs: `python-tests`, `node-core-tests`, three `node-widget-tests-*` shards (1, 2a, 2b, 3), and `secrets-check` (gitleaks). Doc-only commits skip the matrix via `paths-ignore`. `concurrency: cancel-in-progress: true` means a follow-up push cancels the previous run. Per-push macOS/Windows jobs are a regression — cross-platform belongs in the weekly `nightly-cross-platform.yml`. Other workflows: `supply-chain.yml`, `refresh-vuln-snapshot.yml`, `site.yml`, `status-report.yml`. To debug: `gh run view <id> --log-failed`.

## External test deps (not bundled)

OpenAlgo and OpenClaw are external services (formerly submodules). For local testing, `scripts/setup-test-deps.sh` clones them into `.local/external/` (gitignored). AlgoMirror is intentionally absent: its patterns are reimplemented natively in `packages/services/ditto/` (our own code).

## Working style (this repo)

- **Review pipeline:** claude (ultracode multi-agent panels) → maintainer. Codex is retired from the loop.
- **Spec-first:** design work lives in `.local/specs/<area>/` with a `DESIGN_LOG.md`; `changelog.md` is for **shipped** code only.
- After any build/commit wave, run a full multi-agent audit before declaring done. Fix everything, then re-audit.
- `AGENTS.md` carries the full agent/tooling workflow; `PLAN.md` is the living roadmap.

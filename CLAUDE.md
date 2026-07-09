# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FlintTrade is open-source, self-hosted trading software for manual, automated, algorithmic, and AI-assisted workflows. It runs **its own native backend first** and treats OpenAlgo as one optional (bridge) broker adapter. Monorepo of **18 package surfaces** in a fat-core 4-way nest: 13 Python, 1 Rust/PyO3 (`ticks`), 1 shared TypeScript design-system, 1 React terminal, 1 Tauri desktop shell, 1 Next.js site. Licensed AGPL-3.0. Target Python `>=3.12` (no upper bound; the repo currently runs 3.14), Node `>=22`. The full architectural reference is [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); contributor mechanics are [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md); CI is [docs/CI.md](docs/CI.md); the live roadmap is [PLAN.md](PLAN.md). Read those before non-trivial work.

Version: **v0.6.0-beta.1** (beta restructure; not production-ready). Python tooling is **uv** (workspace lockfile `uv.lock`); JS is **pnpm** (workspace lockfile `pnpm-lock.yaml`).

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

Dependencies are installed with `uv sync` (Python, incl. the dev group) and `pnpm install` (JS workspace: terminal + site + design-system + desktop).

## Architecture (essentials)

**Native backend first; OpenAlgo optional.** The terminal talks to the FlintTrade backend (port 5100) for everything, and to OpenAlgo (port 5000, external) only via the OpenAlgo **bridge adapter** for broker/market data, plus an OpenAlgo WebSocket on 8765. All three are proxied through Vite in dev:

| Dev proxy prefix | Target |
|---|---|
| `/api`     | `http://127.0.0.1:5000` (OpenAlgo) |
| `/ft-api`  | `http://127.0.0.1:5100` (FlintTrade backend) |
| `/ws`      | `ws://127.0.0.1:8765` (OpenAlgo WebSocket) |

**WSGI prefix strip.** The backend lives in [packages/core/core/src/flinttrade_core/app.py](packages/core/core/src/flinttrade_core/app.py) and binds to 5100. Middleware strips `/ft-api` before URL dispatch, so a blueprint registered at `url_prefix="/v1"` answers external `/ft-api/v1/…`. Note: most `ftApi.*` callers use the **`/api/v1`** prefix (served by the backend too) — match the prefix the frontend uses; **never double-prefix**. A blueprint at `/v1/X` that the frontend calls at `/api/v1/X` will 404 (the recurring wiring bug).

**Gated execution (the headline feature — do not bypass).** Every reachable live order traverses, in order: `SafetySystem` **L1–L5** (order validation → position limits → portfolio risk → daily P&L → kill switch) → `gate_order()` (mints a one-shot HMAC `SafetyContext` bound to a selector-bound principal) → `BrokerRouter` (re-HMAC + field-by-field match + account ACL + one-shot gate consume) → broker adapter (module-private `_ROUTER_TOKEN`). The **OpenAlgo bridge adapter** is the community-tested primary path. The five founder-broker **native adapters** (Dhan, Upstox, Kotak Neo, INDmoney, Groww) are doc-grounded and mock-tested but their write surfaces are deliberately asymmetric (Dhan: full incl. forever/super/conditional; Upstox: GTT-via-variety + multi/cancel-all/exit-all/convert; Kotak Neo: place/modify/cancel only; INDmoney: trio + smart-cancel; Groww: regular/smart REST paths pending promotion) — `test_no_legacy_order_path.py` pins exactly this. They stay dormant until SDK attestation + vault credentials; the activation plumbing now exists (Phase 1) — the credential-replay login step (`flinttrade_gateway/native_login.py`: vault → `adapter.login()` → registry session), the in-app credential-capture UX (Settings → Brokers via `native_account_routes.py` `/api/v1/native/*`), the OAuth connect flow, and daily session refresh (`native_rotation.py`). Broker-management writes require the operator's session JWT (G9); the PIN is a re-auth factor over a live session, never a session-minting one (D6). Native connectability is evidence-gated: Dhan, Upstox, and INDmoney are enabled after live login/read verification; Kotak Neo remains disabled until a live TOTP/MPIN adapter login/read probe passes, and Groww (API-key session approved; account reads + margin checks verified) remains disabled until market-data/API permission, static-IP setup, and order-safety evidence clear. New gated write verbs are routed table-driven via `BrokerRouter.execute_gated` (minted by `gate_broker_write`). If you wire a new order path (basket, webhook, agent, mirror, or a new verb), it MUST mint a `SafetyContext` through `gate_order`/`gate_broker_write` → `BrokerRouter` — `gateway/tests/test_no_legacy_order_path.py` is the grep guard.

**Three-mode state machine** (Explore / Practice / Live) enforced server-side by [packages/services/engine/src/flinttrade_engine/mode_guard.py](packages/services/engine/src/flinttrade_engine/mode_guard.py). Transitions mint a new JWT with the new `mode` claim and revoke the old `jti` (minting/revocation lives in core `auth_routes.py`; `mode_guard.py` enforces the claim per request). A live order on a Practice JWT is rejected 403 with code `mode_blocked`/`practice_unsupported`; Practice routes to the native SandboxEngine (not OpenAlgo).

**Frontend state boundaries** (do not mix):
- **Jotai atoms** — WebSocket-driven per-instrument LTP/quote/depth and derived values.
- **TanStack Query** — REST responses (positions, orders, holdings, funds, option chain).
- **Zustand** — derived/UI state only (connection, layout, settings mirror, aggregated P&L, mode).

Each data shape enters through one path only. Duplicate it and you guarantee a bug.

**Configuration is two tiers:**
1. `.env` (repo root, never committed) — non-secret infra only: `OPENALGO_HOST`, `OPENALGO_PORT`, `OPENALGO_API_KEY`, `OPENALGO_WS_PORT`. Secrets (master password, JWT secret, API-key pepper, safety-gate secret) are file-backed + hardened under the workspace dir, never in `.env`. The workspace dir is platform-specific: `~/.flinttrade/` on Linux, `~/Library/Application Support/flinttrade/` on macOS, `%APPDATA%/flinttrade/` on Windows (override: `FLINTTRADE_WORKSPACE_DIR`/`FLINTTRADE_HOME`).
2. `workspace.json` — user preferences (storage paths, enabled modules, UI, LLM, notifications, broker routing/ACLs). Read via `flinttrade_core.config.FlintTradeConfig`. Native-adapter broker credentials live in the encrypted vault (`gateway/credentials.py`, Fernet with a per-row random salt + PBKDF2-derived key from the master password), never plaintext.

## Package map (where things live — paths are `packages/<group>/<pkg>/src/flinttrade_<pkg>/`)

| Package | Group | Lang | Role |
|---|---|---|---|
| `core` | core | Py | Flask app + blueprint registration, OpenAlgo client (45+ endpoints), config, workspace, auth/JWT, models, WSGI strip |
| `data` | core | Py | Tick capture (opt-in via `FLINTTRADE_TICK_CAPTURE`), append-only JSONL audit log, Practice-mode sandbox engine, tax/P&L routes, DuckDB (QuestDB client exists but is dormant) |
| `historical` | core | Py | OHLCV downloader (OpenChart/yfinance), DuckDB/Parquet pipeline, expiry tracker |
| `indicators` | core | Py | Pure-NumPy batch indicators (110 exports; no TA-Lib import despite the optional extra) + pure-Python streaming classes (numba accelerates only 3 batch kernels, optional) + Pine Script convert |
| `ticks` | core | Rust+PyO3 | Tick-level backtesting simulator (was `tick-engine`) — builds and imports, but currently has zero production consumers |
| `design-system` | core | TS | Shared tokens/glass/cinematic CSS, charts module (Flint* components), brand, layer scale — the consumed surface; the UI-kit/forms/motion exports are unconsumed scaffolding |
| `engine` | services | Py | 5-layer `SafetySystem`, `gate_order`, order router, scheduler, mode guard, sandbox executor, strategies |
| `screener` | services | Py | Option chain, OI/PCR/max-pain, IV smile, futures quadrant, portfolio Greeks, RRG, FII/DII |
| `backtest` | services | Py | Event-driven simulator, 94 template files (132 registered strategy classes), walk-forward, Monte Carlo (library-only), VectorBT (optional extra, not installed by default) |
| `ai` | services | Py | Multi-provider LLM client (incl. Cerebras + Claude Code OAuth), ChromaDB RAG, ML signals, multi-agent team, sentiment, `agent_backends` registry (Codex streaming; Hermes ACP + Antigravity catalogued) |
| `ditto` | services | Py | Multi-account mirror, margin calc, trailing SL, risk manager (AlgoMirror patterns reimplemented natively) |
| `automation` | services | Py | Cron, Telegram bot (kill switch), post-market analysis, voice orders |
| `journal` | services | Py | Trade journal, trade logging, execution analytics, realised P&L |
| `gateway` | integrations | Py | Native broker gateway — `BrokerAdapter` protocol, `BrokerRouter`, `BROKER_CATALOG` (35 brokers), encrypted credential vault, WS bridge, OpenAlgo bridge adapter |
| `webhooks` | integrations | Py | TradingView/ChartInk/GoCharting/custom webhooks + flow builder (n8n + WhatsApp bridges actually live in `automation`) |
| `terminal` | apps | TS/React | SPA: Dockview workspace, 101 widgets, routes — single source of truth for UI |
| `desktop` | apps | TS/Rust | Tauri 2 native shell — bundles the PyInstaller-frozen backend sidecar + built terminal into one cross-OS installer (Linux/Windows/macOS), served from a single loopback origin |
| `site` | apps | TS/Next | Next.js + fumadocs public site, generated docs, docs MCP |

(`chrome-extension` was dropped in the v0.6.0 restructure; the Tauri `desktop` shell was re-added and shipped in v0.6.0-beta.1 — see [docs/DESKTOP.md](docs/DESKTOP.md).)

## House rules that bite

These cause real failures, not just style nits:

- **Python**: PEP 8 + `ruff` (line length 120). Type hints on every public function (`list[int]`, `X | None`). Google-style docstrings. **Absolute imports for anything cross-package or top-level** (`flinttrade_<pkg>....`) — those relative forms break under `--import-mode=importlib` (the `f35cfb31` revert). Intra-package relative imports (`from .sibling import x`) are widespread and safe; don't churn them. Run `ruff check` before claiming done — `F821`/`F401` catch the import-NameError class that import-only checks miss.
- **TypeScript**: strict mode is non-negotiable — no `any`, no `@ts-ignore`, no `@ts-expect-error` without an issue link. All new code in `.ts`/`.tsx`. Functional components and hooks only. Use shadcn/ui primitives (never raw `<button>`/`<input>`/`<dialog>`) and lucide-react icons. Path alias `@` → `packages/apps/terminal/src/` (kept in sync across `tsconfig.json` and `vite.config.ts`; Vitest config lives inside `vite.config.ts` and inherits the alias).
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
3. WebSocket drops without heartbeat — the terminal's `services/websocket.ts` implements ping/pong; preserve it (the Python client is REST-only apart from `ping`).
4. PNL is wrong for some brokers — compute locally from `tradebook`.
5. MCX symbol format is inconsistent — normalise via `flinttrade_core.symbol_utils`.

## CI shape (so you know what's running)

`test.yml` runs eight parallel Ubuntu jobs on push to `main`/`dev` and non-draft PRs: `python-tests`, `node-core-tests`, four `node-widget-tests-*` shards (1, 2a, 2b, 3), `secrets-check` (a grep-based two-pattern scan — NOT gitleaks), and `rust-ticks-tests` (`cargo test` on the `ticks` crate — the only job that runs the crate's unit tests; `cargo audit` in `supply-chain.yml` checks advisories, not behaviour). The vitest shards are hand-maintained path lists, but `tests/test_ci_vitest_shard_coverage.py` (in `python-tests`) now fails CI if any terminal `*.test.ts(x)` runs in no shard — so coverage is complete apart from `TradeIdea` (OOMs the 7GB runner; allowlisted in that guard's `DOCUMENTED_EXCLUSIONS`). The hook, `src/chrome`, `src/widgets/orders/`, `src/widgets/account/`, AITeam, Obsidian and TradeJournal suites all now run (in `node-core-tests` / `node-widget-tests-2b` / `node-widget-tests-3`); `packages/core/core/tests/test_contract_mock_drift.py` pins the async OpenAlgoClient shape and asserts every ftApi-called URL maps to a real route. Other workflows: `supply-chain.yml`, `refresh-vuln-snapshot.yml`, `site.yml`, `status-report.yml`, `desktop-release.yml` (manual trigger), plus the claude review workflows. Doc-only commits skip the matrix via `paths-ignore`. `concurrency: cancel-in-progress: true` means a follow-up push cancels the previous run. Per-push macOS/Windows jobs are a regression — cross-platform belongs in the weekly `nightly-cross-platform.yml`. To debug: `gh run view <id> --log-failed`.

## External test deps (not bundled)

OpenAlgo is an external service (formerly a submodule). For local testing, `scripts/setup-test-deps.sh` clones it into `.local/external/` (gitignored). AlgoMirror is intentionally absent: its patterns are reimplemented natively in `packages/services/ditto/` (our own code). OpenClaw was dropped in the AI-backends rework — the `agent_backends` layer (Codex/Hermes/Antigravity + the LLM providers) replaced its external-gateway bridge.

## Working style (this repo)

- **Review pipeline:** claude (ultracode multi-agent panels) → maintainer. Codex is retired from the loop.
- **Spec-first:** design work lives in `.local/specs/<area>/` with a `DESIGN_LOG.md`; `changelog.md` is for **shipped** code only.
- After any build/commit wave, run a full multi-agent audit before declaring done. Fix everything, then re-audit.
- `AGENTS.md` carries the full agent/tooling workflow; `PLAN.md` is the living roadmap.

# CLAUDE.md

Broker connections use five native adapters: Dhan, Upstox, Kotak Neo,
INDmoney and Groww. Availability remains evidence-gated. Native broker HTTP
mutations and reads remain frozen until Task 9D and Task 7C.2; a broker session
cannot currently be established through the terminal. Practice uses the local
sandbox. Funded Live placement remains unproven and fail-closed.


This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FlintTrade is open-source, self-hosted trading software for manual, automated, algorithmic, and AI-assisted workflows. It runs **its own native backend first** and uses native broker adapters. Monorepo of **18 package surfaces** in a fat-core 4-way nest: 13 Python, 1 Rust/PyO3 (`ticks`), 1 shared TypeScript design-system, 1 React terminal, 1 Electron desktop shell, 1 Next.js site. Licensed AGPL-3.0. Target Python `>=3.12` (no upper bound; the repo currently runs 3.14), Node `>=22.22.2` (jsdom 30's engine floor). The full architectural reference is [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); contributor mechanics are [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md); CI is [docs/CI.md](docs/CI.md); the live roadmap is [PLAN.md](PLAN.md). Read those before non-trivial work.

Version: **v0.0.1** (clean-slate pre-1.0 baseline after the 2026-07-23 release reset; not production-ready). Python tooling is **uv** (workspace lockfile `uv.lock`); JS is **pnpm** (workspace lockfile `pnpm-lock.yaml`).

## Commands

`python scripts/ft.py <cmd>` is the cross-platform entry point — identical behaviour on Windows, macOS and Linux; `python scripts/ft.py help` lists every command. `make <target>` is the POSIX alias for the same targets (`make help` lists them; a few POSIX-only targets have no `ft.py` equivalent). Most-used:

```bash
# Tests (Python via uv; flat-package layout needs --import-mode=importlib, which the runner sets)
python scripts/ft.py test                                          # all pytest (POSIX alias: make test)
python scripts/ft.py test-fast                                     # pytest, stop on first failure (make test-fast)
uv run pytest packages/<group>/<pkg>/tests/ -v --import-mode=importlib              # single package
uv run pytest packages/core/core/tests/test_app.py::test_name -v --import-mode=importlib   # single test
cd packages/apps/terminal && npx vitest run                        # all Vitest
cd packages/apps/terminal && npx vitest run src/widgets/path/foo.test.tsx
cd packages/apps/terminal && npx vitest run -t "places a market order"

# Lint / typecheck
python scripts/ft.py lint                                          # ruff over packages/ tests/ (make lint)
cd packages/apps/terminal && npm run typecheck                     # tsc --noEmit (strict)

# Build
cd packages/apps/terminal && npm run build                         # tsc --noEmit + vite build
cd packages/core/ticks && cargo build --release                    # Rust/PyO3 wheel
python scripts/ft.py desktop-build                                 # verify/test/bundle the Electron shell (make desktop-build)
python scripts/ft.py desktop-package                               # package + verify this host's Electron installer

# Dev / run
python scripts/ft.py dev                                           # terminal dev server + backend (make dev)
python scripts/ft.py desktop-dev                                   # run Electron against its managed source bootstrap
python scripts/ft.py start                                         # FlintTrade backend (port 5100) (make start)
make docker-up | docker-down | docker-build                        # POSIX-only Makefile targets
make full-check                                                    # tests + lint + typecheck snapshot (POSIX-only)
```

Dependencies are installed with `uv sync` (Python, incl. the dev group) and `pnpm install` (JS workspace: terminal + site + design-system + desktop).

## Architecture (essentials)

| Dev proxy prefix | Target |
|---|---|
| `/ft-api`  | `http://127.0.0.1:5100` (FlintTrade backend) |

**WSGI prefix strip.** The backend lives in [packages/core/core/src/flinttrade_core/app.py](packages/core/core/src/flinttrade_core/app.py) and binds to 5100. Middleware strips `/ft-api` before URL dispatch, so a blueprint registered at `url_prefix="/v1"` answers external `/ft-api/v1/…`. Note: most `ftApi.*` callers use the **`/api/v1`** prefix (served by the backend too) — match the prefix the frontend uses; **never double-prefix**. A blueprint at `/v1/X` that the frontend calls at `/api/v1/X` will 404 (the recurring wiring bug).

**Gated execution (the headline feature — do not bypass).** Every reachable live order traverses, in order: `SafetySystem` **L1–L5** (order validation → position limits → portfolio risk → daily P&L → kill switch) → `gate_order()` (mints a one-shot HMAC `SafetyContext` bound to a selector-bound principal) → `BrokerRouter` (re-HMAC + field-by-field match + account ACL + one-shot gate consume) → broker adapter (module-private `_ROUTER_TOKEN`). The five founder-broker **native adapters** (Dhan, Upstox, Kotak Neo, INDmoney, Groww) are doc-grounded and mock-tested but their write surfaces are deliberately asymmetric (Dhan: full incl. forever/super/conditional; Upstox: GTT-via-variety + multi/cancel-all/exit-all/convert; Kotak Neo: place/modify/cancel plus a fail-closed emergency planner; INDmoney: trio + smart-cancel; Groww: regular/smart REST paths pending promotion) — `test_no_legacy_order_path.py` pins exactly this. They stay dormant until SDK attestation + vault credentials; the activation plumbing now exists (Phase 1) — the credential-replay login step (`flinttrade_gateway/native_login.py`: vault → `adapter.login()` → registry session), the in-app credential-capture UX (Settings → Brokers via `native_account_routes.py` `/api/v1/native/*`), the OAuth connect flow, and daily session refresh (`native_rotation.py`). Broker-management writes require the operator's session JWT (G9); the PIN is a re-auth factor over a live session, never a session-minting one (D6). Native connectability is evidence-gated: the current connectable native set is Dhan, Upstox, and Kotak Neo. Dhan and Upstox are connectable after live login/read verification and emergency-planner coverage. Kotak Neo is catalogue-connectable for Connected (read) / API smoke only (FT-MONDAY-002) — never placeable Live; Live place stays fail-closed. Neo has no sandbox — never offer Neo Practice; operator copy is `Live read only until funded unlock.` Funded Live place / market-hours order-safety proof for Neo remain pending (human-gated). Native HTTP freeze (Task 9D / Task 7C.2) is not lifted; Setup → Brokers HTTP still fails; MSI static-IP host native read smoke is the in-process native read path. SDK: `dhanhq` 2.2.0. Neo's runtime is exact upstream `main` `9a37488d77dc96442ee2a90ef78462e688cf4856`; `v3.0.7` peeled to `53cccc45fe56a193b30ffce3c03c71c5c0378538` is the release baseline. The runtime exposes `kotakneoapi` 3.0.8; explicit `release_version` 3.0.7 retains the stable compatibility baseline through the intentionally retained `neo_api_client` namespace; reject the obsolete `neo-api-client` distribution. The 3.0.8 runtime update is verified offline only; earlier non-funded activation evidence remains historical. Neo's async SFeed/order-feed lifecycle is locally synthetic-tested only. Sandbox proof is unavailable because Neo offers no sandbox; live-account/market-hours, funded order, Live catalogue promotion, and cross-platform proof remain outstanding. INDmoney is login/read verified but remains disabled until restart-time smart-parent cancellation is authoritative, a broker-native atomic reduce-only close primitive exists, and live order-safety proof passes. Groww (API-key session approved; account reads + margin checks verified) remains disabled until market-data/API permission, static-IP setup, and order-safety evidence clear. New gated write verbs are routed table-driven via `BrokerRouter.execute_gated` (minted by `gate_broker_write`). If you wire a new order path (basket, webhook, agent, mirror, or a new verb), it MUST mint a `SafetyContext` through `gate_order`/`gate_broker_write` → `BrokerRouter` — `gateway/tests/test_no_legacy_order_path.py` is the grep guard.

**Three-mode state machine** (Explore / Practice / Live) enforced server-side by [packages/services/engine/src/flinttrade_engine/mode_guard.py](packages/services/engine/src/flinttrade_engine/mode_guard.py). Transitions mint a new JWT with the new `mode` claim and revoke the old `jti` (minting/revocation lives in core `auth_routes.py`; `mode_guard.py` enforces the claim per request). A live order on a Practice JWT is rejected 403 with code `mode_blocked`/`practice_unsupported`; Practice routes to the native SandboxEngine.

**Frontend state boundaries** (do not mix):
- **Jotai atoms** — WebSocket-driven per-instrument LTP/quote/depth and derived values.
- **TanStack Query** — REST responses (positions, orders, holdings, funds, option chain).
- **Zustand** — derived/UI state only (connection, layout, settings mirror, aggregated P&L, mode).

Each data shape enters through one path only. Duplicate it and you guarantee a bug.

## Package map (where things live — paths are `packages/<group>/<pkg>/src/flinttrade_<pkg>/`)

| Package | Group | Lang | Role |
|---|---|---|---|
| `core` | core | Py | Flask app + blueprint registration, native broker reads, config, workspace, auth/JWT, models, WSGI strip |
| `data` | core | Py | Tick capture (opt-in via `FLINTTRADE_TICK_CAPTURE`), append-only JSONL audit log, Practice-mode sandbox engine, tax/P&L routes, DuckDB (QuestDB client exists but is dormant) |
| `historical` | core | Py | OHLCV downloader (OpenChart/yfinance), DuckDB/Parquet pipeline, expiry tracker |
| `indicators` | core | Py | Pure-NumPy batch indicators (110 exports; no TA-Lib — the unused extra was removed) + pure-Python streaming classes (numba accelerates only 3 batch kernels, optional) + Pine Script convert |
| `ticks` | core | Rust+PyO3 | Tick-level backtesting simulator (was `tick-engine`) — optional accelerated engine for `flinttrade_backtest.signal_backtest` (pure-Python default, byte-equivalence tested) |
| `design-system` | core | TS | Shared tokens/glass/cinematic CSS, charts module (Flint* components), brand, layer scale — the consumed surface; the UI-kit/forms/motion exports are unconsumed scaffolding |
| `engine` | services | Py | 5-layer `SafetySystem`, `gate_order`, order router, scheduler, mode guard, sandbox executor, strategies |
| `screener` | services | Py | Option chain, OI/PCR/max-pain, IV smile, futures quadrant, portfolio Greeks, RRG, FII/DII |
| `backtest` | services | Py | Event-driven simulator, 94 template files (132 registered strategy classes), walk-forward, Monte Carlo (library-only), VectorBT (optional extra, not installed by default) |
| `ai` | services | Py | Multi-provider LLM client (incl. Cerebras + Claude Code OAuth), local SQLite/NumPy RAG, ML signals, multi-agent team, sentiment, `agent_backends` registry (Codex streaming; Hermes ACP + Antigravity catalogued) |
| `ditto` | services | Py | Multi-account mirror, margin calc, trailing SL, risk manager (AlgoMirror patterns reimplemented natively) |
| `automation` | services | Py | Cron, Telegram bot (kill switch), post-market analysis |
| `journal` | services | Py | Trade journal, trade logging, execution analytics, realised P&L |
| `gateway` | integrations | Py | Native broker gateway — `BrokerAdapter`, `BrokerRouter`, `BROKER_CATALOG` (6 brokers), encrypted vault and exact-account reads |
| `webhooks` | integrations | Py | Generic HMAC-signed custom webhooks (the TradingView/ChartInk/GoCharting parsers and the n8n/WhatsApp bridges were removed on 2026-07-26; a retired provider source now 404s) |
| `terminal` | apps | TS/React | SPA: FlexLayout workspace, 71 widgets, FDC3 channel bus, routes — single source of truth for UI |
| `desktop` | apps | TS/Electron | Sandboxed Electron 44 shell — verifies tools, builds managed local source, supervises its guardian, and loads only the selected loopback origin |
| `site` | apps | TS/Next | Next.js + fumadocs public site, generated docs, docs MCP |

(`chrome-extension` was dropped in the v0.6.0 restructure. The Tauri shell was
first shipped in the beta line and is now retired in favour of the Electron
source-bootstrap architecture. The source-built web app remains distinct from
Electron-shell installers; a release is accepted only as all four canonical
installers plus `SHA256SUMS.txt`, and retired Tauri and PyInstaller assets never
satisfy that gate. See [docs/DESKTOP.md](docs/DESKTOP.md).)

## House rules that bite

- Preserve exact-account identity and the SafetyContext → BrokerRouter gate.
- Secrets remain in hardened workspace files; native credentials use the encrypted gateway vault.
- The backend uses port 5100.

- **Python**: PEP 8 + `ruff` (line length 120). Type hints on every public function (`list[int]`, `X | None`). Google-style docstrings. **Absolute imports for anything cross-package or top-level** (`flinttrade_<pkg>....`) — those relative forms break under `--import-mode=importlib` (the `f35cfb31` revert). Intra-package relative imports (`from .sibling import x`) are widespread and safe; don't churn them. Run `ruff check` before claiming done — `F821`/`F401` catch the import-NameError class that import-only checks miss.

- **TypeScript**: strict mode is non-negotiable — no `any`, no `@ts-ignore`, no `@ts-expect-error` without an issue link. All new code in `.ts`/`.tsx`. Functional components and hooks only. Use shadcn/ui primitives (never raw `<button>`/`<input>`/`<dialog>`) and lucide-react icons. Path alias `@` → `packages/apps/terminal/src/` (kept in sync across `tsconfig.json` and `vite.config.ts`; Vitest config lives inside `vite.config.ts` and inherits the alias).

- **No mock/placeholder/fake data in any UI** without an explicit `isExplore`/`isConnected` guard + visible "Demo data" affordance. A widget that renders fabricated prices and lets a click place a live order is a safety bug.

- **British English** in docstrings, comments, and **user-visible strings** (behaviour, organise, colour, centred…). Code identifiers keep upstream spelling. Indian market terms always win: "expiry" (never "expiration"), "lakh", "crore", "scrip".

- **Conventional Commits** are mandatory (`feat|fix|docs|test|chore|refactor|perf|ci(scope): …`). Scope is the package name or focus area.

- **Never** `git add -A` / `git add .` — stage explicitly. Never commit `.env`, API keys, broker account names, fund amounts, order IDs, or personal hostnames/IPs. Never push without explicit permission, and never with `--no-verify` or `dangerouslySkipPermissions`.

- Before opening or merging any PR, fetch `origin`, verify `origin/main` against the live remote, and bring local `main` and the PR branch up to date with affected verification repeated. A stale fetched base is not sufficient, and this check grants no push or merge permission.

- Every new widget is a workspace (FlexLayout) panel registered in [packages/apps/terminal/src/layout/widgetFactory.tsx](packages/apps/terminal/src/layout/widgetFactory.tsx) with a co-located `<Name>.test.tsx`.

- The pytest harness registers three markers (`unit`, `integration`, `slow`) under `--strict-markers` — a typo'd marker fails CI. Tag new tests.

These cause real failures, not just style nits:

## CI shape (so you know what's running)

`test.yml` runs a change classifier and ten verification jobs on pushes to `main`/`dev` and non-draft PRs. The Python, node-core, secrets and terminal E2E infrastructure jobs always run; four widget shards, Rust and Electron use the classifier to skip inert changes. Electron packaging runs on Ubuntu 24.04. `docs/CI.md` and the workflow files are authoritative for job names, triggers, coverage guards and required checks. Cross-platform verification belongs in `nightly-cross-platform.yml`; installer publication follows the separate `desktop-release.yml` gates. Diagnose failures with `gh run view <id> --log-failed`.

## Working style (this repo)

- **Review pipeline:** build agents (Codex or other supported agents) → independent multi-agent review panels → maintainer.
- **Spec-first:** design work lives in `.local/specs/<area>/` with a `DESIGN_LOG.md`; `changelog.md` is for **shipped** code only.
- After any build/commit wave, run a full multi-agent audit before declaring done. Fix everything, then re-audit.
- `AGENTS.md` carries the full agent/tooling workflow; `PLAN.md` is the curated public roadmap (the detailed working plan lives in the maintainer's private workspace at `.local/agent-context/PLAN.md`).

## Agent skills

Read the [Agent skills section in AGENTS.md](AGENTS.md#agent-skills) for the issue tracker, triage labels and domain docs configuration.

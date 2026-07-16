# Repository Guidelines

## Project Structure & Module Organisation

FlintTrade is a monorepo for an Indian trading platform. Python packages live under `packages/core/<name>/src`, `packages/services/<name>/src`, and `packages/integrations/<name>/src`, with tests beside them under `tests/`; shared repository tests live in the root `tests/` folder. The React/Vite terminal is in `packages/apps/terminal/src`, with Vitest tests co-located as `*.test.tsx` (plus suites under `src/__tests__/`), and Playwright specs in `packages/apps/terminal/e2e`. Rust/PyO3 tick processing lives in `packages/core/ticks`. Operational scripts are in `scripts/` and `infra/`; docs are in `docs/`.

## Build, Test, and Development Commands

Use the root `Makefile` as the main entry point.

- `make setup` installs project dependencies.
- `make dev` starts the terminal dev server plus the FlintTrade backend; run `make start-openalgo` separately only for the optional OpenAlgo integration path.
- `make test` runs all pytest suites with the required import mode.
- `make test-fast` stops pytest on the first failure.
- `make lint` runs Ruff over Python packages and tests.
- `make full-check` runs a compact tests, lint, and terminal typecheck pass.
- `cd packages/apps/terminal && npm run build` runs `tsc --noEmit` plus Vite.
- `cd packages/apps/terminal && npm run test` runs Vitest; `npm run e2e` runs Playwright.

## Coding Style & Naming Conventions

EditorConfig sets LF endings, final newlines, two-space indentation by default, four spaces for Python, and tabs for `Makefile`. Python targets 3.12, uses Ruff with a 120-character line length, absolute imports, public API type hints, and Google-style docstrings. TypeScript is strict: use `.ts`/`.tsx`, functional components, hooks, shadcn/ui primitives, and `lucide-react` icons. Prose, user-visible strings, comments, and docs use British English, except code identifiers and third-party API names.

## Testing Guidelines

Run focused tests before broad suites, for example `uv run pytest packages/integrations/gateway/tests/ -v --import-mode=importlib` or `cd packages/apps/terminal && npx vitest run -t "places a market order"`. Pytest markers are `unit`, `integration`, and `slow`; misspelled markers fail CI. New widgets should include a co-located `<Name>.test.tsx` and be registered as Dockview panels.

## Commit & Pull Request Guidelines

Follow Conventional Commits, as used in history: `feat(terminal): add sector rotation widget`, `fix(tests,docs): align project-structure test`, or `chore(repo): untrack ignored folders`. Scope should be a package or focus area. Stage explicit files only; do not use `git add -A` or `git add .`. PRs should describe intent, link issues, list tests run, include screenshots for UI changes, and update docs when behaviour changes.

## Agentic Workflow

- **Pipeline:** build agents (Codex or claude) → claude ultracode multi-agent review panels → maintainer. After any build/commit wave, run a full multi-agent audit before declaring done — fix everything found, then re-audit.
- **Full arsenal:** for substantial work use the ultracode `Workflow` tool (fan-out → adversarial verify → synthesise), relevant skills, specialised agents, and MCP (a library-docs MCP for APIs, the browser-preview toolset for UI). Don't fall back to bare read/edit when a specialised tool fits.
- **Gated execution is load-bearing:** any new order path must mint a `SafetyContext` through `gate_order` → `BrokerRouter`. Never add a path that reaches a broker adapter or `OpenAlgoClient.place_order` ungated.
- **Spec-first:** design work lives in `.local/specs/<area>/` with a `DESIGN_LOG.md`; `PLAN.md` is the living roadmap; `changelog.md` is for **shipped** code only (no in-flight design entries).
- **Verification:** Python is verified locally (any OS) against the `.venv` (`uv run` / `.venv` python). Cross-platform (macOS/Windows) and the terminal (TS) are validated by **CI + the contributor pool** — never assume a single machine validates a language or OS. Never push without explicit maintainer permission; never `--no-verify`.
- **no-overscope:** personal-use open-source — no DPDPA / §65B / CERT-In / RBI / vendor-SEBI ceremony. Only AGPL compliance + OpenAlgo-parity observability apply.

## Current handoff (2026-07-17)

State at handoff: Phase 3 exit criterion met (waves 1–2: 16 features), the Codex broker wave is audited/landed, and the **deferred-ledger clearance wave** has cleared every open item from `.local/specs/consolidation/DEFERRED-LEDGER.md` — daily-driver trade-loop wiring (watchlist→chart, live tick subscriptions, session-aware order refresh), honesty passes (Demo badges ×8, arbitrage scanner, economic calendar), error surfacing (WS auth backoff, Action Centre, MTM/NetPosition), per-position square-off, OrderPad lot validation (incl. the native-stepMismatch bug that blocked ALL NFO orders), **gated bracket orders** (`/api/v1/orders/bracket`; legs traverse gate_order → BrokerRouter via injected dispatchers; fail-closed cancel), desktop sidecar watchdog + OAuth opener, one-command installers (`scripts/install/`, reading GitHub release assets directly), CI-owned releases (release-please → five installers + hash-verified backend payloads), the native one-click updater (tauri-plugin-updater), and payload-based backend updates. CI green on `main`; count pins: 102 widgets, 35 brokers, 18 packages. `PLAN.md` is the roadmap of record — resume from its phase tracker, never restart planning.

**Next-work queue (in order):**
1. **Thin-shell desktop** — shell-only installers (~6 MB) with first-run hash-verified payload bootstrap; ad-hoc macOS sealing until Apple secrets exist.
2. **Phase 2 stabilisation remainder** — G40 broker-connect merge (`.local/specs/consolidation/BACKLOG.md`), infra script duplicates, GTT order UI, post_market_analysis cron handler, dead admin-route dispositions (G31/G32/U18 shipped).
3. **Phase 4 learning loop** — AI1–AI3 + the full-day Practice run; spec first in `.local/specs/`.
4. **Phase 5 remainder** — Apple signing secrets when the maintainer adds them; macOS install/uninstall hands-on checklist.
5. **Bracket follow-ups** — OCO monitoring (one leg fills → cancel sibling) is refused-at-placement today, not silently accepted; a proper engine-side monitor is the next step. `BrokerRouter`/`_resolve_target` private-config coupling in `bracket_routes.py` mirrors core order routes — refactor both together or neither.
6. **Human-gated (do not attempt autonomously):** Groww session approval, Kotak Neo live probe, funded order smoke, W6 spec, B3 order-capable MCP decision.

**Non-negotiables (verify before claiming done):**
- Every reachable live order mints a `SafetyContext` via `gate_order`/`gate_broker_write` → `BrokerRouter`; `gateway/tests/test_no_legacy_order_path.py` is the guard — run it after touching anything order-adjacent.
- MERGE the union of capabilities — never delete a duplicate blind; a pure-dead-path exception must be stated in the commit message.
- Frontend live-order entrypoints stay fail-closed (`assertNativeWriteTargetReadyOrThrow`); broker store selectors use composite `source:broker:account_id` keys.
- Widget/broker/package count pins move in lockstep: `widgetFactory.test.ts` (catalogue), `test_adapter.py` (BROKER_CATALOG), `capabilities.test.ts` (site), `test_project_structure.py` (packages).
- Lockfile changes require `python scripts/generate-notice.py` + commit, or the Supply Chain workflow fails on NOTICE drift.
- Full local gate before any push (and push only with explicit maintainer permission): whole pytest tree, ruff, `tsc --noEmit`, full terminal vitest (CI shards under-cover; run everything), terminal build, site vitest, secrets scan.

## Security & Configuration

Never commit `.env`, API keys, broker credentials, fund amounts, order IDs, hostnames, or personal IPs. Start from `.env.example`. Secrets (master password, JWT secret, API-key pepper, safety-gate secret) are file-backed + hardened under the platform workspace dir (`~/.flinttrade/` on Linux, `~/Library/Application Support/flinttrade/` on macOS, `%APPDATA%/flinttrade/` on Windows), never in `.env`. Native-adapter broker credentials live in the encrypted gateway vault (`gateway/credentials.py`, Fernet with a per-row random salt + PBKDF2-derived key from the master password); the OpenAlgo bridge path keeps broker auth inside OpenAlgo and holds only the OpenAlgo API key. Report vulnerabilities through `security.md` rather than public issues.

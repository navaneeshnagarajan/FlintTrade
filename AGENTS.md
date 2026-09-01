# Repository Guidelines

## Project Structure & Module Organisation

FlintTrade is a monorepo for an Indian trading platform. Python packages live under `packages/core/<name>/src`, `packages/services/<name>/src`, and `packages/integrations/<name>/src`, with tests beside them under `tests/`; shared repository tests live in the root `tests/` folder. The React/Vite terminal is in `packages/apps/terminal/src`, with Vitest tests co-located as `*.test.tsx` (plus suites under `src/__tests__/`), and Playwright specs in `packages/apps/terminal/e2e`. Rust/PyO3 tick processing lives in `packages/core/ticks`. Operational scripts are in `scripts/` and `infra/`; docs are in `docs/`.

## Build, Test, and Development Commands

`python scripts/ft.py <target>` is the cross-platform entry point — it needs no make and no bash, and behaves identically on Windows, macOS and Linux. After an install the shim exposes the same subcommands as `flinttrade <target>`. `make <target>` is the POSIX alias for the same targets; a few POSIX-only targets have no `ft.py` equivalent and are marked below.

- `python scripts/ft.py setup` installs project dependencies.
- `python scripts/ft.py dev` starts the terminal dev server plus the FlintTrade backend; run `make start-openalgo` (POSIX only) separately for the optional OpenAlgo integration path.
- `python scripts/ft.py test` runs all pytest suites with the required import mode.
- `python scripts/ft.py test-fast` stops pytest on the first failure.
- `python scripts/ft.py lint` runs Ruff over Python packages and tests.
- `make full-check` (POSIX only — it needs bash) runs a compact tests, lint, and terminal typecheck pass.
- `pnpm --filter @flinttrade/terminal build` runs `tsc --noEmit` plus Vite.
- `pnpm --filter @flinttrade/terminal test` runs Vitest; `pnpm --filter @flinttrade/terminal e2e` runs Playwright.

Never chain these with `&&` in documentation or in instructions to a contributor: Windows PowerShell 5.1 has no `&&` operator. Put one command per line, or use `;`.

## Coding Style & Naming Conventions

EditorConfig sets LF endings, final newlines, two-space indentation by default, four spaces for Python, and tabs for `Makefile`. Python targets 3.12, uses Ruff with a 120-character line length, absolute imports, public API type hints, and Google-style docstrings. TypeScript is strict: use `.ts`/`.tsx`, functional components, hooks, shadcn/ui primitives, and `lucide-react` icons. Prose, user-visible strings, comments, and docs use British English, except code identifiers and third-party API names.

## Testing Guidelines

Run focused tests before broad suites, for example `uv run pytest packages/integrations/gateway/tests/ -v --import-mode=importlib`, or `npx vitest run -t "places a market order"` after `cd packages/apps/terminal` (two lines, not an `&&` chain). Pytest markers are `unit`, `integration`, and `slow`; misspelled markers fail CI. New widgets should include a co-located `<Name>.test.tsx` and be registered as FlexLayout panels in `packages/apps/terminal/src/layout/widgetFactory.tsx`.

## Commit & Pull Request Guidelines

Follow Conventional Commits, as used in history: `feat(terminal): add sector rotation widget`, `fix(tests,docs): align project-structure test`, or `chore(repo): untrack ignored folders`. Scope should be a package or focus area. Stage explicit files only; do not use `git add -A` or `git add .`. PRs should describe intent, link issues, list tests run, include screenshots for UI changes, and update docs when behaviour changes.

## Agentic Workflow

- **Pipeline:** build agents (Codex or claude) → claude ultracode multi-agent review panels → maintainer. After any build/commit wave, run a full multi-agent audit before declaring done — fix everything found, then re-audit.
- **Full arsenal:** for substantial work use the ultracode `Workflow` tool (fan-out → adversarial verify → synthesise), relevant skills, specialised agents, and MCP (a library-docs MCP for APIs, the browser-preview toolset for UI). Don't fall back to bare read/edit when a specialised tool fits.
- **Gated execution is load-bearing:** any new order path must mint a `SafetyContext` through `gate_order` → `BrokerRouter`. Never add a path that reaches a broker adapter or `OpenAlgoClient.place_order` ungated.
- **Spec-first:** design work lives in `.local/specs/<area>/` with a `DESIGN_LOG.md`; `PLAN.md` is the curated public roadmap (the detailed working plan lives at `.local/agent-context/PLAN.md`); `changelog.md` is for **shipped** code only (no in-flight design entries).
- **Verification:** Python is verified locally (any OS) against the `.venv` (`uv run` / `.venv` python). Cross-platform (macOS/Windows) and the terminal (TS) are validated by **CI + the contributor pool** — never assume a single machine validates a language or OS. Never push without explicit maintainer permission; never `--no-verify`.
- **no-overscope:** personal-use open-source — no DPDPA / §65B / CERT-In / RBI / vendor-SEBI ceremony. Only AGPL compliance + OpenAlgo-parity observability apply.

## Current handoff (2026-07-29)

State at handoff: Phase 3 and the deferred-ledger clearance remain landed. The
Tauri-to-Electron migration merged to `main` in `a6f92464` and is complete in
the settled tree. Electron 43.2.0 now provides the hardened shell,
checksum-bound first-run source and tool bootstrap, journalled source updates,
source guardian lifecycle, renderer update UX and four-installer release
pipeline. The retained Tauri/frozen-payload production path and dependencies
are gone. The desktop installer contains only the shell and bootstrap
resources; first launch builds the managed checkout at
`~/.flinttrade/src/FlintTrade`, and source/runtime updates remain distinct from
Electron-shell installer updates.

Task 8 is complete. A clean Finder-installed universal macOS DMG bootstrapped
`main` at `3c4d0902` into empty source/workspace state, reached the real Welcome
screen and passed the installed OAuth, tray/hotkey, update, Quit and uninstall
acceptance. The 2026-07-29 branding follow-up replaces the generic orange
desktop tile with the canonical FlintTrade angular `F` and green spark. One
deterministic generator now owns every PNG, ICNS and ICO output; macOS, Windows,
Linux and NSIS point at explicit native assets; packaged runtimes byte-verify
the app/tray icons; Linux windows use the packaged app icon; and the AppImage
installer selects its exact path instead of the first bundled PNG.

The latest local DMG is 219,591,645 bytes with SHA-256
`8eeb2d8dfe00cb903d7e388489bb93cc197b4f2ae22ddffe45b2ea790604914f`;
its `app.asar` SHA-256 is
`4bdfee7cd9b45f5846a65298f03a15dc744aa2856680545ef963ca8ba4a84b12`.
The settled follow-up gate passed 14,880 Python tests (68 skipped), 69 Rust
tests, 962 desktop tests (8 skipped), 5,785 terminal tests and 69 site tests,
plus Ruff, all typechecks/builds, secrets, NOTICE/provenance/lock drift, package
verification and a clean cross-platform icon re-review. Evidence is under
`.local/specs/desktop-electron/evidence/icon-followup-20260729/`; the older Task
8 bundle remains historical evidence for the installed-app acceptance.

No Electron installer release is published. The site exposes the distinct
source-built web-app install path, but withholds Electron-shell installer
commands and downloads until all four installers and `SHA256SUMS.txt` exist
together. Local
macOS output is ad-hoc sealed with no Team ID; Apple distribution
signing/notarisation, Windows/Linux native runtime evidence and the accepted
RF3 Windows job-supervisor digest pin remain maintainer/native-runner work.
Count pins remain 71 widgets, 37 brokers and 18 packages. `PLAN.md` is the
curated public roadmap; the detailed working plan of record lives at
`.local/agent-context/PLAN.md` — resume from its ordered delivery/status/current
work queue, verify branch/PR state live, and never push without explicit
maintainer permission.

**Next-work queue (in order):**
1. **Phase 2 stabilisation remainder** — continue only evidence-backed duplicate consolidation. Cross-platform nightly-CI repairs landed in #140. G40 broker-connect, infra-script de-duplication, native GTT UI, `post_market_analysis`, dead admin-route wiring, G31/G32/U18 and the final two widget merges are shipped or superseded.
2. **Phase 4 learning loop** — AI1 and AI2 shipped; AI3 is deferred to a maintainer sandbox-design call. The remaining execution gate is the full-day Practice run on a market day.
3. **Phase 5 publication/signing** — publish only after native CI evidence and the complete release set; add Apple signing/notarisation secrets when the maintainer is ready, and never describe an ad-hoc seal as distribution signing.
4. **Bracket follow-ups** — OCO monitoring (one leg fills → cancel sibling) is refused at placement today, not silently accepted; a proper engine-side monitor is the next step. `BrokerRouter`/`_resolve_target` private-config coupling in `bracket_routes.py` mirrors core order routes — refactor both together or neither.
5. **Human-gated (do not attempt autonomously):** Groww session approval, Kotak Neo live probe, funded order smoke, W6 spec, B3 order-capable MCP decision.

**Non-negotiables (verify before claiming done):**
- Every reachable live order mints a `SafetyContext` via `gate_order`/`gate_broker_write` → `BrokerRouter`; `gateway/tests/test_no_legacy_order_path.py` is the guard — run it after touching anything order-adjacent.
- MERGE the union of capabilities — never delete a duplicate blind; a pure-dead-path exception must be stated in the commit message.
- Frontend live-order entrypoints stay fail-closed (`assertNativeWriteTargetReadyOrThrow`); broker store selectors use composite `source:broker:account_id` keys.
- Widget/broker/package count pins move in lockstep: `widgetFactory.test.ts` (catalogue), `test_adapter.py` (BROKER_CATALOG), `capabilities.test.ts` (site), `test_project_structure.py` (packages).
- Lockfile changes require `python scripts/generate-notice.py` + commit, or the Supply Chain workflow fails on NOTICE drift.
- Full local gate before any push (and push only with explicit maintainer permission): whole pytest tree, ruff, `tsc --noEmit`, full terminal vitest (CI shards under-cover; run everything), terminal build, site vitest, secrets scan.

## Security & Configuration

Never commit `.env`, API keys, broker credentials, fund amounts, order IDs, hostnames, or personal IPs. Start from `.env.example`. Secrets (master password, JWT secret, API-key pepper, safety-gate secret) are file-backed + hardened under the platform workspace dir (`~/.flinttrade/` on Linux, `~/Library/Application Support/flinttrade/` on macOS, `%APPDATA%/flinttrade/` on Windows), never in `.env`. Native-adapter broker credentials live in the encrypted gateway vault (`gateway/credentials.py`, Fernet with a per-row random salt + PBKDF2-derived key from the master password); the OpenAlgo bridge path keeps broker auth inside OpenAlgo and holds only the OpenAlgo API key. Report vulnerabilities through `security.md` rather than public issues.

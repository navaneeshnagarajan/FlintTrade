# Repository Guidelines

## Project Structure & Module Organisation

FlintTrade is a monorepo for an Indian trading platform. Python packages live under `packages/core/<name>/src`, `packages/services/<name>/src`, and `packages/integrations/<name>/src`, with tests beside them under `tests/`; shared repository tests live in the root `tests/` folder. The React/Vite terminal is in `packages/apps/terminal/src`, with Vitest tests under `packages/apps/terminal/tests` or co-located as `*.test.tsx`, and Playwright specs in `packages/apps/terminal/e2e`. Rust/PyO3 tick processing lives in `packages/core/ticks`. Operational scripts are in `scripts/` and `infra/`; docs are in `docs/`.

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

Run focused tests before broad suites, for example `python -m pytest packages/integrations/gateway/tests/ -v --import-mode=importlib` or `cd packages/apps/terminal && npx vitest run -t "places a market order"`. Pytest markers are `unit`, `integration`, and `slow`; misspelled markers fail CI. New widgets should include a co-located `<Name>.test.tsx` and be registered as Dockview panels.

## Commit & Pull Request Guidelines

Follow Conventional Commits, as used in history: `feat(terminal): add sector rotation widget`, `fix(tests,docs): align project-structure test`, or `chore(repo): untrack ignored folders`. Scope should be a package or focus area. Stage explicit files only; do not use `git add -A` or `git add .`. PRs should describe intent, link issues, list tests run, include screenshots for UI changes, and update docs when behaviour changes.

## Agentic Workflow

- **Review pipeline:** claude (ultracode multi-agent panels) → maintainer. Codex is retired from the loop. After any build/commit wave, run a full multi-agent audit before declaring done — fix everything found, then re-audit.
- **Full arsenal:** for substantial work use the ultracode `Workflow` tool (fan-out → adversarial verify → synthesise), relevant skills, specialised agents, and MCP (`context7` for library APIs, `playwright`/`gstack` for UI). Don't fall back to bare read/edit when a specialised tool fits.
- **Gated execution is load-bearing:** any new order path must mint a `SafetyContext` through `gate_order` → `BrokerRouter`. Never add a path that reaches a broker adapter or `OpenAlgoClient.place_order` ungated.
- **Spec-first:** design work lives in `.local/specs/<area>/` with a `DESIGN_LOG.md`; `PLAN.md` is the living roadmap; `changelog.md` is for **shipped** code only (no in-flight design entries).
- **Verification:** Python is verified locally (any OS) against the `.venv` (`uv run` / `.venv` python). Cross-platform (macOS/Windows) and the terminal (TS) are validated by **CI + the contributor pool** — never assume a single machine validates a language or OS. Never push without explicit maintainer permission; never `--no-verify`.
- **no-overscope:** personal-use open-source — no DPDPA / §65B / CERT-In / RBI / vendor-SEBI ceremony. Only AGPL compliance + OpenAlgo-parity observability apply.

## Security & Configuration

Never commit `.env`, API keys, broker credentials, fund amounts, order IDs, hostnames, or personal IPs. Start from `.env.example`. Secrets (master password, JWT secret, API-key pepper, safety-gate secret) are file-backed + hardened under `~/.flinttrade/`, never in `.env`. Native-adapter broker credentials live in the encrypted gateway vault (`gateway/credentials.py`, Fernet + per-row DEK); the OpenAlgo bridge path keeps broker auth inside OpenAlgo and holds only the OpenAlgo API key. Report vulnerabilities through `security.md` rather than public issues.

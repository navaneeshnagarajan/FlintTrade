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

Before opening or merging any PR, fetch `origin`, verify `origin/main` against the live remote, and check whether local `main` and the PR branch include it. Bring the work up to date and repeat affected verification before proceeding; never rely on a previously fetched base. Updating the base does not grant push or merge permission.

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
5. **Human-gated (do not attempt autonomously):** Groww session approval, Kotak Neo funded Live unlock / order-safety proof, funded order smoke, W6 spec, B3 order-capable MCP decision.

**Non-negotiables (verify before claiming done):**
- Every reachable live order mints a `SafetyContext` via `gate_order`/`gate_broker_write` → `BrokerRouter`; `gateway/tests/test_no_legacy_order_path.py` is the guard — run it after touching anything order-adjacent.
- MERGE the union of capabilities — never delete a duplicate blind; a pure-dead-path exception must be stated in the commit message.
- Frontend live-order entrypoints stay fail-closed (`assertNativeWriteTargetReadyOrThrow`); broker store selectors use composite `source:broker:account_id` keys.
- Widget/broker/package count pins move in lockstep: `widgetFactory.test.ts` (catalogue), `test_adapter.py` (BROKER_CATALOG), `capabilities.test.ts` (site), `test_project_structure.py` (packages).
- Lockfile changes require `python scripts/generate-notice.py` + commit, or the Supply Chain workflow fails on NOTICE drift.
- Full local gate before any push (and push only with explicit maintainer permission): whole pytest tree, ruff, `tsc --noEmit`, full terminal vitest (CI shards under-cover; run everything), terminal build, site vitest, secrets scan.

## Security & Configuration

Never commit `.env`, API keys, broker credentials, fund amounts, order IDs, hostnames, or personal IPs. Start from `.env.example`. Secrets (master password, JWT secret, API-key pepper, safety-gate secret) are file-backed + hardened under the platform workspace dir (`~/.flinttrade/` on Linux, `~/Library/Application Support/flinttrade/` on macOS, `%APPDATA%/flinttrade/` on Windows), never in `.env`. Native-adapter broker credentials live in the encrypted gateway vault (`gateway/credentials.py`, Fernet with a per-row random salt + PBKDF2-derived key from the master password); the OpenAlgo bridge path keeps broker auth inside OpenAlgo and holds only the OpenAlgo API key. Report vulnerabilities through `security.md` rather than public issues.

<!-- reticle:begin (managed by `reticle init` — edit outside these markers) -->
## Verifying with Reticle

This app is instrumented by **Reticle**, an in-app verification layer exposed as `reticle_*` MCP tools and the `npx @reticlehq/server` CLI (always through npx: Reticle's server is not installed into this project). Verifying is part of "done", not an optional extra.

**Verify when you have changed something a user can see or do.** A component, a form, a route, a request, a piece of state that reaches the screen. Do it BEFORE telling the user it is complete. Reading the diff proves nothing and unit tests do not run the app.

**Do not reach for Reticle when the change cannot show up in the running app.** It costs tool calls and the user's patience, and a verdict over an unrelated flow proves nothing about what you changed. Skip it for: documentation, comments, tests, build config, CI, dependency bumps with no user-facing effect, backend or CLI work with no UI surface, and any change to a project that is not a running web app. Say in one line that you skipped verification and why, rather than silently not doing it.

**How to verify:**

- Drive the flow with `reticle_act_and_wait({ ref, action, until })`. It names the consequence you expect BEFORE the action, which is the difference between a check and a rationalisation.
- Batch a multi-step journey (a login, a form) into one `reticle_act { steps: [...] }` rather than one round trip per field.
- Read the surrounding evidence with `reticle_look { action: "page" | "state" }` and `reticle_observe { action: "network" | "console" }`.
- **Only `reticle_act_and_wait` and `reticle_assert` produce a verdict.** `reticle_act` and everything else move or read the app and prove nothing, so a session ending without one of those two has no result however many tools it used.
- Covered flows: `npx @reticlehq/server gate` reports which recorded flows the changed files affect and whether they still pass.

**Setting Reticle up? You are mid-sequence — do not stop until a verdict exists.** The whole of it
is: instrument the app → get a dev server running → open the app in a browser → drive one flow →
report the verdict. Every step is yours to do, and none of them needs the user. Stopping short leaves an app that
looks installed and can verify nothing, which is the commonest way this goes wrong. `/reticle`
carries the recovery ladder; never report the install as finished without a verdict to point at.

**Nothing connected? Get the app running.**

**A dev server already running when `reticle init` ran does not have Reticle in its bundle.** It read the build config at boot; `init` edited it afterwards. It serves the old bundle and no session appears. In order:

1. **A dev server was already running?** Restart it, then hard-reload the tab. "Something is listening" does not mean the right bundle is served.
2. **Nothing was running?** Start it in the BACKGROUND and say so in one line. `reticle_session { action: "list" }` gives you this project's own dev command in `next_action`; use that, never compose one. Started after `init`, it needs no restart.

Stopping to ask is how a verification turn ends with nothing verified.

Four guards, none optional:

1. **Never run two at once.** One dev server on the app's port. Restarting a stale one means stopping it first, not starting a second alongside it.
2. **Never guess the command.** It comes from `package.json` scripts. No recognisable dev script means say so and stop, not invent one.
3. **Never kill anything you did not start**, and never a daemon or a port holder. The one exception is the restart above, and say in one line that you did it.
4. **The permission prompt belongs to your host.** Never bypass, suppress or auto-approve it, and take a refusal as the answer.

A dev server that is already running does not pick up an edited build config or a newly created plugin file — restart it and hard-reload the tab. And if a server IS listening and still nothing connects, the cause is the SDK not loading in the page, not a missing dev server; do not tell the user to start one they are already running.

**Finish `src/reticle-dev.ts` before you claim setup is done.** `init` writes it and cannot always fill it in: a store that needs an argument only reading the code supplies (Jotai atoms, an XState actor, a TanStack `queryClient`) is left as a commented `registerStore` line. A file that registers nothing looks exactly like a finished one, and `reticle_look { action: "state" }` then returns empty forever — which is indistinguishable from an app that has nothing to report, so it reads as success. Uncomment the line, complete it, and prove it by driving one flow and seeing your keys come back. If `init` told you to restart your client, this is the job waiting for you on the other side of that restart.

**Verify each feature as you finish it, not all of them at the end.** Asked for four, build one, drive it, get a verdict, then start the second. A red verdict after four builds has four suspects; after one it has none.

**Capture what a change is FOR while you are building it, not afterwards.** The business outcome a change is meant to produce is known only while the change is being made. Pass `intent` when a flow is saved, so the saved flow carries the reason it exists. A flow without one replays for months and then reports "step 3 failed" instead of what stopped being true for a user.

**Honesty, which is the whole point:**

- **`verified: "unknown"` is not a pass.** It means Reticle drove the app and could not tell what happened; `verifiedReason` says which clause decided that. Report it as unknown, never as working.
- **`verified: "no-fault"` is not a pass either.** It means nothing was DECLARED to prove: the page settled and no channel complained, but you asserted nothing, so there is no verification. You get it whenever `until` is omitted. Name a consequence the action changes — a signal, a request, a route, or store state — and call again.
- **Never weaken a check to make it green.** Downgrading, skipping or deleting an assertion is a finding, not a fix.
- **If Reticle cannot run** (no daemon, or this is not a running web app), say so. Do not skip verification silently.
- **Setup is not finished until one real flow has been driven and produced a verdict.** `init` exiting 0, the tools appearing, and a session being listed are all things that happen before anything has been verified.

**The `/reticle` skill runs this whole loop for you** — detect, connect, drive one flow, report. If your client does not have it, install it once: `/plugin marketplace add reticlehq/reticle` then `/plugin install reticle@reticlehq` in Claude Code, or `npx skills add reticlehq/reticle` anywhere the skills CLI works.

**A tool you need is missing?** Call `reticle_tools` before assuming it: this surface merges several families behind an `action`, so what looks absent is usually one argument away. It is the verify loop and nothing else on purpose, and a daemon started with `RETICLE_ADVERTISE_ALL_TOOLS=1` advertises the wider set — it reads that at startup, so it takes effect on the next one.

**Report Reticle's own defects with `reticle_session { action: "feedback" }` the moment you notice**, then carry on with your task. You are the user Reticle is built for and the only one who can say what it cost you, and that knowledge is gone when your context is.

📄 **The rest is in [RETICLE.md](./RETICLE.md): what to do when the tools are missing, when a result carries `version_skew` or `update_available`, when `reticle_look { action: "state" }` comes back empty, and how to write a feedback report that can be acted on. Read it when you hit one of those, not before.**
<!-- reticle:end -->

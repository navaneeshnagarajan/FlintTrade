# Continuous Integration

This document describes how FlintTrade's GitHub Actions pipeline runs,
what each workflow covers, and how to interpret a failed job. Every
contributor whose change touches code (Python, TypeScript, Rust) or a
workflow YAML should read this once.

> The goal is **zero CI errors after every push**. The mechanics below
> exist to make that achievable without ballooning runner usage and
> without burning out reviewers on cosmetic failures.

---

## 1. Workflow inventory

| Workflow | Trigger | Runner cost | Notes |
|---|---|---|---|
| `test.yml` | push to `main` / `dev`; non-draft PR (no `paths` / `paths-ignore` on the PR trigger) | `changed-surfaces` classifier + 9 Linux jobs | The main quality gate. Includes Electron typecheck, Vitest, bundle and Linux directory-package verification. Every non-draft PR to `main`/`dev` instantiates the workflow so required check contexts exist. Documentation, site, and former inert-file edits still run `python-tests`, `node-core-tests` and `secrets-check`; the expensive lanes gate on `changed-surfaces`. |
| `supply-chain.yml` | push to `main` / `dev`; non-draft PR (paths-ignore); weekly cron (Mon 03:00 UTC); manual dispatch | Linux jobs per-push/PR; the macOS + Windows jobs (`cross-platform-smoke`, `windows-acl-test`) gate to the weekly cron / `workflow_dispatch` only (§7) | Full supply-chain gate: python/rust/node audits, licence + provenance checks, NOTICE drift, hashed-install enforcement, Windows secret-file ACL hardening, cross-platform install smoke, lockfile drift, and the CLA GPG binding (external-fork `pull_request` events only — skipped on push/schedule/owner and same-repo bot merges). |
| `site.yml` | push to `main` / `dev`; non-draft PR (path-filtered to site, terminal, design-system, package manager, docs, package README, and `site.yml` itself) | 1 Linux job | Typechecks, tests and builds the documentation site (Next.js). Documentation changes still instantiate `test.yml` (cheap lanes only) and also run this workflow. |
| `nightly-cross-platform.yml` | weekly cron (Sun 03:00 UTC); manual dispatch | Python on macOS, Windows and Ubuntu 26.04; Electron directory packages on macOS, Windows and Linux | Catches slow-burn platform and packaging regressions before they accumulate. |
| `desktop-release.yml` | manual dispatch only; Release Please supplies the immutable release tag and expected commit SHA | macOS universal + Windows x64 + Linux x64/ARM64 | Builds the four Electron installers, verifies the packaged contract, writes `SHA256SUMS.txt`, attests provenance and publishes only to an empty release target. |
| `release-please.yml` | push to `main` | Linux control jobs | Maintains the release PR/version contract and dispatches `desktop-release.yml` after a release tag is created. |
| `refresh-vuln-snapshot.yml` | weekly cron (Sun 04:00 UTC); manual dispatch | 1 Linux job | Refreshes the offline OSV vuln snapshot used by `pip-audit-with-allowlist.py` and opens a PR for the founder to merge, keeping the snapshot inside its freshness window. |
| `status-report.yml` | weekly cron (Mon 07:00 UTC); manual dispatch | 1 Linux job (~5 minutes) | Emits a repo-health snapshot artefact. |
| `key-freshness.yml` | daily cron; manual dispatch; push touching `packages/apps/desktop/resources/bootstrap/checksums/**` | 1 Linux job (~1 minute) | Fails while the pinned Node release key is expired, revoked, or expiring inside 30 days. Node releases are signed by whichever release manager cut them, using their own key with their own expiry, so this is upstream state we consume — it can be refreshed, never regenerated. `gpg` exits 0 on an expired key and reports `EXPKEYSIG` out of band, so a check that only reads the exit status passes indefinitely against a dead key. Revocation is upstream-only state — the packet lands on the keyserver, never in the mirrored `.asc` — so this job fetches the keyserver copy and merges it into the same keyring before reporting; that is why the per-PR `--offline` step in `test.yml` cannot replace it. Availability is handled separately from trust: an unreachable or unparseable keyserver prints `Upstream: NOT CHECKED` and leaves the exit code alone. |
| `toolchain-freshness.yml` | daily cron; manual dispatch | 1 Linux job (~1 minute) | Fails when a pinned or floor version is EOL or has fallen outside the N-1 band declared in `flint.toml` `[requirements]`, reading nodejs.org/dist, the Node LTS schedule, the npm registry, uv's GitHub releases and the CPython EOL calendar. `pnpm audit` audits the dependency tree and pnpm is not a node in the lockfile, so nothing else can see toolchain binaries. Network-tolerant: an unreachable source skips with a note rather than failing an unrelated PR. |
| `claude.yml` | issue / PR comment containing `@claude` | 1 Linux job per invocation | Zero per-push cost. Runs only when explicitly tagged. |
| `claude-code-review.yml` | PR opened / ready-for-review / reopened (paths-ignore + draft guard) | 1 Linux job per qualifying transition | Skips `synchronize` events to avoid running on every PR commit. |

### The nine per-push Ubuntu jobs

`test.yml` splits the Python, TypeScript, and Rust test suites across nine
parallel jobs to keep wall-clock time low:

1. `python-tests` — full pytest suite.
2. `node-core-tests` — Vitest for non-widget terminal code (`lib`, `stores`,
   `atoms`, `services`, `test-utils`, `hooks`, `layout`, `admin`, `__tests__`).
3. `node-widget-tests-1` — `src/widgets/trading/` + utility widgets A–H.
4. `node-widget-tests-2a` — utility widgets M–S.
5. `node-widget-tests-2b` — utility widgets S–W + AIBackends/AITeam/Obsidian/
   TradeJournal (`TradeIdea` excluded — OOMs the 7 GB runner).
6. `node-widget-tests-3` — `src/widgets/analysis/`, `routes/`, `tools/`,
   `components/`, `chrome/`, and the safety-relevant `widgets/orders/` +
   `widgets/account/`.
7. `secrets-check` — an inline two-pattern grep scan (NOT gitleaks) over the
   tree.
8. `rust-ticks-tests` — `cargo test` on the `packages/core/ticks` crate (the
   tick-level backtest simulator). This is the only job that runs the crate's
   unit tests; `cargo audit` in `supply-chain.yml` checks advisories, not
   behaviour. Cached via `Swatinem/rust-cache` so the per-push compile stays
   cheap.
9. `electron-desktop-tests` — strict Electron TypeScript, the full desktop
   Vitest suite, main/preload bundle, Linux x64 directory package and packaged
   security-contract verification on `ubuntu-24.04`.

All nine must be green for the workflow to be reported as passing. The shard
path lists are hand-maintained, but `tests/test_ci_vitest_shard_coverage.py`
(in `python-tests`) fails CI if any terminal `*.test.ts(x)` file runs in no
shard — so coverage stays complete apart from the allowlisted `TradeIdea`.

### Why Ubuntu-only for per-push

`ubuntu-latest` is the cheapest runner class on GitHub Actions, and the
codebase is portable enough that 99 % of regressions surface there
first. macOS and Windows coverage is preserved by the weekly nightly
workflow, which is enough to catch slow-burn platform regressions
without paying for them on every commit.

Anyone adding a new platform matrix MUST add it to the nightly workflow,
not `test.yml`. Per-push macOS or Windows jobs are treated as CI-budget
regressions and reverted on review.

---

## 2. Concurrency and skip rules

Three mechanisms keep CI inexpensive and signal-rich:

- **`concurrency: cancel-in-progress: true`** on `test.yml` and
  `claude-code-review.yml`. Back-to-back pushes only run the latest
  commit's matrix — the previous one is cancelled automatically.
- **Draft-PR guard.** Every job is gated on
  `github.event.pull_request.draft != true`. Open PRs as drafts while
  iterating; mark "ready for review" to trigger CI.
- **No PR-level `paths` or `paths-ignore` on `test.yml`.** A positive or
  negative path filter on the `pull_request` trigger would omit every required
  Test check context for PRs outside that filter. Push may still use
  `paths-ignore`. Cost control for genuinely inert files (`.local/**`, `notice`,
  `LICENSE`, `.gitignore`, `.gitattributes`, `.editorconfig`,
  `.github/ISSUE_TEMPLATE/**`, `claude*.yml`, `status-report.yml`) and for
  documentation/site-only edits lives in the `changed-surfaces` classifier, not
  in the PR trigger.
- **Documentation and the site are deliberately NOT path-ignored on the PR
  trigger.** `python-tests` carries `tests/test_windows_command_docs.py`, the
  guard that stops a Windows setup page prescribing `make` or a command fence
  chaining with `&&`, and `packages/apps/site` carries the `desktop-copy`
  assertions that pin the one-command install strings. Ignoring those paths
  skipped exactly the jobs that police them, so a docs-only PR could reintroduce
  the defect and still merge green. `python-tests`, `node-core-tests` and
  `secrets-check` therefore always run.
- **The `changed-surfaces` classifier keeps that cheap.** It diffs the push or PR
  range with plain git and reports `code=false` when every changed path is
  documentation, site content, or a former inert surface listed above; the four
  widget shards, `rust-ticks-tests` and `electron-desktop-tests` gate on it. It
  fails **open** — an unresolvable range (first push to a branch, force push,
  shallow history) reports `code=true` and the full matrix runs. Changes under
  `docs/**` still run `site.yml` because that workflow includes documentation in
  its positive path filter.

---

## 3. Per-commit checklist (local side)

If the local checklist passes, CI catches drift rather than regressions.

One command per line — Windows PowerShell 5.1 has no `&&` operator, so none of
these may be chained with it.

1. **Before you commit:**
   - `pnpm --filter @flinttrade/terminal typecheck` — terminal type-check.
   - `npx vitest run <changed-tests>` from `packages/apps/terminal` — or
     `pnpm --filter @flinttrade/terminal test` if you touched the widget
     surface.
   - `python -m pytest <changed-tests> --tb=short --import-mode=importlib`
   - `python scripts/ft.py lint` — runs `ruff check packages/ tests/` and then
     the terminal's `eslint src --max-warnings=0` lint gate
     (`react-hooks/rules-of-hooks`, `react-hooks/exhaustive-deps`,
     `local/no-explicit-any`, `local/no-ts-suppression`), the same
     command `node-core-tests` runs. Same scope as `make lint`,
     shell-independent on every platform. Both halves always run and the first
     non-zero exit code wins; a missing ruff or a missing
     `packages/apps/terminal/node_modules` skips that half with a hint rather
     than failing.
2. **Before you push:**
   - `git status` clean — no stray `__init__.py` or `package-lock.json`
     left out of the commit.
   - `python scripts/ft.py test` (POSIX alias: `make test`) if anything inside
     `packages/*/src/` changed.
3. **Doc-only commits** no longer skip `test.yml`. `python-tests`,
   `node-core-tests` and `secrets-check` always run — the first carries
   `tests/test_windows_command_docs.py`, the guard that stops a Windows page
   prescribing `make` or a fence chained with `&&`, so ignoring docs used to
   skip precisely the job that polices docs. Only the expensive lanes (the four
   widget shards, `rust-ticks-tests`, `electron-desktop-tests`) gate on the
   `changed-surfaces` classifier. Changes under `docs/**` additionally run the
   site typecheck, tests and build through `site.yml`.
4. **Draft PRs are free.** Open as draft, iterate, mark "ready for
   review" when you want CI to run.

---

## 4. Defence-in-depth layers

| Layer | Mechanism | Catches |
|---|---|---|
| 1 | Local pre-commit (`tsc --noEmit` + `vitest run` + `pytest --tb=short` + `ruff check`) | Most syntactic and unit-test regressions. |
| 2 | Contract tests (e.g. `packages/core/core/tests/test_orders_contract.py` parses `api.ts` for `postOrder("leaf", ...)` calls and asserts the matching Flask route exists) | Frontend ↔ backend route drift. |
| 3 | `cancel-in-progress: true` on `test.yml` and `claude-code-review.yml` | Back-to-back-push runner amplification. |
| 4 | Draft-PR guard on every test job | Wasted CI on work-in-progress PRs. |
| 5 | No PR-level `paths`/`paths-ignore` on `test.yml`, plus the `changed-surfaces` classifier gating expensive lanes on doc/site/inert-only edits | Routine doc or inert-file updates burning runner minutes — without omitting required check contexts or blinding the guards that police documentation. |
| 6 | `continue-on-error: true` confined to the nightly workflow — never `test.yml` | Cosmetic matrix entries inflating perceived failure rate. |
| 7 | Local stop-time review gate (`/codex:setup --enable-review-gate`) — **legacy/optional local contributor option**, not a required hosted CI job. Its optional status does not retire Codex build agents or replace the canonical build agents (Codex or Claude) → Claude ultracode multi-agent review panels → maintainer pipeline. | High-level design / contract / safety issues unit tests cannot see. |
| 8 | Nightly cross-platform matrix (Sunday cron) | Slow-burn Python and Electron-package regressions on macOS, Windows and Linux before they pile up. |

---

## 5. How to read a failed CI run

### Step 1 — find the failed job

```bash
gh run list --limit 5
gh run view <run-id>
```

`gh run view` prints a tree of jobs and their conclusions. Look for the
red ✕.

### Step 2 — read the failing step

```bash
gh run view <run-id> --log-failed
```

This dumps **only** the lines from the failed step, not the entire
workflow log. It is the single most useful CI command — bookmark it.

### Step 3 — reproduce locally

The per-push jobs are designed to be reproducible without a runner. Map the
failed job to its local command:

All terminal rows are run from `packages/apps/terminal` — `cd` there first, on
its own line. Do not chain the `cd` with `&&`; Windows PowerShell 5.1 has no
`&&`.

| Job | Local command |
|---|---|
| `python-tests` | `python scripts/ft.py test` (POSIX alias: `make test`) |
| `node-core-tests` | `npx vitest run --pool=forks src/lib/ src/stores/ src/atoms/ src/services/ src/test-utils/ src/hooks/ src/layout/ src/admin/ src/__tests__/` |
| `node-widget-tests-1` | `... npx vitest run src/widgets/trading/ src/widgets/utility/{AIAdvisor,Alerts,AuditTrail,Calculator,CurrencyConverter,EarningsCalendar,EconomicCalendar,ExpiryCountdown,FundingRate,GlobalIndices,Health}/` |
| `node-widget-tests-2a` | `... npx vitest run src/widgets/utility/{MarketClock,MarketSummary,News,PositionSizing,ProfitTarget,Scanner}/` |
| `node-widget-tests-2b` | `... npx vitest run` over `src/widgets/utility/{StrategyTemplates,TickSpeed,Ticker,Watchlist,AIBackends,AITeam,Obsidian,TradeJournal}/` (one dir per invocation; `TradeIdea` excluded) |
| `node-widget-tests-3` | `... npx vitest run src/widgets/analysis/ src/routes/ src/tools/ src/components/ src/chrome/ src/widgets/orders/ src/widgets/account/` |
| `secrets-check` | the inline two-pattern `grep` loop from `test.yml` (NOT gitleaks) |
| `rust-ticks-tests` | `cargo test --manifest-path packages/core/ticks/Cargo.toml` (or `make ticks-test`, POSIX only) |
| `electron-desktop-tests` | `python scripts/ft.py desktop-test`, then `python scripts/ft.py desktop-build`, then the Linux `electron-builder --dir` package and `pnpm --filter @flinttrade/desktop verify:package` |

The exact per-shard path lists live in `.github/workflows/test.yml`; treat that
as the source of truth (the shard-coverage guard keeps it complete).

### Step 4 — fix and push

Conventional commit, no `--no-verify`, no `dangerouslySkipPermissions`.
If a pre-commit hook breaks because of your change, fix the hook in the
same commit.

---

## 6. Common CI failure shapes

| Symptom | Likely cause | Fix |
|---|---|---|
| `pytest` reports `ImportError: cannot import name 'X'` | New module not added to `__init__.py`, or import is relative inside `packages/*/src/`. | Use absolute imports; add to `__init__.py` if it is a public surface. |
| `vitest` reports `Cannot find module '@/...'` | Path alias not honoured in the test config. | Ensure `vite.config.ts` (which holds the Vitest `test:` config) reads the same `@` alias as `tsconfig.json`. |
| `ruff` fails with new lint codes | Newer ruff rule activated. | Run `ruff check --fix` locally, commit the autofix. |
| `secrets-check` flags a "secret" that is a public sample | The inline grep matched a `BROKER_API_KEY=` or `sk-…` pattern. | Move the sample under `tests/fixtures/` or restructure it so it does not match the two grep patterns (there is no allowlist pragma — it is a raw grep, not gitleaks). |
| Cross-platform job fails on Sunday but Linux is green | Path-separator or filesystem-case issue. | Reproduce in a Linux VM with `WIN_COMPAT=1` env, or switch to `pathlib`. |
| Workflow is queued for a long time | Runner contention or workflow concurrency cancellation chain. | Wait. If a real outage, GitHub Status will say so. |

---

## 7. CI usage guardrails

### Why this section exists

FlintTrade is a public, multi-contributor repository, so cross-platform
coverage genuinely matters, but runner usage has to stay deliberate and
bounded. The CI policy is designed around GitHub Actions budget and reliability
best practices. The expensive pattern this repo avoids is:

- **Daily** scheduled runs, on top of every push and pull request.
- **Multi-platform matrices on the frequent triggers** — macOS runners
  are billed at **10x** the Linux minute rate and Windows at **2x**, so a
  single push fanned out into roughly **13x** the minutes of a
  Linux-only run.
- **Jobs with no `timeout-minutes`**, which can each consume minutes up to
  the six-hour runner default if they hang.
- A large parallel-job count on frequent triggers.

The fix is to keep frequent CI Linux-only, move cross-platform checks to weekly
or manual triggers, require job timeouts, and add a guardrail so no future
change quietly re-introduces the heavy footprint.

### The rules (enforced in CI)

`tests/test_workflow_policy.py` loads **every** `.github/workflows/*.yml`
with PyYAML and asserts the following. It runs inside the normal
`python-tests` job, so a workflow that breaks the policy fails CI like any
other test, with an assertion message naming the offending workflow and
job.

1. **No expensive runner on a cheap, frequent trigger.** A job that uses a
   `macos-*` or `windows-*` runner must **not** be reachable from a `push`
   or `pull_request` trigger, nor from a **daily-or-more-frequent**
   `schedule` cron. macOS / Windows coverage is allowed only under a
   **weekly-or-less-frequent** `schedule` *or* a manual
   `workflow_dispatch`. A release-tag push is still a push, so
   cross-platform jobs gate behind `workflow_dispatch` / schedule, never an
   unconditional push.

   The check resolves the runner OS through both the literal `runs-on`
   value **and** any `strategy.matrix` list (so `runs-on: ${{ matrix.os }}`
   with `matrix.os: [ubuntu-latest, macos-latest]` is understood), and it
   honours a job-level `if:` that confines the job to safe events — e.g.
   `if: github.event_name == 'schedule' || github.event_name ==
   'workflow_dispatch'`. Anything it cannot prove safe **fails closed**.

2. **Every job declares `timeout-minutes`.** No exceptions for runnable
   jobs. Sensible values: lint **~10**, tests **~30**, cross-platform
   **~45**. (A pure reusable-workflow call — a job that is only `uses:`
   with no `steps:` — is exempt, because its timeout lives in the called
   workflow.)

3. **Every workflow declares a top-level `permissions` block.** Default to
   least privilege (`permissions:` → `contents: read`) and widen only the
   specific scope a job needs (for example `pull-requests: write` only on a
   workflow that comments on PRs).

### How this maps onto the live workflows

- Per-push / per-PR work stays on **`ubuntu-latest`** only (the cheapest
  runner class): `test.yml`, the Linux audits in `supply-chain.yml`, and
  `site.yml`.
- macOS / Windows coverage lives in **`nightly-cross-platform.yml`**
  (weekly Sunday cron + `workflow_dispatch`) and in the
  `cross-platform-smoke` / `windows-acl-test` jobs of `supply-chain.yml`,
  which are gated to `schedule` / `workflow_dispatch` even though that
  workflow also runs Linux jobs on push.
- The four-build-leg installer matrix lives in **`desktop-release.yml`**, which
  is `workflow_dispatch` only. Release Please supplies the immutable tag and
  expected commit SHA; a build-only manual dispatch publishes no GitHub assets.
- Scheduled workflows use a **weekly-or-less** cadence
  (`refresh-vuln-snapshot.yml`, `status-report.yml`,
  `nightly-cross-platform.yml`, and the `supply-chain.yml` cron) — never a
  daily one.

If you genuinely need a daily run or a macOS / Windows job on push, the
policy test will stop you. That is the intended behaviour: change the
design (move it to a weekly schedule or behind `workflow_dispatch`), not
the test.

---

## 8. Adding a new workflow

If you add a new GitHub Actions workflow:

- Default to `ubuntu-latest`. macOS / Windows must sit behind a
  weekly-or-less `schedule` or `workflow_dispatch` only — never `push` /
  `pull_request` / daily cron (§7).
- Add a top-level `permissions` block (least privilege: `contents: read`,
  widened only where a job needs it).
- Set `timeout-minutes` on **every** job (lint ~10, tests ~30,
  cross-platform ~45).
- Add `paths-ignore` if the workflow does not need to fire on doc-only
  changes.
- Add a `concurrency` block with `cancel-in-progress: true` for any
  workflow that can be triggered rapidly.
- `tests/test_workflow_policy.py` enforces the first three points — run
  `python -m pytest tests/test_workflow_policy.py -v --import-mode=importlib`
  before you push.
- Update this document in the same commit.

---

## 9. When CI behaves unexpectedly

1. `gh run list --limit 50 --json conclusion,createdAt` — look for a
   burst of red runs (force-pushes and cancellations can still consume
   runner time even with concurrency cancellation, because cancelled
   jobs spend the first 10-30 seconds starting up before they are
   killed).
2. Check `nightly-cross-platform.yml` — confirm it is on the weekly
   schedule, not a daily one (a daily macOS cron is significantly more
   expensive than weekly).
3. Check `claude.yml` invocations — a runaway `@claude` thread can fire
   a job per comment.
4. Check artefact retention — `actions/upload-artifact@v4` defaults to
   90 days. For large bundles (coverage HTML, screenshots), set
   `retention-days: 7`.

---

## Resolved: `electron-desktop-tests` Linux containment failures (2026-07-23 → 2026-07-26)

Red on `main` since a6f92464, the Electron source-bootstrap migration; green
through 07a0f434 on 2026-07-20; fixed on this branch on 2026-07-26. Roughly 19
failing locations in `electron/bootstrap-io.test.ts` and `electron/bootstrap.test.ts`
— the process-containment cases — passed on macOS (953 tests) and failed on the
Ubuntu runner.

**Root causes (three, all downstream of detection, as the measurements said):**

1. **Drain iterations were quadratically expensive on Linux.** Each sweep
   re-parsed the full env-laden `ps` snapshot (~189 KB on the runner) with
   multiple byte-at-a-time `while read` here-doc passes in dash, so the
   TERM→KILL escalation ladder (SIGKILL from the 11th sighting) took several
   seconds — long after an escapee's marker timers fired. The snapshot is now
   prefiltered with `grep` (C speed) so each pass reads only candidate lines,
   and escaped-session processes that retain the containment marker are
   SIGKILLed on first sighting: they never receive the process-group TERM and
   are precisely the violation the guardian exists for, so there is no graceful
   window to honour. In-group members keep the TERM grace ladder.
2. **A drained-descendant report rewrote timeout/cancel exit codes.** The
   settled proof's `descendants=1` flag set `descendantLeak` unconditionally,
   which outranks `timeout` in the exit-code mapping — so a timed-out command
   whose dying child was merely *sighted* by the first sweep reported exit 1
   instead of 124. On macOS the child was always reaped before the first
   snapshot; on Linux it was often still visible. The leak flag now only
   applies when the run has no terminal reason of its own.
3. **Zombies counted as live descendants.** The sweep now requests `-o state=`
   and skips `Z*` entries — a zombie cannot be signalled and only added a
   phantom drain iteration.
4. **A fake-clock leak turned one flake into a file-wide cascade.** The
   force-kill-timer test ran its whole cancel flow under `vi.useFakeTimers()`,
   which also froze every `delay()`/retry inside the product cancel path; after
   any heavy containment test it hung, vitest abandoned it mid-await (so its
   own `finally` restore never ran), and every later timer-dependent test in
   the file inherited the frozen clock — the contiguous 5 s/15 s timeout block
   that ends exactly where the timer-free filesystem tests begin. The test now
   verifies the same cleared-timer behaviour on the real clock, and the file's
   `afterEach` restores real timers defensively.

**Two measurement traps, both measured, both of which cost a lot of time —
they remain the durable lesson:**

**1. A plausible hypothesis about `ps` formatting is FALSE.** The containment
sweep tags processes with a `FLINTTRADE_PROCESS_ANCHOR` environment marker and
finds them in `ps` output. It is tempting to conclude that procps does not
append the environment when an explicit `-o command=` format is given. Measured
on the runner:

```
ps axeww -o …command= : status=0 markerFound=TRUE  bytes=189656
/proc/<pid>/environ   : exact-match count=1
drain-loop replay     : escaped_matched=[4732]
```

Enumeration, parsing and detection all work correctly on Linux. **The bug is
downstream of detection.** Chasing this cost two reverted cgroup
implementations and a `/proc` code path that fixed nothing.

**2. `gh run view --log-failed` on an IN-PROGRESS run returns a PARTIAL log.**
Failure counts read from it are far below reality — readings of "3 failing
locations" came from partial logs, while a control run of the identical commit
returned 19. Wait for the run to complete, and re-run the same commit before
believing any delta between two numbers.

Reproduce on ubuntu-24.04 + Node 22 (Docker is sufficient). This is fail-closed
containment — the guardian that stops orphaned bootstrap processes surviving —
so do not relax an assertion or extend a timeout to get green; the 2026-07-26
fix strengthened enforcement (faster sweeps, immediate SIGKILL for
session-escapees) rather than weakening any assertion.

Fuller history, including the approaches tried and reverted along the way,
is kept in the maintainer's private working notes; the essentials are
recorded here.

---

*Owners: any contributor who touches a file under `.github/workflows/`
should update this document in the same commit so the contract stays
current.*

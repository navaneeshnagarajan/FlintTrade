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
| `test.yml` | push to `main` / `dev`; non-draft PR | 8 Linux jobs (~70 minutes wall-clock) | The main quality gate. Uses `paths-ignore` so doc-only commits skip the matrix entirely. |
| `supply-chain.yml` | push to `main` / `dev`; non-draft PR (paths-ignore); weekly cron (Mon 03:00 UTC); manual dispatch | Linux jobs per-push/PR; the macOS + Windows jobs (`cross-platform-smoke`, `windows-acl-test`) gate to the weekly cron / `workflow_dispatch` only (§7) | Full supply-chain gate: python/rust/node audits, licence + provenance checks, NOTICE drift, hashed-install enforcement, Windows secret-file ACL hardening, cross-platform install smoke, lockfile drift, and the CLA GPG binding (external forks only). |
| `site.yml` | push to `main` / `dev`; non-draft PR (path-filtered to site, terminal, design-system, package manager, docs, package README, and workflow files) | 1 Linux job | Typechecks, tests and builds the documentation site (Next.js). Skipped unless a site-relevant path changes. |
| `nightly-cross-platform.yml` | weekly cron (Sun 03:00 UTC); manual dispatch | 1 macOS + 1 Windows | Catches slow-burn platform regressions before they accumulate. |
| `refresh-vuln-snapshot.yml` | weekly cron (Sun 04:00 UTC); manual dispatch | 1 Linux job | Refreshes the offline OSV vuln snapshot used by `pip-audit-with-allowlist.py` and opens a PR for the founder to merge, keeping the snapshot inside its freshness window. |
| `status-report.yml` | weekly cron (Mon 07:00 UTC); manual dispatch | 1 Linux job (~5 minutes) | Emits a repo-health snapshot artefact. |
| `claude.yml` | issue / PR comment containing `@claude` | 1 Linux job per invocation | Zero per-push cost. Runs only when explicitly tagged. |
| `claude-code-review.yml` | PR opened / ready-for-review / reopened (paths-ignore + draft guard) | 1 Linux job per qualifying transition | Skips `synchronize` events to avoid running on every PR commit. |

### The eight per-push Ubuntu jobs

`test.yml` splits the Python, TypeScript, and Rust test suites across eight
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

All eight must be green for the workflow to be reported as passing. The shard
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
- **`paths-ignore` for doc-only commits.** The matrix is skipped if a
  commit only touches `*.md`, `docs/**`, `.local/**`, `notice`,
  `LICENSE`, `.gitignore`, `.gitattributes`, `.editorconfig`,
  `.github/ISSUE_TEMPLATE/**`, or the `claude*.yml` / `status-report.yml`
  workflows themselves.

---

## 3. Per-commit checklist (local side)

If the local checklist passes, CI catches drift rather than regressions.

1. **Before you commit:**
   - `cd packages/apps/terminal && npx tsc --noEmit` — terminal type-check.
   - `cd packages/apps/terminal && npx vitest run <changed-tests>` — or the
     full suite if you touched the widget surface.
   - `python -m pytest <changed-tests> --tb=short --import-mode=importlib`
   - `ruff check packages/*/src/`
2. **Before you push:**
   - `git status` clean — no stray `__init__.py` or `package-lock.json`
     left out of the commit.
   - `make test` if anything inside `packages/*/src/` changed.
3. **Doc-only commits** (paths listed above) skip CI by design. Use this
   to keep noise down when correcting a typo or adding a screenshot.
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
| 5 | `paths-ignore` for doc-only commits | Routine doc updates burning runner minutes. |
| 6 | `continue-on-error: true` confined to the nightly workflow — never `test.yml` | Cosmetic matrix entries inflating perceived failure rate. |
| 7 | Stop-time review gate (`/codex:setup --enable-review-gate`) — **legacy/optional**: Codex was retired from the review pipeline (2026-06-05), so this gate is no longer part of the standard flow (claude ultracode panels → maintainer). Kept only for contributors who still run a local Codex CLI | High-level design / contract / safety issues unit tests cannot see. |
| 8 | Nightly cross-platform matrix (Sunday cron) | Slow-burn macOS / Windows regressions before they pile up. |

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

The seven per-push jobs are designed to be reproducible without a
runner. Map the failed job to its local command:

| Job | Local command |
|---|---|
| `python-tests` | `make test` |
| `node-core-tests` | `cd packages/apps/terminal && npx vitest run --pool=forks src/lib/ src/stores/ src/atoms/ src/services/ src/test-utils/ src/hooks/ src/layout/ src/admin/ src/__tests__/` |
| `node-widget-tests-1` | `... npx vitest run src/widgets/trading/ src/widgets/utility/{AIAdvisor,Alerts,AuditTrail,Calculator,CurrencyConverter,EarningsCalendar,EconomicCalendar,ExpiryCountdown,FundingRate,GlobalIndices,Health}/` |
| `node-widget-tests-2a` | `... npx vitest run src/widgets/utility/{MarketClock,MarketSummary,News,PositionSizing,ProfitTarget,Scanner}/` |
| `node-widget-tests-2b` | `... npx vitest run` over `src/widgets/utility/{StrategyTemplates,TickSpeed,Ticker,Watchlist,AIBackends,AITeam,Obsidian,TradeJournal}/` (one dir per invocation; `TradeIdea` excluded) |
| `node-widget-tests-3` | `... npx vitest run src/widgets/analysis/ src/routes/ src/tools/ src/components/ src/chrome/ src/widgets/orders/ src/widgets/account/` |
| `secrets-check` | the inline two-pattern `grep` loop from `test.yml` (NOT gitleaks) |

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

*Owners: any contributor who touches a file under `.github/workflows/`
should update this document in the same commit so the contract stays
current.*

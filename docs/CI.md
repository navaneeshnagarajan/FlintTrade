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
| `test.yml` | push to `main` / `dev`; non-draft PR | 7 Linux jobs (~70 minutes wall-clock) | The main quality gate. Uses `paths-ignore` so doc-only commits skip the matrix entirely. |
| `nightly-cross-platform.yml` | weekly cron (Sun 03:00 UTC); manual dispatch | 1 macOS + 1 Windows | Catches slow-burn platform regressions before they accumulate. |
| `status-report.yml` | weekly cron (Mon 07:00 UTC); manual dispatch | 1 Linux job (~5 minutes) | Emits a repo-health snapshot artefact. |
| `claude.yml` | issue / PR comment containing `@claude` | 1 Linux job per invocation | Zero per-push cost. Runs only when explicitly tagged. |
| `claude-code-review.yml` | PR opened / ready-for-review / reopened (paths-ignore + draft guard) | 1 Linux job per qualifying transition | Skips `synchronize` events to avoid running on every PR commit. |

### The seven per-push Ubuntu jobs

`test.yml` splits the Python and TypeScript test suites across seven
parallel jobs to keep wall-clock time low:

1. `python-tests` — full pytest suite (~9,089 tests).
2. `node-core-tests` — Vitest for non-widget terminal code.
3. `node-widget-tests-1` — Vitest for the first widget shard.
4. `node-widget-tests-2a` — second widget shard, half A.
5. `node-widget-tests-2b` — second widget shard, half B.
6. `node-widget-tests-3` — third widget shard.
7. `secrets-check` — runs `gitleaks` against the diff to catch leaked
   credentials early.

All seven must be green for the workflow to be reported as passing.

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
  commit only touches `*.md`, `docs/**`, `.local/**`, `NOTICE`,
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
| 7 | Stop-time review gate (`/codex:setup --enable-review-gate`) — runs a deeper review before each stop during active development | High-level design / contract / safety issues unit tests cannot see. |
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
| `node-core-tests` | `cd packages/apps/terminal && npx vitest run --exclude 'src/widgets/**'` |
| `node-widget-tests-1` | `cd packages/apps/terminal && npx vitest run src/widgets/trading/` |
| `node-widget-tests-2a` | `cd packages/apps/terminal && npx vitest run src/widgets/analysis/ --shard=1/2` |
| `node-widget-tests-2b` | `cd packages/apps/terminal && npx vitest run src/widgets/analysis/ --shard=2/2` |
| `node-widget-tests-3` | `cd packages/apps/terminal && npx vitest run src/widgets/utility/` |
| `secrets-check` | `gitleaks detect --source . --no-banner` |

### Step 4 — fix and push

Conventional commit, no `--no-verify`, no `dangerouslySkipPermissions`.
If a pre-commit hook breaks because of your change, fix the hook in the
same commit.

---

## 6. Common CI failure shapes

| Symptom | Likely cause | Fix |
|---|---|---|
| `pytest` reports `ImportError: cannot import name 'X'` | New module not added to `__init__.py`, or import is relative inside `packages/*/src/`. | Use absolute imports; add to `__init__.py` if it is a public surface. |
| `vitest` reports `Cannot find module '@/...'` | Path alias not honoured in the test config. | Ensure `vitest.config.ts` reads the same alias as `tsconfig.json`. |
| `ruff` fails with new lint codes | Newer ruff rule activated. | Run `ruff check --fix` locally, commit the autofix. |
| `gitleaks` flags a "secret" that is a public sample | Sample API key without a `# pragma: allowlist secret` marker. | Add the marker, or move the sample under a `tests/fixtures/` path. |
| Cross-platform job fails on Sunday but Linux is green | Path-separator or filesystem-case issue. | Reproduce in a Linux VM with `WIN_COMPAT=1` env, or switch to `pathlib`. |
| Workflow is queued for a long time | Runner contention or workflow concurrency cancellation chain. | Wait. If a real outage, GitHub Status will say so. |

---

## 7. Adding a new workflow

If you add a new GitHub Actions workflow:

- Default to `ubuntu-latest`. Anything else needs a written justification
  in the same PR.
- Add `paths-ignore` if the workflow does not need to fire on doc-only
  changes.
- Add a `concurrency` block with `cancel-in-progress: true` for any
  workflow that can be triggered rapidly.
- Update this document in the same commit.

---

## 8. When CI behaves unexpectedly

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

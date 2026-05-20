# CI Budget & Quality Plan

> Goal: **0 CI errors after every push** AND **stay under the monthly GitHub
> Actions minute cap** (free tier: 2000 min/mo for private repos; effectively
> unlimited for public). FlintTrade hit the cap in April 2026.
>
> This doc is the contract that protects both — every contributor must read
> the "Per-commit checklist" and the "Hosted-runner cost model" before
> changing a CI workflow.

## 1. Hosted-runner cost model

GitHub Actions bills minutes against your account based on the runner OS,
with a per-OS multiplier:

| Runner | Minute multiplier |
|---|---:|
| `ubuntu-latest` | **1×** |
| `windows-latest` | **2×** |
| `macos-latest` | **10×** |

A 10-minute `macos-latest` job consumes **100 minutes** of your monthly
budget, which is why the macOS Python job was the single biggest line item
on the FlintTrade bill prior to 2026-05-19.

**Implications for FlintTrade:**
- All per-push jobs MUST be `ubuntu-latest`. macOS and Windows live in
  `nightly-cross-platform.yml` and run weekly (Sunday 03:00 UTC).
- Anyone adding a new platform matrix MUST move it to the nightly workflow,
  not the test workflow. Per-push macOS is a CI-budget regression and will
  be reverted on review.

## 2. Per-commit checklist (contributor side)

This is the first line of defence — if every commit passes locally, CI
catches drift, not regressions.

1. **Before you commit**:
   - `cd packages/terminal && npx tsc --noEmit` (terminal typecheck)
   - `cd packages/terminal && npx vitest run <changed-tests>` (or full
     suite if widget surface touched)
   - `python -m pytest <changed-tests> --tb=short --import-mode=importlib`
   - `ruff check packages/*/src/`
2. **Before you push**:
   - `git status` clean — no untracked Python `__init__.py` or
     `package-lock.json` left out (memory: feedback.md "Commit all
     changed files").
   - `make test` if you touched anything in `packages/*/src/`.
3. **If you only touched docs** (`*.md`, `docs/**`, `.local/**`, `NOTICE`,
   `LICENSE`, `.gitignore`, `.gitattributes`, `.editorconfig`,
   `.github/ISSUE_TEMPLATE/**`, or the `claude*.yml` /
   `status-report.yml` workflows) — `test.yml` skips the matrix
   automatically via `paths-ignore` (no CI cost). Use this for doc-only
   commits to keep the bill down.
4. **Draft PRs are free**: open a PR as a draft, push iteratively without
   CI cost, mark "ready for review" only when you want CI to run. All
   `test.yml` and `claude-code-review.yml` jobs gate on
   `github.event.pull_request.draft != true`.

## 3. Workflow inventory (post-2026-05-19)

| Workflow | Trigger | Cost per fire | Notes |
|---|---|---|---|
| `test.yml` | push to main/dev + non-draft PR (with paths-ignore) | 7 Linux jobs (~70 min) | The main gate. `concurrency: cancel-in-progress: true` ensures back-to-back pushes only run the latest. |
| `nightly-cross-platform.yml` | weekly cron (Sun 03:00 UTC) + manual dispatch | 1 macOS + 1 Windows (~100 min macOS + ~30 min Windows = ~130 weighted min) | Cross-platform regressions surface here, not on every push. |
| `status-report.yml` | weekly cron (Mon 07:00 UTC) + manual dispatch | 1 Linux job (~5 min) | Generates `.local/STATUS.md` artefact for repo-health snapshots. |
| `claude.yml` | issue / PR comment containing `@claude` | 1 Linux job, only when explicitly invoked | Zero per-push cost. |
| `claude-code-review.yml` | PR opened / ready-for-review / reopened (paths-ignore + draft guard) | 1 Linux job per qualifying PR transition | `synchronize` removed 2026-05-19 — used to fire on every PR commit, multiplying cost ~5–10× per PR. |

## 4. Why CI used to break

The 2026-05-18 status-report job was crashing with
`AttributeError: 'list' object has no attribute 'get'` in `scripts/audit_repos.py`
because `absorption-status.json` had migrated from a `{"repos": {…}}` dict
shape to a flat `[…]` list shape, and the script never accommodated both.
Fixed 2026-05-19; script now accepts either shape.

The previous run history (~27 of 30 runs red) was almost entirely the
status-report workflow falling over for the reason above plus
`submodules: recursive` on the checkout step (`infra/algomirror`,
`infra/openalgo`, `infra/openclaw`) failing because those submodules were
detached in commit `3da42e4` (2026-04-30) — Git emits warnings, the
workflow itself didn't crash on this but it added noise. Both fixed 2026-05-19.

The `Test` workflow itself was largely passing — the dashboard's red
status was the failing weekly status-report dragging the headline status
down.

## 5. Defence-in-depth for "0 errors after shipping"

| Layer | Mechanism | Catches |
|---|---|---|
| 1. **Local pre-commit** | `npx tsc --noEmit && npx vitest run && pytest --tb=short && ruff check` | Most syntactic + unit-test regressions |
| 2. **Contract tests** | `packages/core/tests/test_orders_contract.py` — parses `api.ts` for `postOrder("leaf",…)` calls, compares against Flask `/api/v1/orders/*` route registrations | Frontend ↔ backend route drift (the Codex stop-gate finding that triggered this whole quality push) |
| 3. **Concurrency cancel** | `cancel-in-progress: true` on `test.yml` and `claude-code-review.yml` | Back-to-back-push minute amplification |
| 4. **Draft-PR guard** | `if: github.event.pull_request.draft != true` on every test job | Wasted CI on work-in-progress PRs |
| 5. **paths-ignore** | doc-only commits skip the matrix | Routine doc updates burning minutes |
| 6. **`continue-on-error` budget hygiene** | Any job marked `continue-on-error: true` MUST live in the nightly workflow, never `test.yml` | "Cosmetic" matrix entries silently inflating the bill |
| 7. **Codex stop-gate** | `/codex:setup --enable-review-gate` runs a Codex rescue review before each stop in active development | High-level design / contract / safety issues that unit tests can't see |
| 8. **Nightly cross-platform** | Sunday cron exercises the full macOS + Windows matrix | Slow-burn platform regressions before they pile up |

## 6. What to do if the bill spikes again

1. **Check `gh run list --limit 50 --json conclusion,createdAt`** — look
   for a burst of red runs (rapid-fire push + force-push cycles burn
   minutes even with concurrency cancellation, because the first 10–30 s
   of each cancelled run still bills).
2. **Check `nightly-cross-platform.yml` schedule** — if it accidentally
   moved to a daily cadence, that's an extra ~520 weighted minutes/week.
3. **Check `claude.yml` invocations** — a runaway `@claude` mention in a
   noisy issue thread bills every comment that contains the trigger.
4. **Check artefact retention** — `actions/upload-artifact@v4` defaults
   to 90 days. For large bundles (e.g. coverage HTML), set
   `retention-days: 7`.

## 7. Going public (AGPL) cuts the bill to zero

GitHub Actions is **free with unlimited minutes for public repositories**.
Publishing the FlintTrade repo (already AGPL-3.0 in the LICENSE) eliminates
the monthly budget pressure entirely. The remaining items on the path are
the pre-public-hardening tasks tracked in memory `project.md` and PLAN.md
(VITE_OPENALGO_API_KEY removal — done in `7a79bac`, sandbox-executor AST
guard — done in `cb5722f`, etc.). Once the residual orphan-API and
sample-data widget items are resolved, going public is the cleanest
budget fix.

---

*Last updated 2026-05-19. Owners: any contributor who touches `.github/workflows/*.yml` must update this doc in the same commit.*

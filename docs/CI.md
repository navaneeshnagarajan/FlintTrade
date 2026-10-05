# Checks and continuous integration

Use the affected gate while editing and the exhaustive gate before pushing. Both use the cross-platform task runner:

```text
python scripts/ft.py check
python scripts/ft.py check --full
```

`check --dry-run` prints the selected commands without running them. `--base <ref>` changes the comparison base; the default is `origin/main`. The comparison includes committed branch changes, staged changes, unstaged changes and non-ignored untracked files. A missing base or an uncertain change selects every surface. Refresh `origin` before relying on the branch comparison.

## Local feedback

Focused Python paths and pytest flags are accepted directly:

```text
python scripts/ft.py test-fast packages/integrations/gateway/tests/test_rate_limiter.py
python scripts/ft.py test packages/services/journal/tests/ --workers 2
```

The default Python worker count is at most four and never exceeds the available CPU count. Set `FLINTTRADE_TEST_WORKERS` or pass `--workers`; use `--workers 0` for serial debugging. The runner only adds xdist arguments when the selected interpreter has the plugin. Normal timeout, import-mode and strict-marker safeguards remain enabled. Focused paths retain the repository pytest configuration and workspace isolation unless you explicitly select another configuration. The default `test` command still runs every Python test directory and the Rust ticks suite when Cargo is available; explicit Python paths and display-only commands avoid an unrelated Rust run.

Pytest subprocesses cap numerical-library threads at one per worker. This avoids nested OpenMP/BLAS pools competing with xdist; application training settings are unchanged. With the same three real LightGBM tests and four pytest workers, the October audit measured 50.65 seconds with default native pools and 1.01 seconds with these limits.

Affected checking conservatively runs all Python package tests for Python, terminal, design-system and desktop changes: Python contracts inspect frontend clients and fixtures, and desktop bootstrap helpers are Python. Documentation and marketing-site changes run repository/script invariants. Runtime Markdown, including AI skills and prompts, keeps its package checks. Core API, gateway and execution-engine changes also select the terminal's contract checks. Unknown files, new packages, root tests, shared manifests, lockfiles and build/installation scripts select every surface.

Cross-surface source contracts retain their consumers: site attribution and AI/MCP inputs select Site, while `docs/INVENTORY.md` and the site's shared-design CSS select terminal checks.

`check --full` includes the whole pytest tree, Ruff, Rust when installed, terminal lint/full Vitest/typecheck/build, site tests/typecheck/build, desktop tests/typecheck and the secrets scan. Required tools failing or missing makes the gate fail. App suites run sequentially to avoid competing for memory. Terminal typechecking runs once through its build command. `make full-check` is the POSIX alias for this same exhaustive gate.

Dependency-selected gates also run the offline HTTP cache contract against every installed pnpm copy. Install the frozen workspace with the repository-pinned package manager before checking; lock metadata alone does not prove that a dependency patch was applied.

The output distinguishes affected checks from exhaustive verification. Passing affected checks does not satisfy the full local pre-push gate. Python is verified in the repository virtualenv. TypeScript and platform-specific results from one development machine are supporting evidence; CI and native contributor runs remain necessary for cross-platform claims.

## PR selection and required checks

The Test workflow has no path filter on its pull-request trigger, so every non-draft PR targeting `main` or `dev` creates the required contexts. Selection happens inside the workflow using `scripts/check_changes.py`, the same classifier as the local runner. Renames include both paths and deleted files remain visible. Unresolvable comparisons and unknown paths run every surface.

| Change | PR work |
|---|---|
| Documentation or marketing site | Repository/script invariants, secrets scan and relevant site checks |
| A known Python leaf package | All Python package suites plus repository/script invariants and secrets |
| Core API, gateway or execution engine | Python package suites, terminal contracts/tests/build and site contracts |
| Terminal or shared design system | Terminal checks, Python contracts/package suites, repository/script invariants, site contracts and relevant visual checks |
| Desktop shell | Desktop checks and package verification, Python/bootstrap suites, repository/script invariants and site contracts |
| Rust ticks | Rust tests and Python package suites, including binding contracts |
| Dependencies, shared configuration, installation scripts or unknown paths | Every selected surface; dependency assurance also runs |

All repository and Python script tests run in `python-invariants` on every non-draft PR. Documentation guards, install/frozen-lockfile rules, catalogue/count pins and workflow-coverage guards remain present even on docs-only changes.

Python package tests run across four deterministic `python-shards` jobs. A stable SHA-256 hash of each collected node ID assigns it to exactly one shard; no tests are excluded by this partition. Each shard keeps xdist workspace isolation, frozen installation, optional ML compatibility tests, strict markers and watchdog timeouts. Its JUnit artefact and slowest-test report make future balancing evidence-based.

The required `python-tests` context is an aggregate. It succeeds only when invariants pass and every selected shard succeeds. A failed classifier, malformed selection, failure, cancellation or unexpected skip makes it fail. Documentation-only PRs expect the package shard job to be skipped and still require the invariant result.

The existing required terminal, widget, Rust, Electron and secrets check names remain intact. An unrelated surface is skipped at job level. The Python aggregate remains reachable even when the classifier fails. Do not add a PR-level path filter to Test: omitted required contexts can block merging.

Terminal suites retain one worker per lane and cover every test file exactly once. Analysis, routes and components are spread across the existing widget runners instead of concentrating in one job. TradeIdea runs as an isolated 4 GiB step: the October audit measured its 14 tests at 316 MiB peak memory, so the former OOM exclusion is removed.

Main/dev pushes, weekly Test runs and manual Test dispatches run the exhaustive selected surfaces. Cross-platform Python, target-version canaries and native desktop packages remain in the weekly/manual cross-platform workflow.

## Workflow inventory

| Workflow | Purpose and scheduling |
|---|---|
| `test.yml` | Required quality checks; affected non-draft PRs, exhaustive main/dev pushes, weekly Sunday 04:00 UTC and manual runs |
| `site.yml` | Reusable site typecheck, tests and build; called by Test using the shared selection plan and exhaustive triggers |
| `supply-chain.yml` | Scoped dependency PR assurance; exhaustive main/dev pushes, weekly Monday and manual runs; native install/ACL smoke remains weekly/manual |
| `visual-a11y.yml` | Advisory terminal screenshots and axe checks for relevant non-draft changes; manual baseline regeneration |
| `nightly-cross-platform.yml` | Weekly/manual macOS, Windows and Linux tests, toolchain-target canaries and native desktop package smoke |
| `desktop-release.yml` | manual dispatch only; Release Please supplies the immutable release tag and expected commit SHA. Builds the four Electron installers, verifies their packaged contract and publishes them with `SHA256SUMS.txt` only to an empty release target. |
| `release-please.yml` | Conventional-Commit release/version automation on main |
| `refresh-vuln-snapshot.yml` | Weekly/manual offline vulnerability-snapshot refresh |
| `status-report.yml` | Weekly/manual repository-health report |
| `key-freshness.yml` | Scheduled upstream signing-key assurance and relevant pin changes; the offline expired/revoked-key guard also runs in Test |
| `toolchain-freshness.yml` | Scheduled/manual and relevant toolchain-version checks |
| `broker-sdk-freshness.yml` | Scheduled/manual broker SDK drift checks |

Supply Chain retains Python/Rust/Node audits, licence/provenance checks, NOTICE and lock drift, frozen/hashed-install enforcement and external-contributor CLA binding. Changes to installation/build support files select assurance even if the lockfiles are unchanged. Mutable upstream advisory state is still checked on protected-branch pushes and scheduled runs.

Electron Linux directory verification has one authoritative Test lane: bootstrap-manifest verification, full desktop tests/typecheck, bundling, required native promotion harness, packaging and packaged-security verification. Removing the duplicate Supply Chain packaging lane preserves this union and its weekly/manual coverage.

Visual checks remain advisory while `VISUAL_AXE_GATE` is `0`; they do not prove application state or network behaviour. Manual baseline updates commit only after successful regeneration. Reticle verifies running user flows when application behaviour changes; CI/tooling-only changes do not require an unrelated UI session.

Dependency version PRs remain grouped and are staggered across Monday–Thursday, with at most two open version PRs per ecosystem. Security updates remain separately enabled. Concurrency cancellation supersedes older runs for the same ref. Draft PRs skip runnable quality jobs until marked ready for review.

## Verification and review

The canonical pipeline is **build agents (Codex or other supported agents) → independent multi-agent review panels → maintainer**. After a build/commit wave, fix actionable findings and re-audit. Use Conventional Commits, stage explicit files and keep the full pre-push gate. Never push or merge without explicit maintainer permission; never bypass hooks.

Workflow changes must retain timeouts, least-privilege permissions, pinned actions and frozen installs. Frequent checks remain Linux-only; expensive native runners belong on weekly/manual workflows. `tests/test_workflow_policy.py`, `test_required_check_reachability.py`, `test_check_changes.py`, `test_check_workflow_efficiency.py` and the Python/Vitest partition guards enforce these contracts.

Run the focused policy checks after editing workflow selection:

```text
python scripts/ft.py test-fast tests/test_workflow_policy.py tests/test_required_check_reachability.py tests/test_check_changes.py tests/test_check_workflow_efficiency.py tests/test_pytest_sharding.py tests/test_ci_vitest_shard_coverage.py
```

A shard failure is investigated using the named test and uploaded JUnit evidence. An unexpected skip is a failure to schedule required work, not a passing test. Do not weaken an assertion, timeout or safety guard to get a green result.

The October 2026 audit sampled successful documentation and code PRs taking about 19–21 minutes overall. Full pytest used about 19 minutes while dependency installation took under a minute. Four-way sharding and focused invariant lanes address that measured bottleneck; actual hosted improvement must be measured after an authorised CI run. Local timings do not establish GitHub runner timings.

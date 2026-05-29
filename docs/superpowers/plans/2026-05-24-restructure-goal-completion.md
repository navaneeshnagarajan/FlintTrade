# Restructure Goal Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every remaining gap between `.local/specs/flinttrade-design/` and the current `codex/flinttrade-v0.6.0-restructure` workspace.

**Architecture:** Treat the `.local` restructure specs as the source of truth, then encode the most brittle repo-shape requirements as tests so future edits cannot silently drift back to pre-restructure paths. Keep fixes scoped to CI wiring, repository metadata, licence layout, and local verification gates.

**Tech Stack:** Python 3.12, pytest, GitHub Actions YAML, pnpm workspace, Docker, git tag verification.

---

### Task 1: Guard The Restructure Invariants

**Files:**
- Create: `tests/test_restructure_goals.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert GitHub workflows no longer reference old package paths, root documentation files use the lowercase names required by the restructure spec, and the licence layout has `LICENSE -> licenses/agpl-3.0.txt` plus the auxiliary licence files.

- [ ] **Step 2: Run the tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/test_restructure_goals.py -q`

Expected: FAIL on stale workflow paths and missing lowercase/licence files.

### Task 2: Patch Repo Metadata And CI Wiring

**Files:**
- Modify: `.github/workflows/test.yml`
- Modify: `.github/workflows/site.yml`
- Modify: `.github/workflows/nightly-cross-platform.yml`
- Modify: `Dockerfile`
- Modify: `scripts/check_doc_sync.py`

- [ ] **Step 1: Update workflow paths**

Replace pre-restructure package paths with the 4-way nest paths, and use the root pnpm lockfile for Node installs.

- [ ] **Step 2: Touch Dockerfile intentionally**

Install the Python workspace packages from their new paths in the Docker image so the container can import `flinttrade_core`.

- [ ] **Step 3: Update commit-1 doc-sync coverage**

Keep `.github/workflows/test.yml`, `.github/workflows/site.yml`, and `Dockerfile` in the commit-1 required set, and add the root metadata/licence files that are part of the commit-1 spec.

### Task 3: Patch Root Casing And Licence Layout

**Files:**
- Rename: `README.md` -> `readme.md`
- Rename: `CHANGELOG.md` -> `changelog.md`
- Rename: `CONTRIBUTING.md` -> `contributing.md`
- Rename: `CODE_OF_CONDUCT.md` -> `code-of-conduct.md`
- Rename: `SECURITY.md` -> `security.md`
- Rename: `NOTICE` -> `notice`
- Create: `licenses/agpl-3.0.txt`
- Create: `licenses/apache-2.0.txt`
- Create: `licenses/cc-by-4.0.txt`
- Create: `licenses/plug-in-exception.txt`
- Replace: `LICENSE` with a symlink to `licenses/agpl-3.0.txt`

- [ ] **Step 1: Rename root docs with git-aware case-only renames**

Use temporary names for case-only renames so the final tree has only the lowercase files.

- [ ] **Step 2: Add licence files and symlink**

Move the AGPL notice into `licenses/agpl-3.0.txt`, add the required companion files, then link root `LICENSE` to the AGPL file.

### Task 4: Verify And Loop

**Files:**
- No production edits expected unless verification exposes another gap.

- [ ] **Step 1: Create local signed baseline tag**

Run: `git tag -s pre-restructure-baseline 82c2b39 -m "pre-restructure baseline"` and verify it with `git tag -v pre-restructure-baseline`.

- [ ] **Step 2: Run focused checks**

Run the restructure-goal test, doc-sync checks, workflow path search, baseline tag verification, broker lock checks, uv-lock drift check, package collection count, site build, terminal build, and `make full-check`.

- [ ] **Step 3: Repeat if any check fails**

Investigate root cause, patch the smallest missing piece, and rerun the failing check before broad verification.

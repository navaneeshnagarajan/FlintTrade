# Public Repo Modernisation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the public FlintTrade repository surface so a stranger can confidently fork, contribute, or self-host — by removing 35 AI-tool-internal `.md` files from tracking, rewriting the README around a hybrid trader/developer story, restructuring `docs/`, adding standard GitHub OSS metadata, and replacing per-package agent docs with public-facing READMEs.

**Architecture:** Six parcels — one sequential head (file moves + ignore rules), four parallel middle parcels (README rewrite + docs/ restructure + CONTRIBUTING refresh + .github metadata), one sequential tail (per-package READMEs + stale sweep). Each parcel produces one commit. Final push held until user approval. No application code touched.

**Tech Stack:** Markdown + GitHub-flavoured conventions, Mermaid for diagrams, Bash for the agent-context scaffold script, conventional commits.

**Spec reference:** [docs/superpowers/specs/2026-05-20-public-repo-modernisation-design.md](../specs/2026-05-20-public-repo-modernisation-design.md)

---

## Parcel 1 — De-scaffold the repo root (sequential, runs first)

Reshapes the tree so subsequent parcels write into a clean structure.

### Task 1.1: Inventory verification

**Files:** none modified — verification only.

- [ ] **Step 1:** Confirm current counts.

```bash
cd /c/Users/navan/Documents/GitHub/FlintTrade
git ls-files | grep -c "CLAUDE\.md$"   # Expected: 17 (root + 16 packages)
git ls-files | grep -c "AGENTS\.md$"   # Expected: 17 (root + 16 packages)
git ls-files | grep -c "^PLAN\.md$"    # Expected: 1 (root)
```

Expected output: `17`, `17`, `1` → total **35 files** to move.

If counts differ, stop and reconcile before proceeding.

### Task 1.2: Create the agent-context template tree

**Files:**
- Create: `.local/agent-context-templates/CLAUDE.md.template`
- Create: `.local/agent-context-templates/AGENTS.md.template`
- Create: `.local/agent-context-templates/PLAN.md.template`
- Create: `.local/agent-context-templates/packages/<pkg>/CLAUDE.md.template` (one per package, populated from the current per-package CLAUDE.md content as the seed)
- Create: `.local/agent-context-templates/packages/<pkg>/AGENTS.md.template` (one per package)

- [ ] **Step 1:** Copy current tracked agent-internal files to the template tree before moving them.

```bash
mkdir -p .local/agent-context-templates/packages
cp CLAUDE.md .local/agent-context-templates/CLAUDE.md.template
cp AGENTS.md .local/agent-context-templates/AGENTS.md.template
cp PLAN.md  .local/agent-context-templates/PLAN.md.template

for pkg in ai automation backtest-engine chrome-extension core data desktop ditto engine gateway historical indicators integration screener terminal tick-engine; do
  mkdir -p .local/agent-context-templates/packages/$pkg
  cp packages/$pkg/CLAUDE.md .local/agent-context-templates/packages/$pkg/CLAUDE.md.template
  cp packages/$pkg/AGENTS.md .local/agent-context-templates/packages/$pkg/AGENTS.md.template
done
```

- [ ] **Step 2:** Verify template tree.

```bash
find .local/agent-context-templates -type f -name '*.template' | wc -l   # Expected: 35
```

### Task 1.3: Create the setup script

**Files:** Create `scripts/setup-agent-context.sh`

- [ ] **Step 1:** Write the script.

```bash
#!/usr/bin/env bash
# Scaffold .local/agent-context/ from the template tree shipped at
# .local/agent-context-templates/. Idempotent: skips files that already exist.
#
# Run this once per fresh clone if you use a CLAUDE-aware or AGENTS-aware
# coding agent (Claude Code, Cursor, Aider, Continue, Codex, etc.). The
# resulting .local/agent-context/ tree is gitignored and machine-local.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SRC=".local/agent-context-templates"
DST=".local/agent-context"

if [ ! -d "$SRC" ]; then
  echo "Templates not found at $SRC. Run from repo root with a fresh clone." >&2
  exit 1
fi

mkdir -p "$DST/packages"
copied=0
skipped=0
while IFS= read -r tpl; do
  rel="${tpl#$SRC/}"
  out="${rel%.template}"
  dst_path="$DST/$out"
  mkdir -p "$(dirname "$dst_path")"
  if [ -e "$dst_path" ]; then
    skipped=$((skipped+1))
  else
    cp "$tpl" "$dst_path"
    copied=$((copied+1))
  fi
done < <(find "$SRC" -type f -name '*.template')

echo "Agent context scaffolded at $DST/"
echo "  copied:  $copied files"
echo "  skipped: $skipped files (already present)"
```

- [ ] **Step 2:** Make executable + smoke test.

```bash
chmod +x scripts/setup-agent-context.sh
bash scripts/setup-agent-context.sh
# Expected: "copied: 35 files" on a fresh run (or some skipped if .local/agent-context/ already exists)
find .local/agent-context -type f | wc -l   # Expected: 35
```

### Task 1.4: Update `.gitignore`

**Files:** Modify `.gitignore`

- [ ] **Step 1:** Add these lines under a clearly labelled section. Use `Edit` tool to insert near the existing `.local/` rule.

```gitignore
# === Agent-internal context (machine-local, scaffolded via scripts/setup-agent-context.sh) ===
/CLAUDE.md
/AGENTS.md
/PLAN.md
/packages/*/CLAUDE.md
/packages/*/AGENTS.md
```

- [ ] **Step 2:** Verify gitignore syntax.

```bash
git check-ignore -v CLAUDE.md      # Expected: gitignore rule fires
git check-ignore -v AGENTS.md      # Expected: gitignore rule fires
git check-ignore -v PLAN.md        # Expected: gitignore rule fires
git check-ignore -v packages/core/CLAUDE.md   # Expected: gitignore rule fires
```

### Task 1.5: `git rm` the 35 tracked files

**Files:** Remove from tracking (content already preserved at `.local/agent-context-templates/`):
- `CLAUDE.md`, `AGENTS.md`, `PLAN.md` (3 root)
- `packages/<pkg>/CLAUDE.md` (16 packages)
- `packages/<pkg>/AGENTS.md` (16 packages)

- [ ] **Step 1:** Run the removal.

```bash
git rm CLAUDE.md AGENTS.md PLAN.md
for pkg in ai automation backtest-engine chrome-extension core data desktop ditto engine gateway historical indicators integration screener terminal tick-engine; do
  git rm packages/$pkg/CLAUDE.md packages/$pkg/AGENTS.md
done

git status --short | grep -c "^D "   # Expected: 35
```

- [ ] **Step 2:** Stage `.gitignore` + the template tree + the script.

```bash
# NOTE: .local/ is gitignored, so .local/agent-context-templates/ won't appear
# in git status. That's intentional — templates are machine-local artefacts.
# Future contributors get them by running the script after clone, but the
# template content must travel WITH the clone. We solve that with a separate
# tracked copy at templates/agent-context/ — see Task 1.6.
git add .gitignore scripts/setup-agent-context.sh
```

### Task 1.6: Mirror templates into a tracked location

`.local/` is gitignored, so the templates won't ship with the clone. They must live in a tracked path.

**Files:** Create `templates/agent-context/` (mirror of `.local/agent-context-templates/`)

- [ ] **Step 1:** Mirror the tree into a tracked location.

```bash
mkdir -p templates/agent-context/packages
cp .local/agent-context-templates/CLAUDE.md.template templates/agent-context/CLAUDE.md.template
cp .local/agent-context-templates/AGENTS.md.template templates/agent-context/AGENTS.md.template
cp .local/agent-context-templates/PLAN.md.template templates/agent-context/PLAN.md.template
for pkg in ai automation backtest-engine chrome-extension core data desktop ditto engine gateway historical indicators integration screener terminal tick-engine; do
  mkdir -p templates/agent-context/packages/$pkg
  cp .local/agent-context-templates/packages/$pkg/CLAUDE.md.template templates/agent-context/packages/$pkg/CLAUDE.md.template
  cp .local/agent-context-templates/packages/$pkg/AGENTS.md.template templates/agent-context/packages/$pkg/AGENTS.md.template
done
```

- [ ] **Step 2:** Update `scripts/setup-agent-context.sh` to read from `templates/agent-context/` (tracked) instead of `.local/agent-context-templates/` (untracked).

Edit the `SRC` variable in the script:

```bash
SRC="templates/agent-context"
```

- [ ] **Step 3:** Re-smoke-test the script.

```bash
rm -rf .local/agent-context   # wipe scaffolded copy
bash scripts/setup-agent-context.sh   # should rebuild from templates/agent-context/
find .local/agent-context -type f | wc -l   # Expected: 35
```

- [ ] **Step 4:** Stage the tracked templates.

```bash
git add templates/agent-context/
```

### Task 1.7: Commit Parcel 1

- [ ] **Step 1:** Stage and commit.

```bash
git status --short
git commit -m "$(cat <<'EOF'
chore(repo): move CLAUDE.md / AGENTS.md / PLAN.md out of tracked tree

Public AGPL repo no longer ships agent-internal context as part of the
clone. 35 files removed from tracking (17 CLAUDE.md, 17 AGENTS.md, 1
PLAN.md, across root + 16 packages).

Content preserved in two places:
- templates/agent-context/ (tracked) — canonical source, ships with the
  clone so any new contributor can scaffold them
- .local/agent-context/ (gitignored) — machine-local working copy,
  re-created by running scripts/setup-agent-context.sh

The script is idempotent and skips files that already exist locally, so
contributors can re-run it after pulls without losing local edits.

No application code touched. Per-package READMEs land in a follow-up
parcel.
EOF
)"
```

Expected: one commit, 35 deletions, 1 new script, 1 new gitignore section, 35 new tracked template files.

---

## Parcels 2-5 — Parallel middle (dispatched as subagents)

The next four parcels write or rewrite documentation. They are independent (different files) and run in parallel via subagent dispatches.

### Parcel 2 — Hybrid README rewrite

**Files:** Modify `README.md` (rewrite end-to-end)

- [ ] **Step 1:** Dispatch a Technical Writer subagent with this brief.

> **Agent type:** `Technical Writer`
> **Description:** Rewrite root README for public AGPL-3.0 release
>
> **Brief:**
>
> Rewrite `c:\Users\navan\Documents\GitHub\FlintTrade\README.md` end-to-end for the public AGPL-3.0 release. The repo was flipped public on 2026-05-19; current version is `v0.5.2-dev`.
>
> **Required structure (in order):**
>
> 1. **H1 title + 12-word tagline** — name "FlintTrade", short pitch like "Open-source modular trading platform for Indian F&O, commodities, and crypto"
> 2. **Badges row** — License (AGPL-3.0, shields.io), version (from VERSION file, dynamic), CI status (`test.yml` workflow), tests count (~12,062 hard-coded), GitHub stars, last-commit. Use shields.io URLs.
> 3. **Hero screenshots** — 4 images using existing files under `docs/screenshots/`. Pick the strongest 4 from the repo (welcome, trade canvas, options chain / IV smile, and an analysis tool). Use HTML `<picture>` or markdown image grid, centred.
> 4. **What it does** — 6-8 trader-facing bullets (intraday F&O scalping, multi-broker support, options analysis, paper trading mode, AI-assisted signals, custom strategies, automation flows, multi-account orchestration).
> 5. **Supported brokers** — one-liner "32 brokers via the OpenAlgo gateway — see [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) for the full list".
> 6. **Quickstart (5-min Docker)** — 3-4 commands max:
>    ```bash
>    git clone https://github.com/navaneeshnagarajan/FlintTrade.git
>    cd FlintTrade
>    cp .env.example .env   # set OPENALGO_API_KEY
>    docker-compose up
>    ```
>    Then "Open http://localhost:5173 and follow the welcome wizard." Brief sentence that OpenAlgo must also be running (one-line install link).
> 7. **Visual divider** — `---`
> 8. **For developers** — start of second fold. Architecture diagram in Mermaid (FlintTrade React → REST/WS → OpenAlgo Flask → Broker API). Package map as a table (16 packages: name | purpose | language | tests). Tech stack summary (frontend: React 19 + TypeScript + Tailwind v4 + Dockview; backend: Python 3.12 + Flask + DuckDB; data: TA-Lib + Numba + Rust/PyO3; AI: LM Studio + ChromaDB + LightGBM).
> 9. **Three CTAs** — "Try it" → quickstart anchor, "Build with it" → docs/DEVELOPER_GUIDE.md, "Contribute" → CONTRIBUTING.md.
> 10. **Visual divider** — `---`
> 11. **Project documentation grid** — 2x3 table linking USER_GUIDE / DEVELOPER_GUIDE / ARCHITECTURE / API / CHANGELOG / SECURITY (each in `docs/`).
> 12. **Community** — GitHub Discussions, Issues, contributing pointer. No personal email / Discord unless user asks.
> 13. **Credits** — OpenAlgo (Rajandran R / marketcalls), OpenClaw, and "215 absorbed reference repos — see docs/REFERENCES.md".
> 14. **License + Code of Conduct + Contributing** footer — three short paragraphs with links.
>
> **Style rules (non-negotiable):**
>
> - **British English** throughout (colour, behaviour, serialise, analyse, optimise, organise, recognise, summarise, normalise, centred). Exception: code identifiers, library APIs, CSS class names.
> - No personal hostnames, IPs, broker account details, hardware specs. Project is public.
> - Each section ~ 1 screen on a 1080p laptop. Skim-friendly subheads.
> - Code blocks use triple backticks with the language tag.
> - Mermaid diagram uses fenced ` ```mermaid ` block.
> - Tables use proper Markdown alignment.
> - First sentence under the title must hook a reader in under 10 seconds.
>
> **What to read for context:** `c:\Users\navan\Documents\GitHub\FlintTrade\docs\superpowers\specs\2026-05-20-public-repo-modernisation-design.md` (the approved spec). Current `README.md` (treat as reference for facts, but rewrite layout fully). `CHANGELOG.md` recent entries (for accurate "what shipped"). `VERSION` file. `flint.toml` for package list.
>
> **Output:** Write the new README.md content to the file. Do not commit (the orchestrator commits at parcel end).

- [ ] **Step 2:** Receive output, spot-check first 60 lines, verify badges resolve, verify Mermaid renders.

- [ ] **Step 3:** Verify acceptance criteria:
  - Above-the-fold: title + tagline + badges + 4 screenshots + "what it does" + quickstart
  - Below-the-fold: developer view + package map + tech stack + docs grid + credits
  - British English (no `color`, `behavior`, `serialize`, `analyze`, `organize`)
  - All file links are correct relative paths

### Parcel 3 — Restructure `docs/` (parallel)

**Files:**
- Move: `docs/RELEASE_NOTES_v0.5.1.md` → `docs/releases/v0.5.1.md`
- Move: `docs/RELEASE_NOTES_v0.5.2-dev.md` → `docs/releases/v0.5.2-dev.md`
- Move: `docs/machine-setup/` → `docs/setup/` (renamed, all contents preserved)
- Rename: `docs/CI_BUDGET_AND_QUALITY.md` → `docs/CI.md` (content softened — see brief)
- Create: `docs/README.md` (landing index)
- Create: `docs/USER_GUIDE.md`
- Create: `docs/DEVELOPER_GUIDE.md`
- Create: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md` (refresh)
- Archive to `.local/archive/docs-internal/` (logged in `ARCHIVE_LOG.md`):
  - `docs/COMPETITIVE_ANALYSIS.md`
  - `docs/research/`
  - `docs/status/`
  - `docs/superpowers/plans/` (NOT specs/ — leave the current spec accessible)
  - `docs/REFERENCES.md` (full version archived; slimmer credits page at `docs/REFERENCES.md` written by Parcel 6)

- [ ] **Step 1:** Dispatch a Technical Writer subagent with this brief.

> **Agent type:** `Technical Writer`
> **Description:** Restructure docs/ folder per the modernisation spec
>
> **Brief:**
>
> Reorganise `c:\Users\navan\Documents\GitHub\FlintTrade\docs\` per the approved spec at `docs\superpowers\specs\2026-05-20-public-repo-modernisation-design.md`.
>
> **Step A — Moves (preserve content):**
>
> ```bash
> mkdir -p docs/releases
> git mv docs/RELEASE_NOTES_v0.5.1.md docs/releases/v0.5.1.md
> git mv docs/RELEASE_NOTES_v0.5.2-dev.md docs/releases/v0.5.2-dev.md
> git mv docs/machine-setup docs/setup
> git mv docs/CI_BUDGET_AND_QUALITY.md docs/CI.md
> ```
>
> **Step B — Archive these to `.local/archive/docs-internal/`** (use `mv`, NOT `git rm`, since `.local/` is gitignored; then `git rm` the originals):
>
> - `docs/COMPETITIVE_ANALYSIS.md`
> - `docs/research/` (whole subtree)
> - `docs/status/` (whole subtree)
> - `docs/superpowers/plans/` (whole subtree — but NOT `docs/superpowers/specs/`)
> - `docs/REFERENCES.md` (you'll write a slimmer replacement in Parcel 6; archive the current full version)
>
> ```bash
> mkdir -p .local/archive/docs-internal
> mv docs/COMPETITIVE_ANALYSIS.md .local/archive/docs-internal/
> mv docs/research .local/archive/docs-internal/
> mv docs/status .local/archive/docs-internal/
> mv docs/superpowers/plans .local/archive/docs-internal/superpowers-plans
> mv docs/REFERENCES.md .local/archive/docs-internal/REFERENCES-full.md
> git rm docs/COMPETITIVE_ANALYSIS.md
> git rm -r docs/research
> git rm -r docs/status
> git rm -r docs/superpowers/plans
> git rm docs/REFERENCES.md
> ```
>
> **Step C — Write new files:**
>
> Write the following files with substantive content (each ~ 200-400 lines, British English, no personal info):
>
> 1. **`docs/README.md`** (landing index)
>    - Two-paragraph intro
>    - Table of every file in `docs/` with a one-line description
>    - Two columns: "For users" / "For developers"
>
> 2. **`docs/USER_GUIDE.md`** (trader-facing)
>    - Audience: someone who wants to use FlintTrade to trade
>    - Sections: Installation → First broker connection → First paper trade → First live trade → Workspace tour → Screener walkthrough → Strategy Lab walkthrough → Automation Hub walkthrough → AI Centre walkthrough → Ditto multi-account walkthrough → Settings reference
>    - Lots of screenshots from `docs/screenshots/`
>    - End with "Troubleshooting" section
>
> 3. **`docs/DEVELOPER_GUIDE.md`** (contributor-facing)
>    - Audience: someone wanting to fork / extend / contribute
>    - Sections: Repo layout (16-package map) → Dev environment setup (Windows / macOS / Ubuntu, link to docs/setup/) → Running tests (Python + Vitest) → Building (terminal + Rust tick-engine) → Architecture deep-dive (link to ARCHITECTURE.md) → Adding a widget → Adding a strategy → Adding a broker adapter → Code style + lint → PR flow → Common gotchas (WSGI prefix strip, port 5100, no TOTP auto-login)
>
> 4. **`docs/API.md`** (endpoint reference)
>    - Audience: developer integrating with FlintTrade backend
>    - Sections: OpenAlgo passthrough (`/api/v1/*`, table of 45+ endpoints with one-liner each) → FlintTrade backend (`/ft-api/v1/*`, table of ~20 endpoints) → WebSocket (port 8765, modes 1/2/4) → Authentication (JWT + X-API-Key) → Rate limits (10/s orders, 2/s smart, 50/s general) → Mode system (explore / practice / live)
>    - Include example request/response for the 5 most-used endpoints
>
> 5. **`docs/ARCHITECTURE.md`** (refresh — existing file gets updated, not rewritten)
>    - Open the current `docs/ARCHITECTURE.md` and update:
>      - Any version references to current (`v0.5.2-dev`)
>      - Package count to 16
>      - Test count to ~12,062
>      - Add Mermaid diagrams: high-level component diagram, data flow diagram, mode-system diagram
>      - Remove any references to deleted files (CLAUDE.md, AGENTS.md, machine-setup folder)
>      - Update path references: `docs/setup/` (not `docs/machine-setup/`)
>
> **Step D — Verify:**
>
> ```bash
> find docs -name "*.md" | sort   # Expected: ~10 .md files at docs/ root + subfolders
> ls docs/releases/   # Expected: v0.5.1.md, v0.5.2-dev.md
> ls docs/setup/      # Expected: same files as old docs/machine-setup/
> test -f docs/CI.md  # Expected: 0 exit
> test ! -f docs/CI_BUDGET_AND_QUALITY.md   # Expected: 0 exit (file gone)
> ```
>
> **Step E — Soften `docs/CI.md`:**
>
> The renamed `CI_BUDGET_AND_QUALITY.md` was internal cost-control narrative. Open `docs/CI.md` and:
> - Remove any "personal billing limit hit on 2026-05-19" specifics
> - Frame it as "How CI runs and why" — contributor-facing
> - Keep the per-push job list and the paths-ignore rules
> - Keep the nightly cross-platform schedule explanation
> - Drop the "we ran out of minutes" history; keep the lessons
>
> **Style rules:**
>
> - British English throughout (colour, behaviour, serialise, analyse, optimise, organise, recognise, summarise, normalise, centred)
> - No personal hostnames, IPs, hardware specs, broker accounts
> - Every internal link uses a relative path
> - Code examples use language-tagged fences
> - Each new doc has a one-paragraph "purpose" preamble at the top
>
> **What to read for context:**
> - The approved spec at `docs/superpowers/specs/2026-05-20-public-repo-modernisation-design.md`
> - Current `docs/ARCHITECTURE.md` (treat as the source of truth for architecture facts)
> - Current `CHANGELOG.md` (for accurate release content)
> - `flint.toml` for package list
> - `packages/core/core/src/openalgo_client.py` for endpoint inventory
>
> **Output:** Write all new files + perform the moves + log the archive moves. Do NOT commit (orchestrator commits at parcel end).

- [ ] **Step 2:** Receive output, spot-check the structure.

- [ ] **Step 3:** Verify the docs/ tree matches:

```bash
ls docs/
# Expected: ARCHITECTURE.md API.md CI.md COMPATIBILITY.md DEVELOPER_GUIDE.md README.md SEBI_COMPLIANCE.md USER_GUIDE.md
# Plus subfolders: assets/ releases/ screenshots/ setup/ superpowers/
```

### Parcel 4 — CONTRIBUTING + CODE_OF_CONDUCT + SECURITY refresh (parallel)

**Files:**
- Modify: `CONTRIBUTING.md`
- Modify or replace: `CODE_OF_CONDUCT.md`
- Modify: `SECURITY.md`

- [ ] **Step 1:** Dispatch a Technical Writer subagent with this brief.

> **Agent type:** `Technical Writer`
> **Description:** Refresh CONTRIBUTING + CoC + SECURITY for public OSS contributors
>
> **Brief:**
>
> Update three root-level governance files for the public AGPL-3.0 release.
>
> **File 1: `CONTRIBUTING.md`** (rewrite end-to-end)
>
> Required sections:
> - Welcome paragraph (we're an Indian fintech OSS project, AGPL-3.0)
> - "Before you start" — review CODE_OF_CONDUCT, SECURITY policy, ARCHITECTURE
> - Development setup (point to docs/setup/)
> - How to run tests (`make test` + `npx vitest run` in `packages/apps/terminal/`)
> - How to build (terminal + Rust tick-engine commands)
> - Branch + commit conventions — Conventional Commits, examples
> - Pull request flow — fork → branch → PR → checklist
> - Code style — Python (ruff), TypeScript (strict, no any), British English in docstrings/comments/user-visible strings
> - "Good first issue" pointers
> - Areas where help is wanted (broker adapters, strategy templates, AI prompts, internationalisation)
> - Reporting bugs — link to issue templates
> - License notice (AGPL-3.0 implications for contributors)
>
> Drop every reference to CLAUDE.md / AGENTS.md / PLAN.md / `.local/` — those are gone from the public surface now.
>
> **File 2: `CODE_OF_CONDUCT.md`** (verify or replace)
>
> Standard expectation: Contributor Covenant v2.1 verbatim, with enforcement contact filled in.
> - Read the current `CODE_OF_CONDUCT.md`. If it's already Contributor Covenant v2.1, only update the enforcement contact line (use GitHub-only contact: "open a private security advisory" rather than a personal email).
> - If it's something else, replace it with the canonical Contributor Covenant v2.1.
>
> **File 3: `SECURITY.md`** (rewrite end-to-end)
>
> Required sections:
> - "Reporting a vulnerability" — primary channel: GitHub Security Advisories (link to the repo's security tab). Fallback: open an issue with "[SECURITY]" prefix.
> - "Supported versions" — table. Pre-1.0: only the latest minor (currently `0.5.x`) gets security patches.
> - "Disclosure policy" — 90 days from confirmed report to public disclosure.
> - "Scope" — what counts as a vulnerability for FlintTrade: anything that lets an unauthenticated user place orders, anything that exfiltrates broker credentials, anything that bypasses the explore→practice→live mode guards, anything that bypasses the JWT auth on `/ft-api/v1/*`.
> - "Out of scope" — issues in OpenAlgo / OpenClaw / external test-deps (report to upstream).
> - "Recognition" — credit reporters in CHANGELOG release notes if they want.
>
> **Style rules:**
>
> - British English throughout
> - No personal email addresses
> - No specific personal contact info
> - Use the GitHub-native reporting channels
>
> **What to read for context:**
> - The approved spec at `docs/superpowers/specs/2026-05-20-public-repo-modernisation-design.md`
> - The current `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`
> - `LICENSE` (AGPL-3.0)
>
> **Output:** Write all three files. Do NOT commit.

- [ ] **Step 2:** Receive output, spot-check.

- [ ] **Step 3:** Verify acceptance:

```bash
grep -ic "claude\.md\|agents\.md\|plan\.md" CONTRIBUTING.md   # Expected: 0
grep -ic "contributor covenant" CODE_OF_CONDUCT.md            # Expected: ≥1
grep -ic "security advisor" SECURITY.md                       # Expected: ≥1
```

### Parcel 5 — `.github/` metadata (parallel)

**Files:**
- Modify or verify: `.github/ISSUE_TEMPLATE/bug_report.md`
- Modify or verify: `.github/ISSUE_TEMPLATE/feature_request.md`
- Create or verify: `.github/ISSUE_TEMPLATE/question.md`
- Create or verify: `.github/ISSUE_TEMPLATE/config.yml` (so the templates show up nicely in the New Issue UI)
- Modify: `.github/PULL_REQUEST_TEMPLATE.md`
- Create: `.github/FUNDING.yml`
- Verify: `.github/CODEOWNERS`

- [ ] **Step 1:** Dispatch a general-purpose subagent with this brief.

> **Agent type:** `general-purpose`
> **Description:** Audit and write .github/ project metadata
>
> **Brief:**
>
> Audit and write standard GitHub OSS metadata files under `c:\Users\navan\Documents\GitHub\FlintTrade\.github\`.
>
> **Step A:** List current contents.
> ```bash
> ls -la .github/
> ls -la .github/ISSUE_TEMPLATE/
> cat .github/PULL_REQUEST_TEMPLATE.md
> cat .github/CODEOWNERS
> ```
>
> **Step B:** Write/update these files:
>
> 1. **`.github/ISSUE_TEMPLATE/bug_report.md`** — Markdown front-matter with `name`, `about`, `labels: bug`. Sections: Describe the bug, To reproduce, Expected behaviour, Screenshots, Environment (FlintTrade version, OS, browser, OpenAlgo version, broker), Additional context.
>
> 2. **`.github/ISSUE_TEMPLATE/feature_request.md`** — front-matter with `labels: enhancement`. Sections: Is your feature request related to a problem? Describe the solution you'd like. Describe alternatives you've considered. Additional context. Persona (Trader / Investor / Beginner / Developer).
>
> 3. **`.github/ISSUE_TEMPLATE/question.md`** — front-matter with `labels: question`. Sections: Question. What I tried. What docs I've checked.
>
> 4. **`.github/ISSUE_TEMPLATE/config.yml`** — disable blank issues, link contact_links to Discussions (if you have Discussions enabled) and SECURITY.md for security issues. Use this exact format:
>    ```yaml
>    blank_issues_enabled: false
>    contact_links:
>      - name: Security vulnerability
>        url: https://github.com/navaneeshnagarajan/FlintTrade/security/advisories/new
>        about: Report security issues privately via GitHub Security Advisories.
>      - name: GitHub Discussions
>        url: https://github.com/navaneeshnagarajan/FlintTrade/discussions
>        about: Ask questions and discuss FlintTrade with the community.
>    ```
>
> 5. **`.github/PULL_REQUEST_TEMPLATE.md`** — Checklist-style:
>    - Summary (2-3 sentences)
>    - Linked issue (if any)
>    - Type of change (bug fix / feature / docs / refactor / test / chore)
>    - Persona affected (trader / investor / beginner / developer / N/A)
>    - Testing done (commands run + outputs)
>    - Screenshots (for UI changes)
>    - Checklist: tests added/updated, docs updated, CHANGELOG entry, ruff clean, tsc clean, conventional commit, no personal info in commit messages
>
> 6. **`.github/FUNDING.yml`** — multi-platform sponsorship:
>    ```yaml
>    github: [navaneeshnagarajan]
>    buy_me_a_coffee: navaneeshvn
>    patreon: navaneeshvn
>    custom:
>      - https://razorpay.me/@flinttrade
>    ```
>    Use these handle names as placeholders. User will edit them later if the actual handles differ. (Keep `github:` line — user has not confirmed others, but the spec says multi-platform; user can null out unused lines after this PR.)
>
> 7. **`.github/CODEOWNERS`** — verify current contents. Default rule should be `* @navaneeshnagarajan`. If anything else is in there, leave the additional rules as-is unless they reference now-moved files. Make sure no rule references CLAUDE.md / AGENTS.md / PLAN.md / docs/research/ / docs/status/ (all moved/archived in this session).
>
> **Style rules:**
>
> - British English throughout
> - Issue templates use Markdown checkbox lists where helpful
> - PR template uses GitHub task-list syntax (`- [ ]`) so reviewers can tick items
> - No personal email or hardware info
>
> **Output:** Write all files. Do NOT commit (orchestrator commits at parcel end).

- [ ] **Step 2:** Receive output, spot-check the YAML.

- [ ] **Step 3:** Verify acceptance:

```bash
ls .github/ISSUE_TEMPLATE/   # Expected: bug_report.md feature_request.md question.md config.yml
test -f .github/FUNDING.yml
test -f .github/PULL_REQUEST_TEMPLATE.md
grep "navaneeshnagarajan" .github/CODEOWNERS   # Expected: at least one match
```

### Commit Parcels 2-5

After all four parallel parcels return:

- [ ] **Step 1:** Verify aggregate state.

```bash
git status
```

- [ ] **Step 2:** Commit each parcel separately for clean history.

```bash
# Parcel 2 — README
git add README.md
git commit -m "docs(readme): rewrite hybrid trader/developer layout for public release"

# Parcel 3 — docs/ restructure
git add docs/
git commit -m "docs(restructure): split USER_GUIDE / DEVELOPER_GUIDE / API; rename CI; archive stale"

# Parcel 4 — governance
git add CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md
git commit -m "docs(governance): refresh CONTRIBUTING + CoC + SECURITY for public OSS contributors"

# Parcel 5 — .github/
git add .github/
git commit -m "feat(.github): bug/feature/question issue templates + PR checklist + FUNDING + CODEOWNERS"
```

---

## Parcel 6 — Per-package READMEs + stale-content sweep (sequential, runs last)

### Task 6.1: Generate 16 per-package READMEs

**Files:** Create `packages/<pkg>/README.md` for each of the 16 packages.

- [ ] **Step 1:** Author the per-package purpose statements.

Create a temporary scratch file `templates/package-purposes.yml` (will be archived after use, not tracked long-term):

```yaml
ai:
  purpose: "Local LLM client, RAG pipeline, multi-agent trading team, ML signal generation, and skill swarm."
  entry_points: ["llm_client.py", "rag.py", "multi_agent.py", "advisor.py"]
automation:
  purpose: "Cron scheduler, Telegram bot with kill switch, OpenClaw bridge, post-market analysis pipelines, voice-order intent extraction."
  entry_points: ["cron_manager.py", "telegram_bot.py", "voice_orders.py"]
backtest-engine:
  purpose: "Strategy simulator, walk-forward + Monte Carlo, portfolio backtester, and 94 strategy templates across 6 categories."
  entry_points: ["simulator.py", "engine.py", "metrics.py", "portfolio_backtester.py"]
chrome-extension:
  purpose: "Browser extension for quick trading from any page (manifest v3)."
  entry_points: ["manifest.json", "content.js", "popup.html"]
core:
  purpose: "Flask app, OpenAlgo client (45+ endpoints), config + workspace management, auth service (argon2id + Fernet TOTP + JWT), and the WSGI prefix-stripper."
  entry_points: ["app.py", "openalgo_client.py", "auth_service.py", "config.py"]
data:
  purpose: "Tick recorder, audit logger (SEBI 5-year retention), trade logger, DuckDB storage, QuestDB writer/bridge, Excel bridge."
  entry_points: ["tick_recorder.py", "audit_logger.py", "questdb_writer.py"]
desktop:
  purpose: "Tauri-based native desktop app wrapper (scaffolded)."
  entry_points: ["src-tauri/Cargo.toml", "src-tauri/tauri.conf.json"]
ditto:
  purpose: "Multi-account manager: position mirror, margin calculator, trailing stop-loss, risk manager (AlgoMirror patterns absorbed)."
  entry_points: ["mirror.py", "margin_calculator.py", "trailing_sl.py", "risk_manager.py"]
engine:
  purpose: "Five-layer safety system, order router, scheduler, base strategy, sandbox executor (AST-guarded), bracket-order engine, mode guard, reconciliation."
  entry_points: ["safety.py", "router.py", "strategy.py", "sandbox_executor.py"]
gateway:
  purpose: "Direct broker connections (32 brokers via OpenAlgo adapter pattern), encrypted credentials, WebSocket bridge."
  entry_points: ["adapter.py", "auth.py", "credentials.py", "registry.py", "ws_bridge.py"]
historical:
  purpose: "OHLCV downloader, free-data sources (OpenChart + yfinance), DuckDB pipeline, expiry manager for derivatives."
  entry_points: ["downloader.py", "openchart.py", "expiry_tracker.py", "nse_session.py"]
indicators:
  purpose: "43 indicator functions across 7 modules — TA-Lib (batch, 150+ indicators) + Numba (streaming) + PineTS (Pine Script conversion)."
  entry_points: ["trend.py", "momentum.py", "oscillators.py", "volatility.py", "volume.py"]
integration:
  purpose: "TradingView webhooks, ChartInk integration, custom webhooks, flow builder, alerter, n8n bridge, WhatsApp bridge."
  entry_points: ["webhook_receiver.py", "chartink.py", "n8n_bridge.py"]
screener:
  purpose: "Option chain, OI analysis, PCR, max pain, futures quadrant, portfolio Greeks, IV smile, fundamental screener, FII/DII tracker, RRG calculator."
  entry_points: ["optionchain.py", "max_pain.py", "rrg.py", "fundamental.py"]
terminal:
  purpose: "React 19 + TypeScript + Vite single-page terminal — Dockview workspace, 82 widgets, 7 tools, 13 workspace presets, 12 public routes."
  entry_points: ["src/main.tsx", "src/layout/widgetFactory.tsx", "src/services/api.ts"]
tick-engine:
  purpose: "High-performance tick processing engine (Rust core with Python bindings via PyO3)."
  entry_points: ["src/lib.rs", "src/processor.rs", "Cargo.toml"]
```

- [ ] **Step 2:** Generate each `packages/<pkg>/README.md` using this template:

```markdown
# <Package Name>

<one-line purpose from YAML>

## Install

This package is part of the FlintTrade monorepo and is installed via the workspace. To use it standalone:

```bash
uv pip install -e packages/<pkg>
```

(For Rust / Node packages, replace with the appropriate command.)

## Public API

The most important entry points:

- `<entry_point_1>` — <one-line purpose>
- `<entry_point_2>` — ...
- ...

(See the source for the full surface.)

## Tests

```bash
# Python packages:
pytest packages/<pkg>/tests/ -v

# React (terminal):
cd packages/apps/terminal && npx vitest run

# Rust (tick-engine):
cd packages/core/ticks && cargo test
```

## Architecture

This package's role in the wider FlintTrade architecture is documented in [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) and [docs/DEVELOPER_GUIDE.md](../../docs/DEVELOPER_GUIDE.md).

## License

AGPL-3.0 (same as the parent repository).
```

Loop over the 16 packages and write each README.

- [ ] **Step 3:** Verify all 16 exist and the count.

```bash
find packages -maxdepth 2 -name README.md | wc -l   # Expected: 16
```

### Task 6.2: Stale-content sweep

**Files:** Walk every tracked `.md` and check freshness.

- [ ] **Step 1:** List remaining tracked `.md` files.

```bash
git ls-files | grep -E "\.md$" | sort
```

- [ ] **Step 2:** For each file, open it and check:
- Does the first paragraph reference deprecated versions (`v0.1.0`, `v0.2.0`, etc.) as "current"?
- Does it reference deleted files (CLAUDE.md, AGENTS.md, PLAN.md, machine-setup/, research/, status/)?
- Does it reference deprecated workflows ("DEVLOG.md", "submodules", "AlgoMirror bridge")?

For each flagged file, choose:
- **Rewrite** if salvageable in 5 minutes
- **Archive** to `.local/archive/docs-internal/` with `ARCHIVE_LOG.md` entry

- [ ] **Step 3:** Refresh `VERSION` file — verify it reads `0.5.2-dev`.

```bash
cat VERSION   # Expected: 0.5.2-dev
```

- [ ] **Step 4:** Refresh `CHANGELOG.md` `[Unreleased]` section.

Open `CHANGELOG.md` and add an `[Unreleased]` entry summarising this modernisation pass:

```markdown
## [Unreleased]

### Changed
- **Public repo modernisation** — moved 35 AI-tool-internal `.md` files (CLAUDE.md / AGENTS.md / PLAN.md across root + 16 packages) out of git tracking into machine-local `.local/agent-context/`, scaffolded from new tracked templates at `templates/agent-context/` via `scripts/setup-agent-context.sh`.
- **README** rewritten for hybrid trader + developer audience.
- **docs/** restructured — new `USER_GUIDE.md` / `DEVELOPER_GUIDE.md` / `API.md`; release notes moved to `docs/releases/`; `machine-setup/` renamed `setup/`; `CI_BUDGET_AND_QUALITY.md` softened and renamed `CI.md`.
- **Per-package READMEs** added for each of the 16 packages.

### Added
- `.github/ISSUE_TEMPLATE/{bug_report,feature_request,question}.md` + `config.yml`.
- `.github/FUNDING.yml` (GitHub Sponsors + Buy Me a Coffee + Patreon + custom).
- `.github/PULL_REQUEST_TEMPLATE.md` — checklist style.
- `scripts/setup-agent-context.sh` — idempotent agent-context scaffolder.

### Removed
- 35 tracked agent-internal `.md` files (preserved at `templates/agent-context/` + machine-local `.local/agent-context/`).
- `docs/COMPETITIVE_ANALYSIS.md`, `docs/research/`, `docs/status/`, `docs/superpowers/plans/` (archived to `.local/archive/docs-internal/`).
- `docs/REFERENCES.md` (full version archived; slimmer credits in new README footer).
```

### Task 6.3: Update `ARCHIVE_LOG.md`

**Files:** Modify `.local/archive/ARCHIVE_LOG.md`

- [ ] **Step 1:** Append a new top-level section to `.local/archive/ARCHIVE_LOG.md` covering this modernisation pass.

The section should list:
- All 35 agent-internal files moved (source path, destination at `templates/agent-context/`, scaffold destination at `.local/agent-context/`)
- All docs/ archives (`COMPETITIVE_ANALYSIS.md`, `research/`, `status/`, `superpowers/plans/`, `REFERENCES.md`)
- New files created (16 per-package READMEs, 4 new docs/, 5 new .github/)
- Acceptance criteria check (all 8 from the spec)

### Commit Parcel 6

- [ ] **Step 1:** Stage and commit.

```bash
git status

git add packages/*/README.md
git commit -m "docs(packages): add per-package READMEs to all 16 packages"

git add CHANGELOG.md
git commit -m "docs(changelog): record public repo modernisation pass under [Unreleased]"
```

---

## Final verification

### Task V.1: Acceptance criteria check

Walk through every line of §6 of the spec and verify on disk:

- [ ] Repo root has zero AI-tool-internal `.md` files:
```bash
ls *.md | grep -Ev "^(README|CHANGELOG|CONTRIBUTING|CODE_OF_CONDUCT|SECURITY|LICENSE|NOTICE)\.md$"
# Expected: empty output
```

- [ ] Each of the 16 packages has a tracked `README.md`:
```bash
find packages -maxdepth 2 -name README.md | wc -l   # Expected: 16
```

- [ ] No tracked CLAUDE.md / AGENTS.md / PLAN.md anywhere:
```bash
git ls-files | grep -iE "(claude|agents)\.md$"   # Expected: empty
git ls-files | grep "^PLAN\.md$"                  # Expected: empty
```

- [ ] `.gitignore` covers them going forward:
```bash
git check-ignore -v CLAUDE.md packages/core/CLAUDE.md PLAN.md
# Expected: gitignore rule fires for each
```

- [ ] README opens with trader-facing pitch (badges + screenshots above developer section):
```bash
head -100 README.md | grep -c "shields.io"   # Expected: ≥3 (badges)
```

- [ ] docs/ follows new structure:
```bash
ls docs/ | sort
# Expected: API.md ARCHITECTURE.md CI.md COMPATIBILITY.md DEVELOPER_GUIDE.md README.md SEBI_COMPLIANCE.md USER_GUIDE.md assets releases screenshots setup superpowers
```

- [ ] All stale docs archived to `.local/archive/docs-internal/`:
```bash
ls .local/archive/docs-internal/
# Expected: COMPETITIVE_ANALYSIS.md REFERENCES-full.md research status superpowers-plans
```

- [ ] `.github/` has issue templates + PR template + FUNDING + CODEOWNERS:
```bash
ls .github/
ls .github/ISSUE_TEMPLATE/
# Expected: bug_report.md feature_request.md question.md config.yml
```

- [ ] `scripts/setup-agent-context.sh` exists and works:
```bash
test -x scripts/setup-agent-context.sh   # exit 0 if executable
rm -rf .local/agent-context-smoke-test
SMOKE_DST=".local/agent-context-smoke-test" bash -c '
SRC=templates/agent-context
mkdir -p "$SMOKE_DST/packages"
while IFS= read -r tpl; do
  rel="${tpl#$SRC/}"
  out="${rel%.template}"
  mkdir -p "$(dirname "$SMOKE_DST/$out")"
  cp "$tpl" "$SMOKE_DST/$out"
done < <(find "$SRC" -type f -name "*.template")
find "$SMOKE_DST" -type f | wc -l
'   # Expected: 35
rm -rf .local/agent-context-smoke-test
```

- [ ] No application code, tests, or runtime behaviour modified:
```bash
git diff origin/main..HEAD --stat -- 'packages/**/src/**' 'packages/**/tests/**' 'tests/**'
# Expected: empty (no changes under src/ or tests/)
```

- [ ] `git status` clean:
```bash
git status --short   # Expected: empty
```

### Task V.2: Final commit summary

Verify the commit graph:

```bash
git log origin/main..HEAD --oneline
# Expected (in order):
# - chore(repo): move CLAUDE.md / AGENTS.md / PLAN.md out of tracked tree
# - docs(readme): rewrite hybrid trader/developer layout for public release
# - docs(restructure): split USER_GUIDE / DEVELOPER_GUIDE / API; rename CI; archive stale
# - docs(governance): refresh CONTRIBUTING + CoC + SECURITY for public OSS contributors
# - feat(.github): bug/feature/question issue templates + PR checklist + FUNDING + CODEOWNERS
# - docs(packages): add per-package READMEs to all 16 packages
# - docs(changelog): record public repo modernisation pass under [Unreleased]
# (7 commits total)
```

### Task V.3: Push (only on explicit user approval)

- [ ] Wait for user to explicitly say "push" or "push it".
- [ ] Run:

```bash
git push origin main
```

- [ ] Watch for CI activity:

```bash
sleep 5
gh run list --limit 5 --branch main
```

Note: CI may not trigger because the changes are mostly `.md` files matched by `paths-ignore: ['**.md', 'docs/**']` in `.github/workflows/test.yml`. This is expected and correct — no application code changed.

---

## Self-Review

(Performed inline after writing — placeholders / consistency / scope / ambiguity checks)

### Spec coverage
- [x] Goal — covered by Parcels 1-6
- [x] Strategic decisions (5) — locked into the plan
- [x] Six parcels — one task section each
- [x] Acceptance criteria (8 from spec) — Task V.1 checks each
- [x] Risk mitigations — embedded in task notes (e.g., Task 1.6 addresses the "templates must travel with clone" risk)

### Placeholder scan
- "user fills handles" in FUNDING.yml is a known acceptable placeholder (user-facing decision, not an agent task).
- All other code blocks, file contents, and commands are complete.

### Type consistency
- File paths consistent across tasks (e.g., `templates/agent-context/` used in both 1.6 and V.1).
- Package list consistent across Task 1.2, Task 6.1, and the per-package paths.

### Scope check
- Single implementation cycle.
- Seven commits, all in one push.
- ~5-7 hours of agent work (parallel middle parcels) + ~30 min orchestration.

---

## Execution choice

Two options to execute this plan:

**1. Subagent-Driven (recommended)** — One fresh subagent per parcel, two-stage review between parcels, fastest iteration.

**2. Inline Execution** — Execute tasks in the current session via `superpowers:executing-plans`, batched with checkpoints.

(Orchestrator will ask the user which to pick after this plan is written and reviewed.)

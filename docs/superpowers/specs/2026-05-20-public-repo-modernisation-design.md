# Public Repo Modernisation — Design

> **Date:** 2026-05-20
> **Status:** Approved (brainstorming gate passed)
> **Author:** Claude Code (Opus 4.7) with Navaneesh V N
> **Prior context:** Repo flipped public AGPL-3.0 on 2026-05-19. Current version then was `v0.5.2-dev`. Test counts and package counts in this historical design note are a point-in-time planning baseline; use the root README and live test commands for current numbers.

## 1. Goal

Make FlintTrade's public surface read as a polished, contributor-ready open-source project — not a personal development journal. End-state passes the "would a stranger fork this confidently?" test.

### Non-goals
- Not changing any application code, tests, or runtime behaviour.
- Not changing package layout or `pyproject.toml` metadata.
- Not deleting any content (memory rule: archive, never delete). Files moved to `.local/` or `.local/archive/`.

## 2. Strategic decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Cleanup aggressiveness | **Comprehensive overhaul** | Repo is now public; first impression must be strong. Surgical pass leaves too many "looks unmaintained" signals. |
| CLAUDE.md / AGENTS.md / PLAN.md (34 files total) | **Move to `.local/agent-context/` (untracked)** | Files remain useful for personal dev workflow on Nitro / Mac / Ubuntu, but stop shipping to the public repo. |
| README audience | **Hybrid — layered** | Trader pitch on top fold, developer view on second fold. One README, two audiences, no audience-switching for visitors. |
| Per-package READMEs | **Generate tiny per-package READMEs** | After removing per-package CLAUDE.md/AGENTS.md, each `packages/<pkg>/` would be bare. A small auto-generated README keeps the package navigable on GitHub. |
| FUNDING.yml | **Add with multiple platforms** | GitHub Sponsors + Buy Me a Coffee + Patreon. Project becomes financially supportable as it grows. |

## 3. Six-parcel structure

### Parcel 1 — De-scaffold the repo root (sequential, runs first)

Affects ~36 tracked files; reshapes the tree everything else writes into.

**Moves:**
- `CLAUDE.md` → `.local/agent-context/CLAUDE.md`
- `AGENTS.md` → `.local/agent-context/AGENTS.md`
- `PLAN.md` → `.local/agent-context/PLAN.md`
- For each of the 16 packages: `packages/<pkg>/CLAUDE.md` → `.local/agent-context/packages/<pkg>/CLAUDE.md`
- For each of the 16 packages: `packages/<pkg>/AGENTS.md` → `.local/agent-context/packages/<pkg>/AGENTS.md`

**Tracking:**
- `git rm` all 35 files
- Add gitignore rules: `/CLAUDE.md`, `/AGENTS.md`, `/PLAN.md`, `packages/*/CLAUDE.md`, `packages/*/AGENTS.md`

**Replacements:**
- 16 new tracked `packages/<pkg>/README.md` files (Parcel-6 deliverable, see below).
- New `scripts/setup-agent-context.sh` that scaffolds the `.local/agent-context/` tree from templates at `.local/agent-context-templates/` so other contributors can opt-in if they use a CLAUDE-aware / AGENTS-aware tool.

**Log entry** in `.local/archive/ARCHIVE_LOG.md` recording the moves with rationale and per-file disposition.

### Parcel 2 — README rewrite (parallel)

**Top fold (trader pitch):**
- Project name + tagline (~12 words)
- Badges row: License (AGPL-3.0), version, CI status, tests count, GitHub stars, last commit
- 4 hero screenshots (already in `docs/screenshots/` — pick the strongest 4)
- 5-minute Docker-Compose quickstart (3-4 commands max)
- "What you can do with it" — 6-8 bullet feature highlights aimed at retail F&O / commodity / crypto traders
- Supported brokers: 33 (link to full list in COMPATIBILITY.md)

**Second fold (developer view):**
- Architecture diagram (mermaid)
- 16-package map (table: name | purpose | tech | tests)
- Tech stack summary (frontend / backend / data / infra)
- Three CTAs: "Try it" → quickstart, "Build with it" → DEVELOPER_GUIDE, "Contribute" → CONTRIBUTING

**Footer:**
- Community links: GitHub Discussions, Issues, (optional Discord/Slack if you want)
- Project docs grid: USER_GUIDE / DEVELOPER_GUIDE / ARCHITECTURE / API / CHANGELOG / SECURITY
- Credits: OpenAlgo, OpenClaw, and the ~215 absorbed reference repos (link to docs/REFERENCES.md)
- License + Code of Conduct + Contributing pointers

**Style:**
- British English throughout (memory rule).
- No personal hostnames, IPs, hardware specs, broker names tied to the author. Sanitised per `c563bd5`.
- Concise, headline-grabbing first sentence. Skim-friendly subheads. Each section ~ 1 screen.

### Parcel 3 — Restructure `docs/` (parallel)

**Target structure:**
```
docs/
  README.md            (new — landing index)
  USER_GUIDE.md        (new — trader-facing)
  DEVELOPER_GUIDE.md   (new — contributor-facing)
  ARCHITECTURE.md      (keep, refresh)
  API.md               (new — endpoint reference)
  COMPATIBILITY.md     (keep)
  CI.md                (renamed from CI_BUDGET_AND_QUALITY.md, content softened)
  releases/
    v0.5.1.md          (moved from RELEASE_NOTES_v0.5.1.md)
    v0.5.2-dev.md      (moved from RELEASE_NOTES_v0.5.2-dev.md)
  setup/               (renamed from machine-setup/)
  assets/              (unchanged)
  screenshots/         (unchanged)
```

**Archived to `.local/archive/docs-internal/` (with ARCHIVE_LOG.md entry):**
- `docs/COMPETITIVE_ANALYSIS.md`
- `docs/research/`
- `docs/status/`
- `docs/superpowers/plans/` (this spec stays under `docs/superpowers/specs/` until merged)
- The original `RELEASE_NOTES_*.md` files (after copies move to `releases/`)
- `docs/REFERENCES.md` (currently a giant table of every absorbed repo — replace with a slimmer credits page; keep full version archived)

**Content rules:**
- `USER_GUIDE.md`: install → first connection → first paper trade → first live trade → workspace tour → screener / Lab / Automate / AI / Ditto walkthroughs
- `DEVELOPER_GUIDE.md`: repo layout → dev setup → test → build → adding a widget → adding a strategy → adding a broker adapter → security and compliance constraints
- `API.md`: OpenAlgo passthrough + FlintTrade `/ft-api/v1/` endpoints, request / response examples
- `ARCHITECTURE.md`: refreshed mermaid diagrams, package map, data flow, mode system, auth, WSGI prefix-strip explained

### Parcel 4 — CONTRIBUTING / Code of Conduct / SECURITY refresh (parallel)

**CONTRIBUTING.md:**
- Drop every reference to CLAUDE.md / AGENTS.md / PLAN.md (now in `.local/`)
- Add: "How to run the dev environment" (link to setup/), "How to add a feature", "How to run tests", "How to submit a PR" sections
- Conventional Commits enforcement explained
- "First issue" pointers (link to `good first issue` label)
- British English

**CODE_OF_CONDUCT.md:**
- Verify it matches Contributor Covenant v2.1
- Enforcement contact: GitHub-only, no personal email leak

**SECURITY.md:**
- Disclosure: GitHub Security Advisories (private) as primary; e-mail as fallback
- Supported versions table (currently: latest minor only, given pre-1.0 status)
- 90-day disclosure clock

### Parcel 5 — GitHub project metadata (parallel)

**`.github/` audit + additions:**
- `ISSUE_TEMPLATE/` — verify 3 templates exist (bug / feature / question); rewrite each for clarity if needed
- `PULL_REQUEST_TEMPLATE.md` — checklist-style (title format, tests added, docs updated, conventional commit)
- `FUNDING.yml` — multiple platforms (GitHub Sponsors `navaneeshnagarajan`, Buy Me a Coffee placeholder, Patreon placeholder; user fills handles)
- `CODEOWNERS` — verify after restructure; default everything to `@navaneeshnagarajan` until contributors emerge
- Repo topics (set via `gh repo edit`): `trading-platform`, `openalgo`, `nse`, `mcx`, `options-trading`, `python`, `react`, `typescript`, `agpl-3-0`, `india`

**README badges** (top fold, plain Markdown):
- License (shields.io)
- Latest release (shields.io reading from tags)
- CI status (`test.yml` workflow)
- Codecov / coverage (optional, only if Codecov already wired)
- GitHub stars
- "Made in India"

### Parcel 6 — Per-package READMEs + stale-content sweep (sequential, runs after 1)

**Per-package READMEs (16 new tracked files):**
Each `packages/<pkg>/README.md` contains:
- Title (package name, one-line purpose pulled from pyproject.toml description)
- Install/import snippet
- Public API surface (3-5 most important entry points)
- Tests command (`make test` filtered or `pytest packages/<pkg>/tests/`)
- Link back to root `docs/ARCHITECTURE.md`

Generation strategy:
- Auto-generate from `pyproject.toml` + a per-package YAML "purpose" file that I'll author by hand
- Output committed as plain Markdown — no build step on consumer side

**Stale-content sweep:**
- Walk every remaining tracked `.md`
- Flag any first-paragraph reference to legacy versions, deprecated workflows, retired features
- Archive flagged items (or rewrite if trivially salvageable)
- Refresh `VERSION` if mismatched (currently `0.5.2-dev` — should still be accurate)
- Refresh `CHANGELOG.md` `[Unreleased]` section to mention this modernisation pass

## 4. Execution shape

```
Parcel 1 (de-scaffold root + package agent-files)
        │
        ▼
Parcels 2 / 3 / 4 / 5 in parallel
  (README rewrite,
   docs/ restructure,
   CONTRIBUTING+CoC+SECURITY refresh,
   .github metadata)
        │
        ▼
Parcel 6 (per-package READMEs + stale-content sweep)
        │
        ▼
Verify acceptance criteria → commit per parcel → push (on explicit user approval)
```

- **Sequential head:** Parcel 1 runs first (it moves files; everything else writes into the reshaped tree).
- **Parallel middle:** Parcels 2, 3, 4, 5 dispatched simultaneously via specialised subagents (Technical Writer × 2, Project Shepherd, MCP Builder or general-purpose).
- **Sequential tail:** Parcel 6 runs after middle parcels return (so the new docs/ layout is finalised before per-package READMEs link to it). Then verification + commit + push.

**Commits:** one per parcel using conventional commit format (`chore(repo):`, `docs:`, `feat(.github):`).

**Push:** held until verification clean and user gives explicit "push" word.

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Removing CLAUDE.md / AGENTS.md breaks the user's own multi-machine workflow (Mac / Ubuntu pull a copy out of git) | `scripts/setup-agent-context.sh` scaffolds them from templates committed at `.local/agent-context-templates/`. User runs it once per machine after clone. Documented in `docs/setup/`. |
| New README sets the wrong tone — too marketing / too technical / wrong audience focus | Hybrid layout decision already locks the answer. Technical Writer agent gets clear style guide (British English, no personal info, target one-screen sections). Review gate before commit. |
| Stale content "sweep" archives something still useful | Memory rule: archive, never delete. Everything goes to `.local/archive/`, all logged. Reversible. |
| Per-package READMEs go out-of-date faster than the code | Generated from `pyproject.toml` description — single source of truth for one-liner. Public API surface section is hand-authored but small (3-5 entries), low maintenance. |
| Issue/PR templates clash with existing in-flight issues | Templates are forward-only. Existing issues unaffected. |
| Memory rule conflict: "never delete" vs `git rm` | `git rm` removes from tracking; file content is preserved on disk inside `.local/`. Not a delete in the memory-rule sense. |

## 6. Acceptance criteria

- [ ] Repo root has zero AI-tool-internal `.md` files (no CLAUDE.md, AGENTS.md, PLAN.md tracked at root).
- [ ] Each of the 16 packages has a tracked `README.md` and zero tracked agent-internal `.md` files.
- [ ] `.gitignore` covers all moved files going forward.
- [ ] Root `README.md` opens with a trader-facing pitch above the fold; developer view starts below ~screen 1.
- [ ] `docs/` follows the new structure exactly (`USER_GUIDE.md`, `DEVELOPER_GUIDE.md`, `API.md`, `ARCHITECTURE.md`, `releases/`, etc.).
- [ ] All stale docs archived to `.local/archive/docs-internal/` with `ARCHIVE_LOG.md` entry.
- [ ] `.github/` has bug / feature / question issue templates, a checklist PR template, a populated `FUNDING.yml`, and a verified CODEOWNERS.
- [ ] `scripts/setup-agent-context.sh` exists and works (smoke test: scaffolds CLAUDE.md and AGENTS.md to `.local/agent-context/` on a fresh clone).
- [ ] `git status` clean after each parcel commit. Final push is held until explicit user approval.
- [ ] No application code, tests, or runtime behaviour modified.

## 7. Open questions (none blocking)

None as of writing. All three follow-up answers gathered before this spec was written (per-package READMEs, FUNDING.yml platforms, comprehensive scope).

## 8. Next steps

1. User reviews this spec.
2. On approval, invoke `superpowers:writing-plans` skill to convert this design into a detailed step-by-step implementation plan with per-parcel checklists.
3. Dispatch parallel subagents per the execution shape in §4.
4. Verify all acceptance criteria, commit, push on user's go-ahead.

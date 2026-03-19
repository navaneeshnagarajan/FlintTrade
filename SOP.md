# FlintTrade — Standard Operating Procedure

> Every Claude Code session follows this workflow. No exceptions.
> Violations = broken trust. Read this BEFORE touching code.

## The Workflow

```
READ → PLAN → APPROVE → BUILD → VERIFY → TEST → FIX → UPDATE → COMMIT
```

### Step 1: READ (every session start)
- Read CLAUDE.md (single source of truth)
- Read PLAN.md (current roadmap and task list)
- Read SOP.md (this file)
- Read MEMORY.md (conversation context from prior sessions)
- Check DEVLOG.md for last session's work
- Check `git status` and `git log` for current state

### Step 2: PLAN
- Pick the next unchecked task from PLAN.md
- For non-trivial tasks: use `/brainstorm` and `/write-plan` skills
- Check REPO_FEATURE_MAP.md before writing ANY new code — absorb first, don't reinvent
- Check FINAL_SWEEP.md for related tracked items

### Step 3: APPROVE
- Present plan to user before implementing
- For trivial changes (typos, version bumps): proceed without asking
- For anything touching architecture, new files, or user-facing features: get approval

### Step 4: BUILD
- Use ALL available tools:
  - `frontend-design` skill for UI components
  - `vercel-react-best-practices` for React code
  - `context7` MCP for library API lookups (NEVER guess APIs)
  - Specialized agent teams (typescript-pro, react-specialist) for code
  - Absorb from cloned repos per REPO_FEATURE_MAP.md
- TypeScript strict mode — no `any` types
- shadcn/ui components — no raw HTML buttons/inputs/dialogs
- Every widget is a Dockview panel — no fixed layouts

### Step 5: VERIFY
- Use `superpowers:verification-before-completion` skill
- `tsc --noEmit` must pass (zero errors)
- `npm run build` must pass (zero warnings)
- Use `playwright` MCP for visual verification of UI changes
- Use `gstack` skill for QA screenshots
- Test with live OpenAlgo sandbox during market hours when possible

### Step 6: TEST
- `npx vitest run` — all tests must pass
- `make test` — all Python tests must pass (712+)
- Spec compliance review after each task group
- Code quality review after each task group
- Use `/simplify` after completing features

### Step 7: FIX
- Fix any failures from Steps 5-6
- Do NOT claim done until verification passes
- Do NOT skip failing tests

### Step 8: UPDATE
- Mark task done in PLAN.md
- Update DEVLOG.md with entry (one entry per commit):
  ```
  ## YYYY-MM-DD HH:MM IST | Machine | @username | IDE/Tool | AI Model/Agent | Branch | Summary
  ```
  Machines: `nitro-dev`, `mac-dev`, `ubuntu-server`

### Step 9: COMMIT + CI
- Conventional commit: `feat(pkg):`, `fix(pkg):`, `docs:`, `test:`, `chore:`
- Plan step numbers in commit body
- Specific file staging (never `git add -A`)
- Push to origin main
- **WAIT for GitHub Actions CI to pass** before moving to next task:
  - Check: `gh run list --limit 1` or `gh run watch <id> --exit-status`
  - CI runs 3 jobs: `python-tests` (pytest + ruff), `node-tests` (tsc + vitest + build), `secrets-check`
  - If CI fails: fix immediately before ANY new work. Use `gh run view <id> --log-failed` to diagnose.
  - Never leave CI red — a broken build blocks everyone.

## Enforced by Hooks
- **PostToolUse (Write|Edit):** Auto build check on TS/React files
- **Stop:** Remind to run tests and check SOP
- **PreToolUse (Bash):** Block destructive commands

## Rules (from spec Section 11)
1. Read MEMORY.md + CLAUDE.md + PLAN.md before any work
2. Check REPO_FEATURE_MAP.md before writing new code — absorb first
3. Get user approval for non-trivial changes
4. Use context7 MCP before guessing library APIs
5. Use Playwright for visual verification of UI changes
6. TypeScript strict mode — no `any` types
7. shadcn/ui components — no raw HTML buttons/inputs/dialogs
8. Every widget is a Dockview panel — no fixed layouts
9. Test with live OpenAlgo sandbox before claiming done
10. Conventional commits, specific file staging, never `git add -A`

## DO NOT
- Skip reading docs at session start
- Write code without checking repos for absorption first
- Bypass hooks with `bypassPermissions`
- Use general-purpose agents when specialized ones exist
- Batch multiple task groups into single commits
- Claim work is done without running verification
- Use mock/placeholder/fake data
- Hardcode API keys, hostnames, IPs, or personal values

## Available Tools (use actively — target 65-70% utilization)

### Skills
- `/brainstorm` — before major features
- `/write-plan` — structured implementation plans
- `/simplify` — after completing features
- `frontend-design` — UI component design
- `vercel-react-best-practices` — React code quality
- `web-design-guidelines` — UI review
- `superpowers:verification-before-completion` — before claiming done
- `superpowers:test-driven-development` — TDD guidance
- `gstack` — visual QA testing

### MCP Servers
- `context7` — live library documentation
- `playwright` — browser testing and screenshots
- `sequential-thinking` — complex reasoning
- `github` — GitHub operations
- `firecrawl` — web scraping and research

### Agent Teams
- `voltagent-lang:typescript-pro` — TypeScript code
- `voltagent-lang:react-specialist` — React components
- `feature-dev:code-reviewer` — code review
- `pr-review-toolkit:code-reviewer` — PR review

### Plugins
- `pyright-lsp` / `typescript-lsp` — real-time type checking
- `commit-commands` — proper git commits
- `pr-review-toolkit` — code review agents

> **HISTORICAL SNAPSHOT** — This audit was conducted before the 2026-03-19 v2 migration.
> All issues listed here have been addressed. See PLAN.md for current status.

# FlintTrade — Tools, Skills, Plugins & MCP Audit

> Generated: 2026-03-19 by Claude Code (Opus 4.6)
> Machine: Nitro (Windows 11, i5-13420H, RTX 5050)
> Scope: Everything available to Claude Code sessions on this project

---

## 1. Installed Plugins

Plugins extend Claude Code with specialized capabilities invoked via `/plugin` or automatically.

| # | Plugin | Source | What It Does | Using? | Notes |
|---|--------|--------|--------------|--------|-------|
| 1 | **superpowers** | obra/superpowers-marketplace | `/brainstorm`, `/write-plan`, `/execute-plan`, `/simplify`, `/debug` — structured planning, Socratic questioning, TDD workflows | YES | Core workflow. Use before every major feature. |
| 2 | **frontend-design** | anthropics/claude-code | UI/UX design guidance, component architecture, accessibility patterns | PARTIAL | Should use more for terminal widget design (F2-F8). |
| 3 | **skill-creator** | anthropics/claude-code | Create custom skills from conversation patterns | NO | Useful for codifying repetitive FlintTrade patterns (e.g., "create new widget" scaffold). |
| 4 | **claude-md-management** | anthropics/claude-code | Manage CLAUDE.md files, memory, project instructions | PARTIAL | Used indirectly. Could automate CLAUDE.md updates. |
| 5 | **voltagent-meta** | VoltAgent/awesome-claude-code-subagents | Meta-agent orchestration, spawn sub-agents for parallel work | NO | High potential for parallel package development (e.g., build screener + backtest simultaneously). |
| 6 | **voltagent-lang** | VoltAgent/awesome-claude-code-subagents | Language-aware sub-agents, polyglot code generation | NO | Useful when working across Python (packages) and React (terminal) in the same session. |

**Summary:** 6 plugins installed, 1 actively used, 2 partially used, 3 unused.

---

## 2. Installed Skills

Skills are invoked via slash commands or automatically when context matches.

### 2A. Superpowers Skills (from plugin)

| # | Skill / Command | Trigger | What It Does | Using? |
|---|----------------|---------|--------------|--------|
| 1 | `/brainstorm` | Manual | Socratic questioning, explores problem space, generates design docs | YES |
| 2 | `/write-plan` | Manual | Creates structured implementation plans with checkboxes | YES |
| 3 | `/execute-plan` | Manual | Builds from an existing plan file step by step | YES |
| 4 | `/simplify` | Manual | 3 parallel review agents analyze changed files for complexity | PARTIAL |
| 5 | `/debug` | Manual | Structured debugging workflow with hypothesis testing | NO |

### 2B. Vercel Skills (from vercel-labs/agent-skills)

| # | Skill | Trigger | What It Does | Using? |
|---|-------|---------|--------------|--------|
| 6 | **vercel-react-best-practices** | Auto/manual | React patterns: hooks, composition, error boundaries, performance | PARTIAL |
| 7 | **web-design-guidelines** | Auto/manual | Web design principles, typography, spacing, color theory | PARTIAL |
| 8 | **vercel-composition-patterns** | Auto/manual | Component composition, render props, compound components | NO |
| 9 | **deploy-to-vercel** | Manual | Vercel deployment configuration and optimization | NO |
| 10 | **vercel-react-native-skills** | Auto/manual | React Native patterns (not relevant for FlintTrade web) | NO |

### 2C. Other Skills

| # | Skill | Trigger | What It Does | Using? |
|---|-------|---------|--------------|--------|
| 11 | **find-skills** | Manual | Discover and install new skills from registries | NO |
| 12 | **planning-with-files** | Auto | File-based planning, creates plan files in project | PARTIAL |
| 13 | **pi-planning-with-files** | Auto | Enhanced planning with PI (Program Increment) structure | NO |
| 14 | **gstack** | Manual | Full-stack project scaffolding and patterns | NO |
| 15 | **taste-skill** | Manual | Code taste and style evaluation | NO |

### 2D. Firecrawl Skills (8 skills from firecrawl-cli)

| # | Skill | Trigger | What It Does | Using? |
|---|-------|---------|--------------|--------|
| 16-23 | **firecrawl** (8 variants) | Manual/auto | Web scraping, crawling, content extraction, browser automation | NO |

**Summary:** 23 skills installed, 3 actively used, 4 partially used, 16 unused.

---

## 3. MCP Servers

MCP (Model Context Protocol) servers provide Claude Code with external tool access.

### 3A. Verified Active in This Session

These were confirmed available via deferred tool discovery in the current session:

| # | MCP Server | Status | Tools Provided | What It Does | Using? |
|---|-----------|--------|----------------|--------------|--------|
| 1 | **playwright** | ACTIVE | 22 tools (navigate, click, snapshot, screenshot, fill_form, evaluate, type, drag, tabs, console, network, etc.) | Headless browser automation for testing terminal UI | PARTIAL |
| 2 | **context7** | ACTIVE | 2 tools (resolve-library-id, query-docs) | Live, version-specific library documentation lookup | PARTIAL |
| 3 | **OpenAlgo MCP** | ACTIVE | 1 tool (searchDocumentation) | Search OpenAlgo docs for API reference, guides, examples | PARTIAL |

### 3B. Configured but Not Verified in This Session

These are installed per REPOS.md but their availability could not be confirmed via tool discovery:

| # | MCP Server | Expected Status | What It Does | Using? |
|---|-----------|----------------|--------------|--------|
| 4 | **memory** | CONFIGURED | Persistent knowledge graph across sessions, entity/relation storage | UNKNOWN |
| 5 | **sequential-thinking** | CONFIGURED | Structured multi-step reasoning for complex decisions | UNKNOWN |
| 6 | **github** | CONFIGURED | GitHub API access (repos, PRs, issues, code search) via MCP | UNKNOWN |
| 7 | **firecrawl** | CONFIGURED | Web scraping and browser automation via MCP | UNKNOWN |

**Note:** No `.mcp.json` file exists at the project root. MCP servers are configured globally via `claude mcp add` commands, stored in `~/.claude/settings.json` (not readable from sandbox).

**Summary:** 7 MCP servers configured, 3 verified active, 4 status unknown.

---

## 4. Available Agents

Per REPOS.md, the **agency-agents** collection (from github.com/msitarzewski/agency-agents) provides 156+ agents installed to `~/.claude/agents/`.

### Agent Categories (estimated from the agency-agents collection)

| # | Category | Est. Count | Relevant to FlintTrade? |
|---|----------|-----------|------------------------|
| 1 | **Engineering** | ~20 | YES — code review, architecture, refactoring |
| 2 | **Design** | ~15 | YES — UI/UX for terminal, dashboard, backtest |
| 3 | **Testing** | ~15 | YES — test strategy, QA automation, E2E |
| 4 | **Product** | ~12 | PARTIAL — feature prioritization, roadmap |
| 5 | **Strategy** | ~10 | PARTIAL — technical strategy, system design |
| 6 | **Specialized** | ~20 | PARTIAL — domain experts (finance, data, ML) |
| 7 | **Marketing** | ~12 | LOW — future open-source promotion |
| 8 | **Sales** | ~10 | LOW — not relevant currently |
| 9 | **Support** | ~10 | LOW — future community support |
| 10 | **Academic** | ~8 | LOW — research references |
| 11 | **Game Dev** | ~8 | NO |
| 12 | **Spatial Computing** | ~6 | NO |
| 13 | **Project Management** | ~10 | PARTIAL — sprint planning, task tracking |
| 14 | **Paid Media** | ~5 | NO |

**Additional agent collection** referenced in REPOS.md:
- **wshobson/agents** — 112 agents, 146 skills, 16 orchestrators, 79 tools (not confirmed installed)

**Summary:** 156+ agents installed across 14 categories. ~50 are directly relevant to FlintTrade.

---

## 5. Built-in Claude Code Commands

These require no installation and are always available.

| # | Command | What It Does | Using? |
|---|---------|--------------|--------|
| 1 | `/compact` | Compress conversation history to save context | YES |
| 2 | `/review` | Code review with security, performance, correctness checks | PARTIAL |
| 3 | `/batch` | Process multiple files/tasks in parallel | NO |
| 4 | `/loop` | Iterative refinement until a condition is met | NO |
| 5 | `/diff` | Interactive diff viewer of all changes | PARTIAL |

---

## 6. Built-in Tools (Always Available)

| # | Tool | Category | What It Does |
|---|------|----------|--------------|
| 1 | **Read** | File I/O | Read files, images, PDFs, notebooks |
| 2 | **Write** | File I/O | Create or overwrite files |
| 3 | **Edit** | File I/O | Exact string replacements in files |
| 4 | **Bash** | Execution | Run shell commands |
| 5 | **Glob** | Search | Fast file pattern matching |
| 6 | **Grep** | Search | Regex content search (ripgrep) |
| 7 | **WebSearch** | Web | Search the internet for current information |
| 8 | **WebFetch** | Web | Fetch and process web page content |
| 9 | **TodoWrite** | Task Mgmt | Structured task tracking within a session |
| 10 | **NotebookEdit** | Jupyter | Edit Jupyter notebook cells |
| 11 | **EnterWorktree** | Git | Create isolated git worktree for parallel work |
| 12 | **ExitWorktree** | Git | Leave and optionally remove a worktree |
| 13 | **ToolSearch** | Discovery | Find and load deferred tool schemas |
| 14 | **Skill** | Skills | Invoke installed skills |

---

## 7. Recommendations — What We Should Be Using But Aren't

### HIGH PRIORITY (start immediately)

| # | Tool/Skill | Why | Action |
|---|-----------|-----|--------|
| 1 | **context7 MCP** (actively) | We have React (lightweight-charts, recharts, lucide-react), Tailwind CSS v4, and Python libraries that change APIs frequently. context7 gives live docs instead of guessing. | Before writing any library code, call `resolve-library-id` then `query-docs` to get current API. |
| 2 | **playwright MCP** (for terminal testing) | The terminal UI (port 5173) has 8 modules planned. Manual testing is slow. Playwright can snapshot, screenshot, and interact with every widget. | After building each F1-F8 module, run playwright to navigate, snapshot, and verify rendering. |
| 3 | **OpenAlgo MCP** (for API accuracy) | Every Python package talks to OpenAlgo. searchDocumentation ensures we use correct endpoints, parameters, and rate limits. | Before implementing any OpenAlgo API call, search the docs first. |
| 4 | **frontend-design plugin** | Terminal F2-F8 modules need professional design. This plugin provides UI/UX guidance, accessibility, and component architecture. | Invoke before designing any new widget or module layout. |
| 5 | **`/batch` command** | We have 10 Python packages and 3 React packages. Batch processing for linting, testing, or refactoring across packages saves time. | Use for cross-package operations (e.g., update all imports, run all tests). |
| 6 | **`/debug` command** | WebSocket connections, CORS issues, and live data bugs are common in trading platforms. Structured debugging beats ad-hoc troubleshooting. | Use when encountering runtime errors, especially in data pipelines and WebSocket feeds. |

### MEDIUM PRIORITY (adopt within next 2 weeks)

| # | Tool/Skill | Why | Action |
|---|-----------|-----|--------|
| 7 | **skill-creator plugin** | Repetitive patterns like "create new FlintTrade package", "add new terminal widget", "add new OpenAlgo endpoint wrapper" should be codified as custom skills. | Create 3 custom skills: `new-widget`, `new-package`, `new-endpoint`. |
| 8 | **voltagent-meta plugin** | Parallel development of independent packages (e.g., screener + historical + backtest-engine) would multiply throughput. | Use when Antigravity is unavailable but parallel work is needed. |
| 9 | **`/simplify` command** | After completing each major feature, run simplify to catch over-engineering. Trading platforms need lean, maintainable code. | Run after every feature completion, before committing. |
| 10 | **`/loop` command** | Iterative refinement for things like theme consistency, API response handling, and test coverage improvement. | Use for "make all widgets match the design system" type tasks. |
| 11 | **vercel-composition-patterns** | Terminal has nested widget hierarchy (sidebar > module > panel > widget). Compound component patterns prevent prop drilling. | Invoke when building the widget system for F2-F8. |
| 12 | **memory MCP** | Persistent knowledge graph could track: which OpenAlgo endpoints are tested, which widgets are complete, known bugs. | Configure and use for cross-session state tracking. |

### LOW PRIORITY (adopt when relevant)

| # | Tool/Skill | Why | Action |
|---|-----------|-----|--------|
| 13 | **firecrawl skills** | Useful for scraping competitor trading terminals (Groww, OiPulse, 1Cliq) for design research. Already doing this manually. | Use when resuming terminal design research (222 repos cloned per memory). |
| 14 | **sequential-thinking MCP** | Complex multi-step decisions like SEBI compliance architecture, multi-broker routing logic, or risk management design. | Use for architecture decisions that have cascading consequences. |
| 15 | **github MCP** | PR management, issue tracking. Currently using GitHub Desktop. | Use when the project moves to PR-based workflow (post v0.x). |
| 16 | **gstack skill** | Full-stack scaffolding. FlintTrade already has its structure defined. | Only if starting a completely new package from scratch. |
| 17 | **agency-agents** (engineering, testing, design) | The ~50 relevant agents could provide specialized reviews. | Use select agents for architecture review, security audit, UX review. |

### NOT NEEDED (can skip)

| # | Tool/Skill | Why Skip |
|---|-----------|----------|
| 18 | **deploy-to-vercel** | FlintTrade deploys to Ubuntu server, not Vercel. |
| 19 | **vercel-react-native-skills** | FlintTrade is web-only. No React Native. |
| 20 | **pi-planning-with-files** | Overkill for a solo/small-team project. `/write-plan` is sufficient. |
| 21 | **game-dev agents** | Not a game. |
| 22 | **spatial-computing agents** | Not a VR/AR project. |
| 23 | **paid-media agents** | Not running ads. |
| 24 | **taste-skill** | Subjective. Ruff + ESLint handle code style objectively. |

---

## 8. Workflow Optimization — Combining Tools for Maximum Efficiency

### Workflow A: Building a New Terminal Widget (F2-F8)

```
1. /brainstorm          — Explore widget requirements, data sources, interactions
2. /write-plan          — Create step-by-step implementation plan
3. frontend-design      — Get UI/UX guidance, component structure, accessibility
4. context7 MCP         — Look up lightweight-charts, recharts, Tailwind v4 APIs
5. OpenAlgo MCP         — Verify the API endpoints the widget will consume
6. /execute-plan        — Build the widget
7. playwright MCP       — Navigate to localhost:5173, snapshot, verify rendering
8. /simplify            — Review for over-engineering
9. /review              — Security + performance check
10. Update PLAN.md + DEVLOG.md
```

### Workflow B: Building a New Python Package Feature

```
1. /brainstorm          — Explore the feature scope
2. /write-plan          — Plan implementation
3. OpenAlgo MCP         — Verify all API endpoints needed
4. context7 MCP         — Look up DuckDB, chromadb, or other library APIs
5. /execute-plan        — Build the feature with tests
6. /debug               — If runtime errors occur
7. make test            — Run full test suite (must pass 670+)
8. /simplify            — Review
9. Update PLAN.md + DEVLOG.md
```

### Workflow C: Cross-Package Refactoring

```
1. /batch               — Process multiple packages in parallel
2. /loop                — Iteratively refine until all packages conform
3. make test            — Verify nothing broke
4. /review              — Final check
```

### Workflow D: Debugging Live Data Issues (WebSocket, CORS, API)

```
1. /debug               — Structured hypothesis testing
2. OpenAlgo MCP         — Verify expected API behavior
3. playwright MCP       — Check browser console for errors, network requests
4. context7 MCP         — Look up WebSocket or fetch API patterns
5. Fix and verify
```

### Workflow E: Design Research (Terminal UI)

```
1. firecrawl skills     — Scrape competitor terminal UIs
2. playwright MCP       — Navigate and screenshot competitor sites
3. frontend-design      — Synthesize findings into FlintTrade design system
4. /write-plan          — Plan the UI implementation
```

### Workflow F: Pre-Commit Quality Gate

```
1. make test            — All 670+ tests pass
2. npm run build        — Clean build for React packages
3. /simplify            — Complexity review
4. /review              — Security, performance, correctness
5. Conventional commit  — feat(pkg): / fix(pkg): / etc.
```

---

## 9. Tool Inventory Summary

| Category | Installed | Actively Used | Partially Used | Unused |
|----------|-----------|---------------|----------------|--------|
| Plugins | 6 | 1 | 2 | 3 |
| Skills | 23 | 3 | 4 | 16 |
| MCP Servers | 7 | 0 | 3 | 4 |
| Agents | 156+ | 0 | 0 | 156+ |
| Built-in Commands | 5 | 1 | 2 | 2 |
| Built-in Tools | 14 | ~10 | ~2 | ~2 |
| **TOTAL** | **211+** | **15** | **13** | **183+** |

**Utilization rate: ~13%** — We are using roughly 1 in 8 available tools.

### Top 5 Quick Wins to Improve Utilization

1. **Use context7 before every library API call** — eliminates API guessing and outdated patterns
2. **Use playwright after every UI change** — automated visual verification, catch regressions
3. **Use OpenAlgo MCP before every endpoint implementation** — ensures API accuracy
4. **Use `/simplify` after every feature** — prevents complexity creep in a monorepo
5. **Create 3 custom skills with skill-creator** — `new-widget`, `new-package`, `new-endpoint` scaffolds

---

## 10. Missing Tools Worth Installing

| # | Tool | What It Does | Why We Need It | Install |
|---|------|--------------|----------------|---------|
| 1 | **eslint-plugin-react-hooks** | Lint React hooks rules | Catch hooks violations in terminal | `npm install -D eslint-plugin-react-hooks` |
| 2 | **@testing-library/react** | React component testing | Test terminal widgets without browser | `npm install -D @testing-library/react` |
| 3 | **msw (Mock Service Worker)** | Mock OpenAlgo API in tests | Test terminal without live API | `npm install -D msw` |
| 4 | **vitest** | Fast Vite-native test runner | Matches our Vite build setup | `npm install -D vitest` |
| 5 | **lighthouse-ci** | Performance auditing | Trading terminals need sub-100ms updates | `npm install -D @lhci/cli` |

---

*This audit should be re-run quarterly or when new tools/skills are installed.*
*Next audit due: 2026-06-19*

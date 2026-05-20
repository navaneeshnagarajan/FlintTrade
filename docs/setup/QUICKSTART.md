# Machine Setup Guide

> Works on any Windows, macOS, or Ubuntu machine — including a new contributor's box.

## 1. Clone and Install

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
make setup
```

`make setup` installs: Python deps, Node deps, workspace init.

OpenAlgo (and OpenClaw) are no longer bundled as git submodules. They are external services FlintTrade talks to over HTTP/WebSocket. Install OpenAlgo separately, OR run the helper to clone a local-dev copy. AlgoMirror is intentionally absent — its mirroring logic is absorbed in-process by `packages/ditto/`, nothing external to install.

```bash
bash scripts/setup-test-deps.sh
```

This populates `.local/external/openalgo/` (gitignored) with a working OpenAlgo clone you can run via `make start`.

## 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` — set `OPENALGO_API_KEY` (get from OpenAlgo web UI after broker login).

## 3. Configure OpenAlgo Broker

Edit OpenAlgo's own `.env` — for the local-dev clone, that's `.local/external/openalgo/.env` (copy from `.sample.env` if needed):
- Set broker name (e.g., your broker or its sandbox variant for testing)
- Set broker credentials (client ID, API key/secret)

## 4. Start and Verify

```bash
make start       # Starts OpenAlgo on port 5000
make status      # Verify API responding
make test        # ~9,089 tests pass
```

## 5. Run Terminal

```bash
cd packages/terminal
npm run dev      # Terminal on http://localhost:5173
```

## 6. Start Building

Read [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the contribution flow, then check the [issue tracker](https://github.com/navaneeshnagarajan/FlintTrade/issues) — the `good first issue` label is a good place to land your first PR. If you use a CLAUDE-aware or AGENTS-aware coding agent (Claude Code, Cursor, Aider, Continue, Codex, etc.), run `bash scripts/setup-agent-context.sh` once to scaffold your machine-local agent context.

---

## OpenAlgo Broker Login

1. Open http://127.0.0.1:5000 in browser
2. Create account on first run
3. Select broker (use sandbox variant for testing)
4. Login to broker via OAuth redirect
5. Go to API Key section, generate key
6. Put key in FlintTrade `.env` as `OPENALGO_API_KEY`

Sessions expire at ~3:30 AM IST. Re-login daily when using live broker.

## Terminal .env

`packages/terminal/.env` is gitignored. The Vite proxy in `vite.config.ts` already forwards `/api` to OpenAlgo, `/ft-api` to the FlintTrade backend, and `/ws` to the WebSocket — you should not need a terminal-side `.env` for normal development.

```
# Only the host/WS endpoints are configurable from VITE_* env vars.
# DO NOT put the API key here — Vite inlines VITE_* at build time, leaking
# the key into the production JS bundle. Configure OPENALGO_API_KEY in the
# in-app Settings → Connection flow (it persists to ~/.flinttrade/workspace.json,
# server-side only) or in the repo-root .env which the FlintTrade backend reads.
VITE_OPENALGO_HOST=http://127.0.0.1:5000
VITE_OPENALGO_WS=ws://127.0.0.1:8765
```

## Claude Code Skills & Plugins

All machines should have these installed globally:

**Skills:** superpowers (brainstorm/write-plan/execute-plan/TDD/debugging), frontend-design, vercel-react-best-practices, web-design-guidelines, planning-with-files, find-skills, gstack, firecrawl

**Agents:** 172 agency-agents in `~/.claude/agents/` (engineering, design, testing, product, strategy, marketing, sales, etc.)

**MCP Servers:** context7 (live library docs), playwright (browser testing), sequential-thinking, github, firecrawl

Install agents from the `agency-agents` repo:
```bash
# Copy all .md files from category folders into ~/.claude/agents/
cp ~/agency-agents/{academic,design,engineering,game-development,marketing,paid-media,product,project-management,sales,spatial-computing,specialized,strategy,support,testing}/*.md ~/.claude/agents/
```

## Reference Files (Not in Public Repo)

Design references (screenshots, scraped sites, broker UI analysis) live in `.reference/` at the repo root. This directory is gitignored but should be kept in sync across machines manually or via a shared drive.

```
.reference/
  screenshots/     # Broker UI screenshots (OiPulse, 1Cliq, Dhan, FYERS, etc.)
  scraped/         # Scraped HTML/content from reference sites
  notes/           # Design notes, audit findings
```

To sync across machines, copy `.reference/` via SCP, shared folder, or external drive.

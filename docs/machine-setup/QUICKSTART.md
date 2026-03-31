# Machine Setup Guide

> Works for any machine: Nitro (Windows), Mac, Ubuntu, or new contributor.

## 1. Clone and Install

```bash
git clone --recursive https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
make setup
```

`make setup` installs: Python deps, Node deps, OpenAlgo deps, gunicorn, workspace init.

## 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` — set `OPENALGO_API_KEY` (get from OpenAlgo web UI after broker login).

## 3. Configure OpenAlgo Broker

Edit `infra/openalgo/.env` (copy from `.sample.env` if needed):
- Set broker name (e.g., your broker or its sandbox variant for testing)
- Set broker credentials (client ID, API key/secret)

## 4. Start and Verify

```bash
make start       # Starts OpenAlgo on port 5000
make status      # Verify API responding
make test        # 2,903+ tests pass
```

## 5. Run Terminal

```bash
cd packages/terminal
npm run dev      # Terminal on http://localhost:5173
```

## 6. Start Building

Read `PLAN.md` at the repo root. Pick the first unchecked task. Build it.

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

`packages/terminal/.env` is gitignored. Create it for direct API access (bypassing Vite proxy):

```
VITE_OPENALGO_HOST=http://127.0.0.1:5000
VITE_OPENALGO_WS=ws://127.0.0.1:8765
VITE_OPENALGO_API_KEY=your_key_here
```

Or use Vite proxy (already configured in `vite.config.ts` for `/api` routes).

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

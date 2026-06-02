# Machine Setup Guide

> Works on any Windows, macOS, or Ubuntu machine — including a new contributor's box.
> FlintTrade `v0.6.0-alpha` is not production ready; use Explore and Practice
> modes before connecting any live broker workflow.

## 1. Clone and Install

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
make setup
```

`make setup` installs: Python deps, Node deps, workspace init.

OpenAlgo is no longer bundled as a git submodule. It is an optional external integration that FlintTrade can talk to over HTTP/WebSocket. Install OpenAlgo separately, or run the helper to clone a local-dev copy only when you want that integration path. AlgoMirror is intentionally absent — its mirroring logic is absorbed in-process by `packages/services/ditto/`, nothing external to install.

```bash
bash scripts/setup-test-deps.sh
```

This populates `.local/external/openalgo/` (gitignored) with a working OpenAlgo clone you can run via `make start-openalgo`.

## 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` only if you want to preconfigure optional integrations such as OpenAlgo.

## 3. Configure Broker Access

For the native FlintTrade gateway, use the terminal setup flow. For the optional OpenAlgo path, edit OpenAlgo's own `.env` — for the local-dev clone, that's `.local/external/openalgo/.env` (copy from `.sample.env` if needed):
- Set broker name (e.g., your broker or its sandbox variant for testing)
- Set broker credentials (client ID, API key/secret)

## 4. Start and Verify

```bash
make start       # Starts FlintTrade backend on port 5100
make status      # Verifies FlintTrade backend; reports OpenAlgo only as optional
make test        # full pytest suite passes
```

## 5. Run Terminal

```bash
cd packages/apps/terminal
npm run dev      # Terminal on http://localhost:5173
```

## 6. Start Building

Read [`contributing.md`](../../contributing.md) for the contribution flow, then check the [issue tracker](https://github.com/navaneeshnagarajan/FlintTrade/issues) — the `good first issue` label is a good place to land your first PR. If you use a CLAUDE-aware or AGENTS-aware coding agent (Claude Code, Cursor, Aider, Continue, Codex, etc.), run `bash scripts/setup-agent-context.sh` once to scaffold your machine-local agent context.

---

## OpenAlgo Broker Login

1. Open http://127.0.0.1:5000 in browser
2. Create account on first run
3. Select broker (use sandbox variant for testing)
4. Login to broker via OAuth redirect
5. Go to API Key section, generate key
6. Put key in FlintTrade `.env` as `OPENALGO_API_KEY` only when using the
   OpenAlgo-compatible bridge.

Sessions expire at ~3:30 AM IST. Re-login daily when using live broker.

## Terminal .env

`packages/apps/terminal/.env` is gitignored. The Vite proxy in `vite.config.ts` already forwards `/api` to OpenAlgo, `/ft-api` to the FlintTrade backend, and `/ws` to the WebSocket — you should not need a terminal-side `.env` for normal development.

```
# Only the host/WS endpoints are configurable from VITE_* env vars.
# DO NOT put the API key here — Vite inlines VITE_* at build time, leaking
# the key into the production JS bundle. Configure OPENALGO_API_KEY only for
# the OpenAlgo-compatible bridge, either in the in-app Settings → Connection
# flow (it persists to ~/.flinttrade/workspace.json, server-side only) or in
# the repo-root .env which the FlintTrade backend reads.
VITE_OPENALGO_HOST=http://127.0.0.1:5000
VITE_OPENALGO_WS=ws://127.0.0.1:8765
```

## Optional Agent Context

The public repository includes reusable agent-context templates under
`templates/agent-context/`. If you use a coding agent, scaffold local copies
with:

```bash
bash scripts/setup-agent-context.sh
```

The generated files live under `.local/agent-context/` and stay gitignored.

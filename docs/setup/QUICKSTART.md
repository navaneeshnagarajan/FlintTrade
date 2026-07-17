# Machine Setup Guide

> Works on any Windows, macOS, or Ubuntu machine — including a new contributor's box.
> FlintTrade `v0.6.0-beta.4` is not production ready; use Explore and Practice
> modes before connecting any live broker workflow.

## 1. Install the Native App

For normal use, download the macOS, Windows, or Linux installer from the
release page and launch FlintTrade like any other app. The first run creates
your OS workspace and opens the Setup flow. No `.env` file is required.

To build the installer yourself:

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
uv sync && uv pip install pyinstaller && pnpm install
make desktop-build
```

Generated packages live under
`packages/apps/desktop/src-tauri/target/release/bundle/`.

## 2. Contributor Source Setup

Use this only when developing FlintTrade from source:

```bash
make setup
make dev
```

OpenAlgo is no longer bundled as a git submodule. It is an optional external integration that FlintTrade can talk to over HTTP/WebSocket. Install OpenAlgo separately, or run the helper to clone a local-dev copy only when you want that integration path. AlgoMirror is intentionally absent — its mirroring logic is reimplemented natively in `packages/services/ditto/` (our own code), nothing external to install.

```bash
bash scripts/setup-test-deps.sh
```

This populates `.local/external/openalgo/` (gitignored) with a working OpenAlgo clone you can run via `make start-openalgo`.

## 3. Configure Broker Access

For the recommended OpenAlgo bridge, configure the OpenAlgo server in OpenAlgo
itself, then paste the OpenAlgo URL/API key in FlintTrade Setup → OpenAlgo
Bridge or Settings → Broker Gateway. For the native FlintTrade gateway, use the
app setup flow only for the currently connectable native options (Dhan and
Upstox). INDmoney is read-verified and its fail-closed emergency planner is
locally verified, but it stays "coming soon" until restart-time regular/smart-parent
cancellation can be resolved authoritatively, a broker-atomic reduce-only close
primitive exists, and a funded/live-market order-safety proof lands;
other catalogued brokers stay disabled until their live checks pass. For the
local-dev OpenAlgo clone, broker credentials stay in
`.local/external/openalgo/.env` (copy from `.sample.env` if needed):
- Set broker name (e.g., your broker or its sandbox variant for testing)
- Set broker credentials (client ID, API key/secret)

## 4. Start and Verify

Native app users can skip this section. Contributors running from source can
use:

```bash
make start       # Starts FlintTrade backend on port 5100
make status      # Verifies FlintTrade backend; reports OpenAlgo only as optional
make test        # full pytest suite passes
```

## 5. Run Terminal

Native app users can skip this section. Contributors running from source can
use:

```bash
cd packages/apps/terminal
npm run dev      # Terminal on http://localhost:5173
```

### Web UI (no desktop app)

The backend serves the built terminal itself, so a plain browser is a full
client. Build the terminal once (`cd packages/apps/terminal && npm run build`),
then `make start` and open http://127.0.0.1:5100.

To reach it from another machine (for example over Tailscale), bind the backend
to that interface:

```bash
FLINTTRADE_BACKEND_HOST=<tailnet-ip> make start
```

Non-loopback binds fail closed: the backend refuses to start until the operator
account exists (complete setup locally first) or `FLINTTRADE_API_KEY` is set,
and every remote request must carry a session JWT or that API key. Settings
writes such as OpenAlgo and LLM configuration stay loopback-only — change those
at the machine that runs the backend. Live market data streams from OpenAlgo's
WebSocket directly, so point the OpenAlgo host configuration at an address the
remote browser can also reach.

## 6. Start Building

Read [`contributing.md`](../../contributing.md) for the contribution flow, then check the [issue tracker](https://github.com/navaneeshnagarajan/FlintTrade/issues) — the `good first issue` label is a good place to land your first PR. If you use a CLAUDE-aware or AGENTS-aware coding agent (Claude Code, Cursor, Aider, Continue, Codex, etc.), run `bash scripts/setup-agent-context.sh` once to scaffold your machine-local agent context.

---

## OpenAlgo Broker Login

1. Open http://127.0.0.1:5000 in browser
2. Create account on first run
3. Select broker (use sandbox variant for testing)
4. Login to broker via OAuth redirect
5. Go to API Key section, generate key
6. Paste the OpenAlgo URL and API key into FlintTrade Setup → OpenAlgo Bridge
   or Settings → Broker Gateway. If the URL omits a port, set REST Port
   (default `5000`); WebSocket Port defaults to `8765`. FlintTrade stores these
   settings in the OS workspace.

Sessions expire at ~3:30 AM IST. Re-login daily when using live broker.

## Terminal Env

There is no terminal-side `.env` template. Vite proxy overrides are developer
only, and production/native connection settings must come from Setup or
Settings so they remain runtime user choices rather than build-time bundle
constants.

## Optional Agent Context

The public repository includes reusable agent-context templates under
`templates/agent-context/`. If you use a coding agent, scaffold local copies
with:

```bash
bash scripts/setup-agent-context.sh
```

The generated files live under `.local/agent-context/` and stay gitignored.

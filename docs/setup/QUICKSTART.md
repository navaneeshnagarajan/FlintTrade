# Machine Setup Guide

> Works on any Windows, macOS, or Ubuntu machine — including a new contributor's box.
> FlintTrade `v0.0.1` is not production ready; use Explore and Practice
> modes before connecting any live broker workflow.

## 1. Install FlintTrade

FlintTrade is a self-hosted web app. The one-line installer needs nothing
pre-installed — no Python, no Node, no git, no bash and no make:

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash
```

```powershell
# Windows 10/11
irm https://flinttrade.vercel.app/web-install.ps1 | iex
```

It provisions a pinned, checksum-verified toolchain (`uv`, Python 3.12, Node
and pnpm) under `~/.flinttrade/tools`, builds FlintTrade from a managed source
checkout at `~/.flinttrade/src/FlintTrade`, and installs a `flinttrade`
launcher. Open <http://127.0.0.1:5100> and complete Setup — no `.env` file is
required.

Uninstalling keeps your workspace and data. Run **one** of these:

```bash
# macOS / Linux — keep data
curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash

# macOS / Linux — also delete recognised FlintTrade data (irreversible)
curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash -s -- --purge
```

```powershell
# Windows 10/11 — keep data
irm https://flinttrade.vercel.app/uninstall.ps1 | iex

# Windows 10/11 — also delete recognised FlintTrade data (irreversible)
& ([scriptblock]::Create((irm https://flinttrade.vercel.app/uninstall.ps1))) -Purge
```

If the site is unreachable, run `scripts/install/flinttrade-uninstall.sh`
(macOS/Linux) or `scripts/install/flinttrade-uninstall.ps1` (Windows) from a
clone instead.

### Electron desktop shell

The Electron desktop shell wraps that same local backend, but no complete,
checksum-published Electron installer release exists yet. Once this branch is
deployed, the download page will expose no one-command install until all four
Electron installers and `SHA256SUMS.txt` are available together. The currently
deployed beta.13 page predates that gate and still advertises the retired
packaging; do not use it as an Electron source-bootstrap installer.

To build and verify the Electron shell locally (these lines run unchanged in
bash, zsh and Windows PowerShell):

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
pnpm install --frozen-lockfile
python scripts/ft.py desktop-test
python scripts/ft.py desktop-package
```

`make desktop-test` and `make desktop-package` are the POSIX aliases. Generated
packages live under `packages/apps/desktop/release/electron/`. On first launch
the shell verifies pinned tools, builds a managed source checkout, creates your
OS workspace and opens Setup after the guardian is healthy. No `.env` file is
required. See [the desktop guide](../DESKTOP.md) for the release availability,
source-bootstrap and ad-hoc macOS signing boundaries.

## 2. Contributor Source Setup

Use this only when developing FlintTrade from source.
`python scripts/ft.py <target>` is the cross-platform runner — it needs no make
and no bash, and behaves identically on Windows, macOS and Linux.
`make <target>` is the POSIX alias.

```bash
python scripts/ft.py setup
python scripts/ft.py dev
```

OpenAlgo is no longer bundled as a git submodule. It is an optional external integration that FlintTrade can talk to over HTTP/WebSocket. Install OpenAlgo separately, or run the helper to clone a local-dev copy only when you want that integration path. AlgoMirror is intentionally absent — its mirroring logic is reimplemented natively in `packages/services/ditto/` (our own code), nothing external to install.

The helper is a bash script, so it is POSIX-only; on Windows run it inside
WSL2, or clone OpenAlgo yourself.

```bash
bash scripts/setup-test-deps.sh
```

This populates `.local/external/openalgo/` (gitignored) with a working OpenAlgo clone you can run via `make start-openalgo` (also POSIX-only).

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
python scripts/ft.py start    # Starts FlintTrade backend on port 5100
python scripts/ft.py status   # Verifies the backend; OpenAlgo is reported as optional
python scripts/ft.py test     # full pytest suite passes
```

The same three lines run unchanged in Windows PowerShell. On POSIX,
`make start`, `make status` and `make test` are aliases for the same targets.

## 5. Run Terminal

Native app users can skip this section. Contributors running from source can
use:

```bash
pnpm --filter @flinttrade/terminal dev   # Terminal on http://localhost:5173
```

### Web UI (no desktop app)

The backend serves the built terminal itself, so a plain browser is a full
client. Build the terminal once, then start the backend and open
<http://127.0.0.1:5100>:

```bash
pnpm --filter @flinttrade/terminal build
python scripts/ft.py start
```

To reach it from another machine (for example over Tailscale), bind the backend
to that interface. The environment variable is set separately from the command
because Windows PowerShell has no `VAR=value command` prefix form:

```bash
# macOS / Linux
export FLINTTRADE_BACKEND_HOST=<tailnet-ip>
python scripts/ft.py start
```

```powershell
# Windows 10/11
$env:FLINTTRADE_BACKEND_HOST = "<tailnet-ip>"
python scripts/ft.py start
```

Non-loopback binds fail closed: the backend refuses to start until the operator
account exists (complete setup locally first) or `FLINTTRADE_API_KEY` is set,
and every remote request must carry a session JWT or that API key. Settings
writes such as OpenAlgo and LLM configuration stay loopback-only — change those
at the machine that runs the backend. Live market data streams from OpenAlgo's
WebSocket directly, so point the OpenAlgo host configuration at an address the
remote browser can also reach.

## 6. Start Building

Read [`contributing.md`](../../contributing.md) for the contribution flow, then check the [issue tracker](https://github.com/navaneeshnagarajan/FlintTrade/issues) — the `good first issue` label is a good place to land your first PR. If you use a CLAUDE-aware or AGENTS-aware coding agent (Claude Code, Cursor, Aider, Continue, Codex, etc.), run `bash scripts/setup-agent-context.sh` once to scaffold your machine-local agent context. That helper is a bash script: on Windows run it in WSL2 or Git Bash, or copy the templates from `templates/agent-context/` by hand.

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
with the POSIX helper (on Windows, run it in WSL2 or Git Bash, or copy the
templates by hand):

```bash
bash scripts/setup-agent-context.sh
```

The generated files live under `.local/agent-context/` and stay gitignored.

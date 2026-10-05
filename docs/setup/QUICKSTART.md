# Machine Setup Guide

> Works on any Windows, macOS, or Ubuntu machine — including a new contributor's box.
> FlintTrade `v0.0.1` is not production ready; use Practice, and example data,
> before connecting any live broker workflow.

## 1. Install FlintTrade

FlintTrade is a self-hosted web app. The one-line installer needs nothing
pre-installed — no Python, no Node, no git, no bash and no make:

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash
```

```powershell
# Windows 10/11
# Run in a normal (non-Administrator) PowerShell window
irm https://flinttrade.vercel.app/web-install.ps1 | iex
```

It provisions a pinned, checksum-verified toolchain (`uv`, Python 3.12, Node
and pnpm) under `~/.flinttrade/tools`, builds FlintTrade from a managed source
checkout at `~/.flinttrade/web-src/FlintTrade`, and installs a `flinttrade-web`
launcher. Open http://127.0.0.1:5100 and complete Setup — no `.env` file is
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

### If the site is unreachable (repo-direct fallback)

Use this whenever any command above fails: the hosted URLs are only a redirect
to the scripts in this repository, so a site outage answers `503` rather than
the script. Fetch the same files straight from GitHub — swap
`flinttrade-web-install` for `flinttrade-uninstall` to remove FlintTrade:

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-web-install.sh | bash
```

```powershell
# Windows 10/11
# Run in a normal (non-Administrator) PowerShell window
irm https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-web-install.ps1 | iex
```

Or run `scripts/install/flinttrade-web-install.sh` /
`scripts/install/flinttrade-uninstall.sh` (macOS/Linux), or the matching `.ps1`
files (Windows), from a clone instead.

### Electron desktop shell

The Electron desktop shell wraps that same local backend. The public download
surface distinguishes the source-built web-app install above from Electron
shell installers and withholds Electron commands and downloads unless one
release contains all four canonical installers plus `SHA256SUMS.txt`.

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


## 3. Configure Broker Access

Native broker HTTP remains frozen until Task 9D and Task 7C.2. Start with
Practice. Credentials belong in the encrypted gateway vault.

## 4. Start and Verify

Native app users can skip this section. Contributors running from source can
use:

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
http://127.0.0.1:5100:

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

## 6. Start Building

Read [`contributing.md`](../../contributing.md) for the contribution flow, then check the [issue tracker](https://github.com/navaneeshnagarajan/FlintTrade/issues) — the `good first issue` label is a good place to land your first PR. If you use a CLAUDE-aware or AGENTS-aware coding agent (Claude Code, Cursor, Aider, Continue, Codex, etc.), run `bash scripts/setup-agent-context.sh` once to scaffold your machine-local agent context. That helper is a bash script: on Windows run it in WSL2 or Git Bash, or copy the templates from `templates/agent-context/` by hand.

---

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

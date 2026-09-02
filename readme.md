# FlintTrade

FlintTrade is an AGPL-3.0, self-hosted trading software project for local
manual, automated, algorithmic, and AI-assisted workflows. It is a **web app
first**: the FlintTrade backend serves the full terminal UI and API from a
single origin (port 5100), usable from any browser, with optional native
desktop apps as convenience wrappers around the same backend. The repository
is a Python, React, TypeScript, and Rust monorepo with a Flask backend,
FlexLayout terminal, broker-gateway integration layer, sandbox mode, data
services, and developer documentation.

## Beta disclaimer

FlintTrade `v0.0.1` is **not production ready**. It is educational,
self-hosted software for research, sandbox workflows, and contributor
development first. Nothing in this repository is financial, investment, tax,
legal, or regulatory advice. Read [disclaimer.md](disclaimer.md) before
connecting a broker or enabling Live mode.

## Project scope

- **Terminal app** — React 19, TypeScript, FlexLayout, FDC3, Zustand,
  TanStack Query, and shadcn/ui components for a local workspace.
- **Backend services** — Python 3.12 Flask routes for auth, workspace state,
  broker-gateway orchestration, sandbox data, analytics, and automation.
- **Gateway integration** — adapter contracts, capability metadata, encrypted
  credential storage, WebSocket bridges, the community-tested
  OpenAlgo-compatible bridge (the primary execution path until native brokers
  are evidence-enabled), and evidence-gated native adapter paths.
- **Safety model** — Explore, Practice, and Live modes with server-side checks,
  audit records, and a kill-switch boundary for order-capable routes.
- **Data and simulation** — DuckDB/Parquet storage, indicator packages,
  backtest services, and a Rust/PyO3 tick-processing engine.
- **Developer tooling** — the cross-platform `scripts/ft.py` runner (with make
  as its POSIX alias), pytest/Vitest/Playwright suites, packaging scripts, CI
  notes, and package-level documentation.

## Supported brokers

FlintTrade supports the recommended OpenAlgo-compatible bridge plus a beta
native broker gateway. Native adapters are implemented as software integrations
that require local credentials and live-read evidence before they are exposed as
connectable. See [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) for the current
matrix.

## Supported versions

FlintTrade tracks current stable releases rather than deferring upgrades into
periodic migrations. Two numbers per runtime, and the difference matters:

| | Minimum (the floor) | Target (what CI builds and the installer pins) |
|---|---|---|
| Python | `>=3.12` | 3.14 |
| Node | `>=22.22.2` | 24 |
| OS | Ubuntu 24.04 LTS, or any platform providing Python >= 3.12 | Ubuntu 26.04 LTS |

The **floor** is the lowest version that actually works — set by what the
dependency tree genuinely needs, never by ambition. Node's floor comes from
`react-router@8`'s own `engines` field, and the OS floor is derived rather than
chosen: Ubuntu 24.04 ships Python 3.12, whereas 22.04 ships 3.10 and cannot meet
the Python floor with its system interpreter.

The **target** is where development, CI and the pinned bootstrap toolchain live,
so early adopters of newer releases are supported rather than merely tolerated.

If you use the one-line installer below, none of this constrains you: it
provisions its own SHA-256-verified Python, Node and pnpm under
`~/.flinttrade/tools` and never touches your system toolchain. The floors apply
to source installs and contributors.

These values are declared once, in `flint.toml`'s `[requirements]` table.
`tests/test_minimum_requirements_single_source.py` fails if any manifest, or
this table, disagrees with it.

## Quickstart

### Install (recommended — no prerequisites)

FlintTrade runs as a self-hosted web app: one backend process serves the
terminal UI and the API on a single origin, and you use it from any browser.
The one-line installer runs in the shell your OS already ships — bash or zsh
on macOS and Linux, built-in PowerShell on Windows — and needs no other
toolchain: no Python, no Node, no git and no make.

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash
```

```powershell
# Windows 10/11
# Run in a normal (non-Administrator) PowerShell window
irm https://flinttrade.vercel.app/web-install.ps1 | iex
```

It provisions a pinned, checksum-verified toolchain — `uv`, Python 3.12, Node
and pnpm — under `~/.flinttrade/tools`, builds FlintTrade from a managed source
checkout at `~/.flinttrade/web-src/FlintTrade`, and installs a `flinttrade-web`
launcher (`~/.local/bin/flinttrade-web` on macOS and Linux;
`%LOCALAPPDATA%\Programs\FlintTradeWeb\flinttrade-web.cmd` plus a **FlintTrade
Web** Start Menu shortcut on Windows). The Electron desktop shell keeps its own
launcher and source checkout, so the two installs never collide. Open <http://127.0.0.1:5100> and complete the in-app Setup flow —
no `.env` file is required.

Uninstalling keeps your workspace and data:

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash
```

```powershell
# Windows 10/11
irm https://flinttrade.vercel.app/uninstall.ps1 | iex
```

Add the purge flag — `--purge` on POSIX, `-Purge` on Windows — to delete
recognised FlintTrade data too. Purge is irreversible and asks for explicit
confirmation:

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash -s -- --purge
```

```powershell
# Windows 10/11
& ([scriptblock]::Create((irm https://flinttrade.vercel.app/uninstall.ps1))) -Purge
```

#### If the site is unreachable (repo-direct fallback)

Use this whenever a `flinttrade.vercel.app` command fails: those URLs are only a
redirect to the scripts in this repository, and a site outage or a deployment
without an immutable source commit answers `503`, which `curl … | bash` would
otherwise pipe into your shell as an error page. The commands below fetch the
same two scripts straight from GitHub and depend on no deployment:

```bash
# macOS / Linux — install
curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-web-install.sh | bash
```

```powershell
# Windows 10/11 — install
# Run in a normal (non-Administrator) PowerShell window
irm https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-web-install.ps1 | iex
```

Replace `flinttrade-web-install` with `flinttrade-uninstall` to remove
FlintTrade the same way. The uninstaller is the script that takes `--purge` /
`-Purge`; the installer does not (its flags are `--ref`, `--yes`, `--no-launch`
and `--dry-run`). To read the script before running it — the right instinct for
anything piped to a shell — clone the repository and run it from the checkout
instead:

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
bash scripts/install/flinttrade-web-install.sh
```

### Desktop app

The desktop app is a small Electron wrapper around the same backend, not a
separate product surface. On first launch it verifies pinned tools, builds an
inspectable local source checkout under `~/.flinttrade/src/FlintTrade`, starts
the source guardian, and opens the terminal only after its loopback health
check passes.

The public [download surface](https://flinttrade.vercel.app/download)
distinguishes the source-built web app from Electron-shell installers. It
accepts and exposes an Electron release only when it contains all four
canonical installers plus `SHA256SUMS.txt`; retired Tauri and PyInstaller assets
never satisfy that gate:

| OS | Electron installer | Architectures |
|---|---|---|
| macOS | universal `.dmg` | Apple Silicon (arm64) + Intel (x64) |
| Windows | `.exe` (NSIS, per-user) | x64; Windows 11 on ARM uses emulation |
| Linux | `.AppImage` | x64 + arm64 |

For a release that passes that gate, the desktop install is one command:

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/install.sh | bash
```

```powershell
# Windows 10/11
irm https://flinttrade.vercel.app/install.ps1 | iex
```

and the matching uninstall is:

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash
```

```powershell
# Windows 10/11
irm https://flinttrade.vercel.app/uninstall.ps1 | iex
```

The same `--purge` / `-Purge` flag applies. If the site is unreachable, run the
desktop installer and uninstaller repo-direct exactly as described in
[If the site is unreachable](#if-the-site-is-unreachable-repo-direct-fallback)
above, substituting `flinttrade-install` for the install script. To build and verify the shell
locally (these lines run unchanged in bash, zsh and Windows PowerShell):

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
pnpm install --frozen-lockfile
python scripts/ft.py desktop-test
python scripts/ft.py desktop-package
```

On POSIX, `make desktop-test` and `make desktop-package` are aliases for the
same two targets.

Output lands in `packages/apps/desktop/release/electron/`. Local macOS packages
are always ad-hoc sealed; an ad-hoc seal verifies bundle integrity but is not
Developer ID trust. Distribution signing and notarisation are available only
in release CI when its complete Apple secret sets are configured. See
[docs/DESKTOP.md](docs/DESKTOP.md) for the source-bootstrap,
update, install and uninstall contracts.

> OpenAlgo is optional. Configure it from the app only if you want the
> OpenAlgo-compatible integration path; FlintTrade's native gateway and sandbox
> do not require a separate OpenAlgo process.

### Run from source (contributors)

Use this when you are developing FlintTrade itself. Unlike the one-line
installer it expects you to supply the toolchain: git, Python 3.12+, Node 22+,
`uv` and `pnpm`.

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
uv sync
pnpm install
pnpm --filter @flinttrade/terminal build
python scripts/ft.py start
```

The same six lines run unchanged in Windows PowerShell. Do not join them with
`&&` — Windows PowerShell 5.1 has no `&&` operator; use `;` if you want them on
one line.

Two things that are easy to get wrong:

- **Build the terminal.** The backend only serves the UI when
  `packages/apps/terminal/dist/index.html` exists, so skipping
  `pnpm --filter @flinttrade/terminal build` leaves you with an API and no
  interface.
- **`python scripts/ft.py <target>` is the cross-platform runner** — it needs
  no make and no bash, and behaves identically on Windows, macOS and Linux.
  `make <target>` is the POSIX alias for the same targets.

Then open <http://127.0.0.1:5100> and complete the in-app Setup flow — no
`.env` file is required.

Docker is an advanced path, not a zero-prerequisite one: `make docker-up`
needs make (POSIX only) and Docker, so use the one-line installer or the
source checkout above to try FlintTrade for the first time. No `.env` file is
required for the Docker app stack either; in Docker the UI is served by Nginx
at http://localhost:8080 (port 5100 is the API only), and the optional
observability stack starts with `docker compose --profile monitoring up`.

## Contributor development

```bash
python scripts/ft.py setup
python scripts/ft.py dev
```

`python scripts/ft.py <target>` is the canonical cross-platform entry point;
`make <target>` is the POSIX alias:

- `python scripts/ft.py test` runs the Python pytest suites.
- `python scripts/ft.py lint` runs Ruff over Python packages and tests.
- `make full-check` runs a compact test, lint, and terminal typecheck pass
  (POSIX only — it needs bash).
- `pnpm --filter @flinttrade/terminal build` runs the terminal typecheck
  and Vite build.
- `pnpm --filter @flinttrade/terminal test` runs Vitest.

### Advanced server and Docker modes

Docker, Nginx, and systemd assets support long-running self-host/server
deployments of the web app (beyond the simple `python scripts/ft.py start`
quickstart). `make docker-up` starts the app stack — backend, a one-shot
terminal build, and Nginx, which serves the UI at http://localhost:8080
(override with `FLINTTRADE_HTTP_PORT`/`FLINTTRADE_HTTPS_PORT`). A `.env`
file is optional for the app stack; only the observability profile
(`docker compose --profile monitoring up`, or `make docker-up-monitoring`)
requires real GlitchTip secrets in `.env`. In those modes, `.env.example` is
a dev/server fallback template only; in-app Setup and Settings remain the
preferred way to configure OpenAlgo.

Architecture, per-OS install/uninstall, and the CI release matrix are documented
in **[docs/DESKTOP.md](docs/DESKTOP.md)**.

---

## For developers

### Architecture

```mermaid
flowchart LR
    subgraph FT["FlintTrade"]
        UI["Terminal<br/>React 19 + TypeScript<br/>FlexLayout workspace"]
        BE["Python backend<br/>Strategy engine, AI,<br/>backtest, screener"]
        TE["ticks<br/>Rust + PyO3"]
        UI <-->|"/ft-api/v1/"| BE
        BE <--> TE
    end

    BG["Broker gateway<br/>native adapters"]
    OA["OpenAlgo-compatible<br/>optional integration<br/>port 5000"]
    BR["Broker API"]

    BE <-->|"native broker contract"| BG
    BE <-->|"REST + WebSocket"| OA
    BG <-->|"broker auth"| BR
    OA <-->|"broker auth"| BR
```

FlintTrade runs its own backend, native sandbox, and broker gateway contract.
OpenAlgo remains an optional external integration for users who already rely on
its broker gateway.

### Package map

18 package surfaces — 13 Python packages, 3 applications (React terminal,
Electron desktop shell, Next.js site), 1 shared TypeScript design-system package,
and 1 Rust/PyO3 tick engine.

| Package | Language | Purpose |
|---|---|---|
| `packages/apps/site` | Next.js + TS | Public documentation site and read-only docs MCP |
| `packages/apps/terminal` | React + TS | Single-page workspace, home widgets, routes, tools, and FlexLayout terminal |
| `packages/apps/desktop` | Electron 43 + TypeScript | Sandboxed desktop shell; verifies tools, builds managed local source, supervises the source guardian, and loads only its selected loopback origin |
| `packages/core/core` | Python | Flask backend, auth, workspace, OpenAlgo-compatible client, route registration |
| `packages/core/data` | Python | Tick capture, audit log, trade logging, SQLite sandbox state, DuckDB analytics storage |
| `packages/core/design-system` | TypeScript | Shared FlintTrade tokens, brand primitives, layers, and React components |
| `packages/core/historical` | Python | OHLCV downloader, free-data sources, DuckDB/Parquet pipeline, expiry manager |
| `packages/core/indicators` | Python | Pure-NumPy batch indicators (110 exports), streaming classes, Pine conversion |
| `packages/core/ticks` | Rust + PyO3 | High-performance tick processing for tick-level backtests |
| `packages/integrations/gateway` | Python | Native broker gateway, adapter pattern, credential vault, WebSocket bridge |
| `packages/integrations/webhooks` | Python | Generic HMAC-signed custom webhooks, visual flow builder |
| `packages/services/ai` | Python | LLM client, RAG, ML signals, sentiment, MCP bridge, advisor workflows |
| `packages/services/automation` | Python | Cron jobs, Telegram bot, post-market analysis, voice-order intent extraction |
| `packages/services/backtest` | Python | Event-driven simulator, 94 strategy templates, walk-forward optimiser |
| `packages/services/ditto` | Python | Multi-account mirroring, margin calculator, trailing stop-loss |
| `packages/services/engine` | Python | 5-layer safety system, order router, scheduler, strategy registry |
| `packages/services/journal` | Python | Trade journal, execution-quality analytics, realised P&L tracking |
| `packages/services/screener` | Python | Option chain, OI analysis, PCR, max-pain, portfolio Greeks, IV smile |

### Tech stack

| Layer | Tools |
|---|---|
| Frontend | React 19, TypeScript 5 (strict), Tailwind CSS v4, FlexLayout (with FDC3 interop), shadcn/ui, Lightweight Charts v5, Glide Data Grid, Zustand 5, Jotai, TanStack Query 5 |
| Backend | Python 3.12, Flask, httpx (async), pydantic, DuckDB, structlog |
| Data | NumPy (batch indicators; optional Numba on 3 kernels), Rust/PyO3 (tick engine), QuestDB (future) |
| AI | Managed Ollama sidecar, local SQLite/NumPy vector store, LightGBM (signals), MCP bridge |

### Three ways in

- **Try it locally** — run the [self-hosted web app or a desktop convenience install](#quickstart) and explore in sandbox mode.
- **Build with it** — read the [Developer Guide](docs/DEVELOPER_GUIDE.md) for repo layout, adding widgets, and adding broker adapters.
- **Contribute** — see [contributing.md](contributing.md) for branch strategy, commit conventions, and good-first-issues.

---

## Project documentation

| Guide | What's inside |
|---|---|
| [User Guide](docs/USER_GUIDE.md) | Install, first connection, paper trade, workspace tour |
| [Developer Guide](docs/DEVELOPER_GUIDE.md) | Repo layout, dev setup, adding widgets and strategies |
| [Architecture](docs/ARCHITECTURE.md) | Diagrams, data flow, mode system, auth, WSGI |
| [API Reference](docs/API.md) | FlintTrade `/ft-api/v1/` endpoints plus broker/OpenAlgo-compatible bridge routes |
| [Disclaimer](disclaimer.md) | Beta-stage, no-advice, trading-risk, and user-responsibility notice |
| [Changelog](changelog.md) | Release notes by version |
| [Security](security.md) | Disclosure policy, supported versions, threat model |

## Community

- [GitHub Issues](https://github.com/navaneeshnagarajan/FlintTrade/issues) — bug reports, feature requests, and usage questions via the repository templates.
- [contributing.md](contributing.md) — how to propose changes, run tests, and open a PR.

## Independence & attribution

FlintTrade is native-first and **independently built**: its backend, native
gateway contract, safety/gating layer, and most application code are original
work — it is not a fork of another trading application. It interoperates with
[OpenAlgo](https://github.com/marketcalls/openalgo) through an optional bridge
adapter rather than bundling its source. Reference projects were studied for
inspiration; where a specific widget or module was adapted from an open-source
project it is marked in-source with an "Adapted from:" header, and its licence
and attribution are preserved in [notice](notice). Reducing the remaining
adapted surface to fully-original implementations is ongoing. See
[docs/REFERENCES.md](docs/REFERENCES.md) for the full influence notes.

## License

FlintTrade is released under [AGPL-3.0](LICENSE). If you modify and run
FlintTrade as a network service, you must publish your modified source.

## Code of Conduct

This project follows the Contributor Covenant. By participating you agree to abide by [code-of-conduct.md](code-of-conduct.md). Report unacceptable behaviour via GitHub.

## Contributing

Issues and pull requests are welcome. Please read [contributing.md](contributing.md) before opening a PR — it covers branch naming, commit conventions, testing, and the documentation expectations for every change.

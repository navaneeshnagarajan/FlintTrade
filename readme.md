# FlintTrade

FlintTrade is self-hosted trading software for Indian markets. It supports
manual, automated, algorithmic, and AI-assisted workflows from a browser, with
an optional desktop shell around the same backend. The FlintTrade backend
serves the terminal and API from a single origin (port 5100).

Practice mode and example data work without a broker. The public roadmap is
[ROADMAP.md](ROADMAP.md).

## Pre-release

FlintTrade `v0.0.1` is pre-release software and is **not production ready**.
Trading involves the risk of loss. Nothing in this repository is financial,
investment, tax, legal, or regulatory advice. Read [disclaimer.md](disclaimer.md)
before enabling Live mode.

## Project scope

- **Terminal app** — React 19, TypeScript, FlexLayout, FDC3, Zustand,
  TanStack Query, and shadcn/ui components for a local workspace.

- **Backend services** — Python 3.14 Flask routes for auth, workspace state,
  broker-gateway orchestration, sandbox data, analytics, and automation.

- **Safety model** — Practice, Connected (read), and Live, with Example for sample data, server-side checks,
  audit records, and a kill-switch boundary for order-capable routes.

- **Data and simulation** — DuckDB/Parquet storage, indicator packages,
  backtest services, and a Rust/PyO3 tick-processing engine.

- **Developer tooling** — the cross-platform `scripts/ft.py` runner (with make
  as its POSIX alias), pytest/Vitest/Playwright suites, packaging scripts, CI
  notes, and package-level documentation.

## Supported brokers

Broker connections use six native adapters: Dhan, Upstox, Kotak Neo,
INDmoney, Groww, and Delta Exchange. A broker session cannot be started from the terminal today. Practice mode and example data work without a broker. Broker writes return 503 and broker reads return 409. Live order placement stays disabled unless it is explicitly unlocked and every safety layer passes.

## Supported versions

Each runtime has a floor and a target. The floor is the lowest version that
must work. The target is what development and CI exercise. Both are declared
once, in `flint.toml`'s `[requirements]` table.
`tests/test_minimum_requirements_single_source.py` fails if a manifest
disagrees with that table.

| | Floor | Target |
|---|---|---|
| Python | `>=3.14` | 3.14 |
| Node | `>=22.22.2` | 24 |
| Linux | Ubuntu 26.04 LTS | 26.04 |
| macOS | macOS 13+ | universal `.dmg` |
| Windows | Windows 10/11 x64 | `.exe` and PowerShell installers |

Python's floor and target are the same 3.14 series. Node's floor comes from
jsdom 30, and its target stays ahead at 24.

Ubuntu 26.04 LTS is the Linux floor because that release ships Python 3.14.
The Ubuntu floor applies only to Linux source installs. macOS 13+ ships as a
universal `.dmg`. Windows 10/11 x64 ships as an `.exe` and through the
PowerShell installer, with ARM supported through emulation.

The one-line installer provisions its own Python, Node and pnpm under
`~/.flinttrade/tools`. The Python and Node floors apply to source installs
and contributors on every platform.

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

It provisions a pinned, checksum-verified toolchain — `uv`, Python 3.14, Node
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
| macOS 13+ | universal `.dmg` | Apple Silicon (arm64) + Intel (x64) |
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

### Run from source (contributors)

Use this when you are developing FlintTrade itself. Unlike the one-line
installer it expects you to supply the toolchain: git, Python 3.14+, Node
22.22.2+, `uv` and `pnpm`.

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
- `python scripts/ft.py check` runs affected checks while editing;
  `python scripts/ft.py check --full` runs the exhaustive local gate before pushing.
- `python scripts/ft.py lint` runs Ruff over Python packages and tests.
- `make full-check` is the POSIX alias for `python scripts/ft.py check --full`.
- `pnpm --filter @flinttrade/terminal build` runs the terminal typecheck
  and Vite build.
- `pnpm --filter @flinttrade/terminal test` runs Vitest.

### Advanced server and Docker modes

Architecture, per-OS install/uninstall, and the CI release matrix are documented
in **[docs/DESKTOP.md](docs/DESKTOP.md)**.

---

## For developers

Architecture, the package map, and how to extend FlintTrade are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md).

### Tech stack

See the [Technology Stack and Dependencies guide](docs/TECH_STACK.md) for what
each dependency does, exact-version sources, and the terminal's About screen.

| Layer | Tools |
|---|---|
| Frontend | React 19, TypeScript 7 (strict), Tailwind CSS v4, FlexLayout (with FDC3 interop), shadcn/ui, Lightweight Charts v5, Glide Data Grid, Zustand 5, Jotai, TanStack Query 5 |
| Backend | Python 3.14, Flask, httpx (async), pydantic, DuckDB, structlog |
| Data | NumPy (batch indicators; optional Numba on 3 kernels), Rust/PyO3 (tick engine), DuckDB |
| AI | Managed Ollama sidecar, local SQLite/NumPy vector store, LightGBM (signals), MCP bridge |

### Three ways in

- **Try it locally** — run the [self-hosted web app or a desktop convenience install](#quickstart) and open Practice.
- **Build with it** — read the [Developer Guide](docs/DEVELOPER_GUIDE.md) for repo layout, adding widgets, and adding broker adapters.
- **Contribute** — see [contributing.md](contributing.md) for branch strategy, commit conventions, and good-first-issues.

---

## Project documentation

| Guide | What's inside |
|---|---|
| [Roadmap](ROADMAP.md) | What works today, what is in progress, and what comes next |
| [User Guide](docs/USER_GUIDE.md) | Install, first connection, paper trade, workspace tour |
| [Developer Guide](docs/DEVELOPER_GUIDE.md) | Repo layout, dev setup, adding widgets and strategies |
| [Architecture](docs/ARCHITECTURE.md) | Diagrams, data flow, mode system, auth, WSGI |
| [Technology stack](docs/TECH_STACK.md) | Dependency purposes, version sources, and app build information |
| [API Reference](docs/API.md) | First-party HTTP routes, authentication, Practice trading and native HTTP freeze |
| [Disclaimer](disclaimer.md) | Beta-stage, no-advice, trading-risk, and user-responsibility notice |
| [Changelog](changelog.md) | Release notes by version |
| [Security](security.md) | Disclosure policy, supported versions, threat model |

## Community

- [GitHub Issues](https://github.com/navaneeshnagarajan/FlintTrade/issues) — bug reports, feature requests, and usage questions via the repository templates.
- [contributing.md](contributing.md) — how to propose changes, run tests, and open a PR.

## Independence & attribution

FlintTrade owns its backend, native gateway and safety layer. Required attribution
for adapted modules is retained in [notice](notice) and in source headers.

## License

FlintTrade is released under [AGPL-3.0](LICENSE). If you modify and run
FlintTrade as a network service, you must publish your modified source.

## Code of Conduct

This project follows the Contributor Covenant. By participating you agree to abide by [code-of-conduct.md](code-of-conduct.md). Report unacceptable behaviour via GitHub.

## Contributing

Issues and pull requests are welcome. Please read [contributing.md](contributing.md) before opening a PR — it covers branch naming, commit conventions, testing, and the documentation expectations for every change.

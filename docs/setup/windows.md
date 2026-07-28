# FlintTrade on Windows

> FlintTrade `v0.0.1` is not production ready; use Explore and Practice
> modes before connecting any live broker workflow.

Everything below runs in stock **Windows PowerShell 5.1** — no WSL, no Git
Bash, no make. Two Windows notes that apply to every command on this page:

- Windows PowerShell 5.1 has **no `&&` operator**. Put each command on its own
  line, or separate them with `;`.
- `make` is not installed on Windows. Use the cross-platform runner instead:
  `python scripts/ft.py <start|stop|restart|status|dev|setup|test|lint|clean|version|help|desktop-test|desktop-build|desktop-package|desktop-dev>`.
  After an install, the shim makes the same subcommands available as
  `flinttrade <subcommand>`. `make <target>` is the POSIX alias only.

## One-line install (recommended — no prerequisites)

The web-app installer needs nothing pre-installed: no Python, no Node, no git
and no make. Open Windows PowerShell and run:

```powershell
irm https://flinttrade.vercel.app/web-install.ps1 | iex
```

It downloads a pinned, checksum-verified toolchain (`uv`, Python 3.12, Node and
pnpm) into `~\.flinttrade\tools`, builds FlintTrade from a managed source
checkout at `~\.flinttrade\src\FlintTrade`, and installs a launcher at
`%LOCALAPPDATA%\Programs\FlintTrade\flinttrade.cmd` plus a Start Menu shortcut.
The install is per-user — **no admin rights needed**.

Then open http://127.0.0.1:5100 and complete Setup. Broker/OpenAlgo
configuration is handled in the app; no `.env` file is required. Your workspace
lives at `%APPDATA%\flinttrade\` (override with `FLINTTRADE_WORKSPACE_DIR`, or
`FLINTTRADE_HOME`).

## Uninstall

The plain uninstall removes the application and its launcher integration and
keeps your workspace and data:

```powershell
irm https://flinttrade.vercel.app/uninstall.ps1 | iex
```

Add `-Purge` to also delete recognised FlintTrade data (workspace, managed
source and tools). Purge is irreversible and asks for explicit confirmation:

```powershell
& ([scriptblock]::Create((irm https://flinttrade.vercel.app/uninstall.ps1))) -Purge
```

If the site is unreachable, run the same script from a clone or from the
managed source checkout at `~\.flinttrade\src\FlintTrade`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install\flinttrade-uninstall.ps1
```

## Electron installer status

No complete, checksum-published Electron release exists yet. The public
[download page](https://flinttrade.vercel.app/download) will withhold installer
commands until the Windows NSIS installer, the universal macOS DMG, both Linux
AppImages and `SHA256SUMS.txt` are published together once this branch is
deployed. The currently deployed beta.13 page predates that gate and still
advertises the retired packaging; do not use those instructions as an Electron
source-bootstrap install.

After that gate opens, the one-command install is:

```powershell
irm https://flinttrade.vercel.app/install.ps1 | iex
```

The script requires the canonical Windows asset and `SHA256SUMS.txt` from the
same official release and verifies SHA-256 before running the installer. The
install is per-user — **no admin rights needed**.
The script lives at [`scripts/install/`](../../scripts/install/) — read it
before piping to a shell if that is your policy (it should be).

Launch the app and complete Setup. Broker/OpenAlgo configuration is handled
in the app; no `.env` file is required.

## Manual `.exe` download (after release availability)

1. Download the NSIS `FlintTrade-<version>-win-x64.exe` installer from the
   release page.
2. Run it. Authenticode signing is not configured, so a manually downloaded
   installer triggers SmartScreen — choose **More info → Run anyway**. The
   install is per-user; no admin rights needed.
3. Electron includes its Chromium runtime; it does not download the retired
   WebView2-based desktop runtime.
4. On first launch, the shell verifies pinned tools and builds the official
   source checkout with progress on the splash (needs internet).
5. Launch the app and complete Setup. Broker/OpenAlgo configuration is handled
   in the app; no `.env` file is required.

**Windows 11 on ARM:** the x64 build runs via emulation — install the same
`FlintTrade-<version>-win-x64.exe`.

To build the installer locally (one command per line — PowerShell 5.1 has no
`&&`):

```powershell
pnpm install --frozen-lockfile
python scripts/ft.py desktop-test
python scripts/ft.py desktop-package
```

Output lands in `packages/apps/desktop/release/electron/`. Windows and Linux
runtime package behaviour is owned by CI and contributor runs; a Mac build is
not cross-platform proof.

## WSL2 (native performance)
1. Install WSL2: `wsl --install`
2. Open Ubuntu terminal in WSL2
3. Follow Linux setup instructions ([docs/setup/linux.md](linux.md))

## Source development (advanced)

Requires: Python 3.12, Node.js 22+, `uv`, `pnpm`, Git, and optionally Rust.
`make` is **not** required and is not available on Windows — use
`python scripts/ft.py <target>` instead.

To run the built web app from source:

```powershell
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
uv sync
pnpm install
pnpm --filter @flinttrade/terminal build
python scripts/ft.py start
```

Then open http://127.0.0.1:5100. The terminal build step is not optional: the
backend serves the UI only when `packages/apps/terminal/dist/index.html`
exists, so skipping it leaves you with an API and no interface.

To run the Vite dev server alongside the backend instead:

```powershell
python scripts/ft.py setup
python scripts/ft.py dev
```

Then open http://localhost:5173.

Note: systemd is not available on Windows.
Use Task Scheduler or NSSM to run as a Windows service.

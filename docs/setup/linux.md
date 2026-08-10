# FlintTrade on Linux (Ubuntu/Debian)

## One-line install (recommended — no prerequisites)

The web-app installer needs nothing pre-installed: no Python, no Node, no git
and no make.

```bash
curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash
```

It downloads a pinned, checksum-verified toolchain (`uv`, Python 3.12, Node and
pnpm) into `~/.flinttrade/tools`, builds FlintTrade from a managed source
checkout at `~/.flinttrade/web-src/FlintTrade`, and installs a
`flinttrade-web` launcher at `~/.local/bin/flinttrade-web`. No `sudo` is used.
The Electron desktop shell keeps its own checkout at `~/.flinttrade/src/FlintTrade`
and its own `~/.local/bin/flinttrade` launcher, so the two installs never
collide and can be run in either order.

Then open http://127.0.0.1:5100 and complete Setup. Broker/OpenAlgo
configuration is handled in the UI; no `.env` file is required. Your workspace
lives at `~/.flinttrade/` (override with `FLINTTRADE_WORKSPACE_DIR`, or
`FLINTTRADE_HOME`).

### If the site is unreachable (repo-direct fallback)

Use this whenever the command above fails: the hosted URL is only a redirect to
the script in this repository, and a site outage or a deployment without an
immutable source commit answers `503`, which `curl … | bash` would pipe into
your shell as an error page. This form fetches the same script straight from
GitHub and depends on no deployment:

```bash
curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-web-install.sh | bash
```

To read the script before running it, clone the repository and run the file:

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
bash scripts/install/flinttrade-web-install.sh
```

## Uninstall

The plain uninstall removes the application and its launcher integration and
keeps your workspace and data:

```bash
curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash
```

Add `--purge` to also delete recognised FlintTrade data (workspace, managed
source and tools). Purge is irreversible and asks for typed confirmation:

```bash
curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash -s -- --purge
```

If the site is unreachable, fetch the same uninstaller straight from GitHub —
the hosted URL is only a redirect to it:

```bash
curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-uninstall.sh | bash
```

Or run the same script from a clone or from the managed source checkout
(`~/.flinttrade/web-src/FlintTrade` for the web app,
`~/.flinttrade/src/FlintTrade` for the desktop shell):

```bash
bash scripts/install/flinttrade-uninstall.sh
```

## Electron installer status

No complete, checksum-published Electron release exists yet. The public
[download page](https://flinttrade.vercel.app/download) will withhold installer
commands until the x64 and ARM64 Electron AppImages, the macOS and Windows
installers, and `SHA256SUMS.txt` are published together once this branch is
deployed. The currently deployed beta.13 page predates that gate and still
advertises the retired packaging; do not use those instructions as an Electron
source-bootstrap install.

After that gate opens, the one-command install is:

```bash
curl -fsSL https://flinttrade.vercel.app/install.sh | bash
```

The script downloads and verifies the canonical `.AppImage` for your
architecture (x64 or arm64), with an automatic FUSE-less self-extraction
fallback because modern distros no longer ship `libfuse2`. It installs an app icon plus a
`flinttrade` command in `~/.local/bin` (no sudo), and verifies the app
survives launch — the launch log is at
`~/.local/state/flinttrade/desktop-launch.log`. The script lives at
[`scripts/install/`](../../scripts/install/) — read it before piping to a
shell if that is your policy (it should be). If the site is unreachable, run it
repo-direct with
`curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-install.sh | bash`.

Complete Setup in the app. Broker/OpenAlgo configuration is handled in the
UI; no `.env` file is required.

## Manual `.AppImage` download

1. Download `FlintTrade-<version>-linux-x64.AppImage` or
   `FlintTrade-<version>-linux-arm64.AppImage` for your architecture from the
   release page.
2. Run `chmod +x FlintTrade-<version>-linux-<arch>.AppImage`, then
   `./FlintTrade-<version>-linux-<arch>.AppImage`. Running an AppImage directly
   needs `libfuse2`; if your distro does not ship it, either install it or run
   `./FlintTrade-<version>-linux-<arch>.AppImage --appimage-extract-and-run`.
3. Complete Setup in the app. Broker/OpenAlgo configuration is handled in the
   UI; no `.env` file is required.

Electron releases publish AppImage only; `.deb` and `.rpm` are not part of the
new four-installer contract.

To build the installer locally:

```bash
pnpm install --frozen-lockfile
python scripts/ft.py desktop-test
python scripts/ft.py desktop-package
```

`make desktop-test` and `make desktop-package` are the POSIX aliases for the
same two targets. Generated packages live under
`packages/apps/desktop/release/electron/`.

## Source development

Requires Python `>=3.12`, Node.js `>=22.22.2`, `uv`, pnpm 10.34.5, Git, and
optionally Rust for `core/ticks`. Those floors come from `[requirements]` in
`flint.toml`, which is the single source of truth for them.

pnpm is pinned in the root `package.json` `packageManager` field, so install it
directly (`npm install -g pnpm@10.34.5`) — Corepack still works if your Node
bundles it, but Node dropped Corepack in 25.0.0, so it is an optional
accelerator rather than a prerequisite.

To run the built web app from source:

```bash
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

```bash
python scripts/ft.py setup
python scripts/ft.py dev
```

Then open http://localhost:5173. `python scripts/ft.py <target>` works on
every OS; `make <target>` is the POSIX alias for the same targets.

## Server services (advanced)
1. `git clone https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `cd FlintTrade`
3. `bash infra/scripts/setup-production.sh`
4. Edit `.env` only for server-only fallback values that cannot be supplied through the app UI.
5. `sudo systemctl start flinttrade`

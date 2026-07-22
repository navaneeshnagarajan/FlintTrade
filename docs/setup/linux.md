# FlintTrade on Linux (Ubuntu/Debian)

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
shell if that is your policy (it should be).

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
make desktop-test
make desktop-package
```

Generated packages live under `packages/apps/desktop/release/electron/`.

## Source development

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
make setup
make dev
```

Open http://localhost:5173.

## Server services (advanced)
1. `git clone https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `cd FlintTrade`
3. `bash infra/scripts/setup-production.sh`
4. Edit `.env` only for server-only fallback values that cannot be supplied through the app UI.
5. `sudo systemctl start flinttrade`

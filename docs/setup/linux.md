# FlintTrade on Linux (Ubuntu/Debian)

## Option A — One-command install (Recommended)

```bash
curl -fsSL https://flinttrade.vercel.app/install.sh | bash
```

The script downloads and verifies the right `.AppImage` for your architecture
(x64 or arm64), with an automatic FUSE-less self-extraction fallback because
modern distros no longer ship `libfuse2`. It installs an app icon plus a
`flinttrade` command in `~/.local/bin` (no sudo), and verifies the app
survives launch — the launch log is at
`~/.local/state/flinttrade/desktop-launch.log`. The script lives at
[`scripts/install/`](../../scripts/install/) — read it before piping to a
shell if that is your policy (it should be).

The desktop app sets `WEBKIT_DISABLE_DMABUF_RENDERER=1` internally by
default, which fixes the blank-window issue on NVIDIA and virtual-machine
graphics stacks.

Complete Setup in the app. Broker/OpenAlgo configuration is handled in the
UI; no `.env` file is required.

## Option B — Manual `.AppImage` download

1. Download the `.AppImage` for your architecture from the release page.
2. `chmod +x FlintTrade_*.AppImage && ./FlintTrade_*.AppImage`. Running an
   AppImage directly needs `libfuse2`; if your distro does not ship it,
   either install it or run
   `./FlintTrade_*.AppImage --appimage-extract-and-run`.
3. Complete Setup in the app. Broker/OpenAlgo configuration is handled in the
   UI; no `.env` file is required.

> **`.deb`/`.rpm` retired:** new releases publish only the AppImage for
> Linux. Older releases still carry `.deb`/`.rpm` packages — install one via
> the script's `--ref <tag>` flag or from that release's assets.

To build the installer locally:

```bash
uv sync && uv pip install pyinstaller && pnpm install
make desktop-build
```

Generated packages live under
`packages/apps/desktop/src-tauri/target/release/bundle/`.

## Option C — Source Development

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
make setup
make dev
```

Open http://localhost:5173.

## Option D — Server Services (Advanced)
1. `git clone https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `cd FlintTrade`
3. `bash infra/scripts/setup-production.sh`
4. Edit `.env` only for server-only fallback values that cannot be supplied through the app UI.
5. `sudo systemctl start flinttrade`

# FlintTrade on Linux (Ubuntu/Debian)

## Option A — Native Desktop (Recommended)

1. Download the `.deb`, `.rpm`, or `.AppImage` from the release page.
2. Install or launch FlintTrade like any other Linux desktop app.
3. Complete Setup in the app. Broker/OpenAlgo configuration is handled in the
   UI; no `.env` file is required.

To build the installer locally:

```bash
uv sync && uv pip install pyinstaller && pnpm install
make desktop-build
```

Generated packages live under
`packages/apps/desktop/src-tauri/target/release/bundle/`.

## Option B — Source Development

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
make setup
make dev
```

Open http://localhost:5173.

## Option C — Server Services (Advanced)
1. `git clone https://github.com/navaneeshnagarajan/FlintTrade.git`
2. `cd FlintTrade`
3. `bash infra/scripts/setup-production.sh`
4. Edit `.env` only for server-only fallback values that cannot be supplied through the app UI.
5. `sudo systemctl start flinttrade`

# FlintTrade on Windows

> FlintTrade `v0.6.0-beta.3` is not production ready; use Explore and Practice
> modes before connecting any live broker workflow.

## Option A — Native Desktop (Recommended)

1. Download the `.exe` installer from the release page.
2. Install FlintTrade like any other Windows app.
3. Launch the app and complete Setup. Broker/OpenAlgo configuration is handled
   in the app; no `.env` file is required.

To build the installer locally:

```powershell
uv sync
uv pip install pyinstaller
pnpm install
make desktop-build
```

## Option B — WSL2 (Native performance)
1. Install WSL2: `wsl --install`
2. Open Ubuntu terminal in WSL2
3. Follow Linux setup instructions ([docs/setup/linux.md](linux.md))

## Option C — Source Development (Advanced)

Requires: Python 3.12, Node.js 22+, Git, and optionally Rust.

```powershell
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
make setup
make dev
```

Open http://localhost:5173.

Note: systemd not available on Windows.
Use Task Scheduler or NSSM to run as a Windows service.

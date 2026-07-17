# FlintTrade on macOS

> FlintTrade `v0.6.0-beta.9` is not production ready; use Explore and Practice
> modes before connecting any live broker workflow.

## Option A — Native Desktop (Recommended)

1. Download the `.dmg` from the release page.
2. Install FlintTrade like any other macOS app.
3. Release builds are currently **unsigned**, so on first launch Gatekeeper
   will block the app. The bypass depends on your macOS version:
   - **macOS 15 (Sequoia) and later**: Apple removed the right-click → Open
     override for unnotarised apps. Double-click FlintTrade once (it will be
     blocked — choose **Done**, not "Move to Trash"), then open
     **System Settings → Privacy & Security**, scroll to the message about
     FlintTrade, and click **Open Anyway**; confirm with **Open Anyway**
     again in the dialog. Needed once per install.
   - **macOS 13/14**: Right-click (Control-click) FlintTrade in Applications,
     choose **Open**, then **Open** again in the dialog — needed once per
     install.

   Subsequent launches work normally either way.
4. Launch the app and complete Setup. Broker/OpenAlgo configuration is handled
   in the app; no `.env` file is required.

To build the installer locally:

```bash
uv sync && uv pip install pyinstaller && pnpm install
make desktop-build
```

## Option B — Source Development

Requires: Python 3.12, Node.js 22+, Git, and optionally Rust.

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
make setup
make dev
```

Open http://localhost:5173.

## Option C — Docker/Server (Advanced)

Docker is retained for advanced self-hosting and contributor testing, not for
the normal desktop app.

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
docker compose up
```

Note: For background-service supervision on macOS, write a launchd plist that runs `make start` from your repo root. A sample plist may be added to `infra/launchd/` in a future release; until then, the systemd unit at `infra/systemd/openalgo.service` is the closest reference.

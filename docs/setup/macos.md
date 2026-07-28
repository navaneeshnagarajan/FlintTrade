# FlintTrade on macOS

> FlintTrade `v0.0.1` is not production ready; use Explore and Practice
> modes before connecting any live broker workflow.

## Electron installer status

No complete, checksum-published Electron release exists yet. The public
[download page](https://flinttrade.vercel.app/download) will withhold the
install command until the universal Electron DMG, the Windows installer, both
Linux AppImages and `SHA256SUMS.txt` are published together once this branch is
deployed. The currently deployed beta.13 page predates that gate and still
advertises the retired packaging; do not treat its assets or instructions as
Electron/source-bootstrap packages.

After that gate opens, the macOS one-command path is:

```bash
curl -fsSL https://flinttrade.vercel.app/install.sh | bash
```

The script requires the canonical universal DMG and checksum asset from the
same official release before installing it. First launch then verifies pinned
tools and builds the managed FlintTrade source checkout; no `.env` file is
required.

## Manual `.dmg` download (after release availability)

1. Download the universal `.dmg`
   (`FlintTrade-<version>-mac-universal.dmg` — one
   file for both Apple Silicon and Intel) from the release page.
2. Install FlintTrade like any other macOS app.
3. Release CI produces an ad-hoc-sealed DMG until its complete Apple
   distribution-signing and notarisation secret sets are configured. The seal
   proves bundle integrity, but Gatekeeper can block a manually downloaded app.
   The override depends on your macOS
   version:
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

Manual Finder copies do not have the identity receipt written by the
one-command installer. To uninstall one, quit FlintTrade and move
`FlintTrade.app` from Applications to Trash. This retains the workspace,
Electron profile, managed source and tools for a later reinstall. After the app
is gone, this explicit purge flow can remove recognised retained data after
typed confirmation:

```bash
curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash -s -- --purge
```

The receipt-based ordinary uninstall script intentionally refuses to delete an
unreceipted same-name application.

To build and verify the installer locally:

```bash
pnpm install --frozen-lockfile
make desktop-test
make desktop-package
```

Output lands in `packages/apps/desktop/release/electron/`. Local packages use
an ad-hoc seal unconditionally. Apple distribution signing and notarisation are
available only through release CI when its complete secret sets are supplied.

## Source development

Requires Python 3.12, Node.js 22+, Git, and optionally Rust for `core/ticks`.

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
make setup
make dev
```

Open http://localhost:5173.

## Docker/server deployment (advanced)

Docker is retained for advanced self-hosting and contributor testing, not for
the normal desktop app.

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
docker compose up
```

Note: For background-service supervision on macOS, write a launchd plist that runs `make start` from your repo root. A sample plist may be added to `infra/launchd/` in a future release; until then, the systemd unit at `infra/systemd/openalgo.service` is the closest reference.

# FlintTrade on macOS

> FlintTrade `v0.0.1` is not production ready; use Explore and Practice
> modes before connecting any live broker workflow.

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
configuration is handled in the app; no `.env` file is required. Your workspace
lives at `~/Library/Application Support/flinttrade/` (override with
`FLINTTRADE_WORKSPACE_DIR`, or `FLINTTRADE_HOME`).

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
required. If the site is unreachable, run it repo-direct with
`curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install/flinttrade-install.sh | bash`.

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
python scripts/ft.py desktop-test
python scripts/ft.py desktop-package
```

`make desktop-test` and `make desktop-package` are the POSIX aliases for the
same two targets.

Output lands in `packages/apps/desktop/release/electron/`. Local packages use
an ad-hoc seal unconditionally. Apple distribution signing and notarisation are
available only through release CI when its complete secret sets are supplied.

## Source development

Requires Python `>=3.12`, Node.js `>=22.22.0`, `uv`, pnpm 10.34.5, Git, and
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

## Docker/server deployment (advanced)

Docker is retained for advanced self-hosting and contributor testing, not for
the normal desktop app.

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
docker compose up
```

Note: For background-service supervision on macOS, write a launchd plist that runs `python scripts/ft.py start` from your repo root. A sample plist may be added to `infra/launchd/` in a future release; until then, the systemd unit at `infra/systemd/openalgo.service` is the closest reference.

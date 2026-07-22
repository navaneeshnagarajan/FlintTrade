# FlintTrade on Windows

> FlintTrade `v0.6.0-beta.13` is not production ready; use Explore and Practice
> modes before connecting any live broker workflow.

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

To build the installer locally:

```powershell
pnpm install --frozen-lockfile
make desktop-test
make desktop-package
```

Output lands in `packages/apps/desktop/release/electron/`. Windows and Linux
runtime package behaviour is owned by CI and contributor runs; a Mac build is
not cross-platform proof.

## WSL2 (native performance)
1. Install WSL2: `wsl --install`
2. Open Ubuntu terminal in WSL2
3. Follow Linux setup instructions ([docs/setup/linux.md](linux.md))

## Source development (advanced)

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

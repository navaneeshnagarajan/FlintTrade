# FlintTrade on Windows

> FlintTrade `v0.6.0-beta.12` is not production ready; use Explore and Practice
> modes before connecting any live broker workflow.

## Option A — One-command install (Recommended)

```powershell
irm https://flinttrade.vercel.app/install.ps1 | iex
```

This is the recommended path because release builds are currently
**unsigned**: the script verifies the installer's SHA-256 against the release
manifest and then clears the Mark-of-the-Web, so SmartScreen does not wall
the verified installer. The install is per-user — **no admin rights needed**.
The script lives at [`scripts/install/`](../../scripts/install/) — read it
before piping to a shell if that is your policy (it should be).

Launch the app and complete Setup. Broker/OpenAlgo configuration is handled
in the app; no `.env` file is required.

## Option B — Manual `.exe` download

1. Download the NSIS `x64-setup.exe` installer from the release page.
2. Run it. Because the build is unsigned, a manually downloaded installer
   triggers SmartScreen — choose **More info → Run anyway**. The install is
   per-user; no admin rights needed.
3. The installer downloads the WebView2 runtime during install if it is
   missing (needs internet).
4. On first launch, the app downloads the ~110–250 MB engine payload with
   progress on the splash (needs internet; honours OS proxy settings).
5. Launch the app and complete Setup. Broker/OpenAlgo configuration is handled
   in the app; no `.env` file is required.

**Windows 11 on ARM:** the x64 build runs via emulation — install the same
`x64-setup.exe`.

**Windows Defender troubleshooting:** the unsigned engine payload lives under
`%APPDATA%\flinttrade\runtime\backend`, and Defender may quarantine it. If the
app reports the engine "disappeared", restore it from Defender's protection
history or add an exclusion for that folder.

To build the installer locally:

```powershell
uv sync
uv pip install pyinstaller
pnpm install
make desktop-build
```

## Option C — WSL2 (Native performance)
1. Install WSL2: `wsl --install`
2. Open Ubuntu terminal in WSL2
3. Follow Linux setup instructions ([docs/setup/linux.md](linux.md))

## Option D — Source Development (Advanced)

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

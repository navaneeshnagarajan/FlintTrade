# FlintTrade Desktop

FlintTrade is a **self-hosted web app first**: the backend (port 5100, via
`make start` or Docker) serves the full terminal UI and API on one origin,
usable from any browser. The desktop apps documented here are **convenience
wrappers** — a thin Tauri shell around that same backend — for people who
want ease of installation rather than running a server themselves. Install
one, launch it, then start in Explore or Practice mode.

Each release ships **one installer per OS**:

- **macOS** — a single **universal** `.dmg`
  (`FlintTrade_<version>_universal.dmg`) — Apple Silicon and Intel in one app
- **Windows** — a single NSIS `x64-setup.exe` — per-user install, no admin
  rights needed; Windows 11 on ARM runs it via emulation
- **Linux** — the **one-command install script** is the story: it downloads
  and verifies the right `.AppImage` for your architecture (x64 and arm64),
  with an automatic FUSE-less self-extraction fallback because modern distros
  lack `libfuse2`. `.deb`/`.rpm` are no longer published from this release
  onward; older releases still carry them (install via `--ref <tag>`).

The installer is a **small native shell** (a few MB): on first launch it
downloads the hash-verified FlintTrade engine payload (~110–250 MB — the
frozen backend, which embeds the React terminal) with progress on the splash,
then starts it. The first-run download needs an internet connection and
honours OS proxy settings. There is no separate server to run and **no `.env`
to configure**. Day-to-day updates replace only that downloaded payload, so
neither installs nor updates ever ship the full runtime inside the installer.

## Download, install, or build

The public website links to this guide from the homepage and primary
navigation. Start here when you want to run FlintTrade as an end-user desktop
app rather than as a contributor checkout.

### One-command install (recommended on every OS)

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/install.sh | bash
```

```powershell
# Windows 10/11
irm https://flinttrade.vercel.app/install.ps1 | iex
```

The bootstrap installer downloads the **published desktop release asset** for
your OS and CPU architecture, verifies it, installs it, and launches
FlintTrade. It does not require Rust, Node, Python, uv, pnpm, PyInstaller,
Xcode, Visual Studio Build Tools, or Linux Tauri development headers unless
you explicitly choose the source-build fallback.

The one-command path is recommended because the beta builds are **unsigned**,
and the script sidesteps the OS walls that manual downloads hit:

- **macOS** — the script's `curl` download carries no quarantine attribute, so
  Gatekeeper never blocks the app. This is the genuine fix for "the app won't
  open" on macOS 15+, where Apple removed the right-click → Open override for
  unnotarised apps.
- **Windows** — the script verifies the installer's SHA-256 against the
  release manifest and then clears the Mark-of-the-Web, so SmartScreen does
  not wall the verified installer.
- **Linux** — the script picks the right `.AppImage` per architecture,
  verifies it, falls back to FUSE-less self-extraction automatically when
  `libfuse2` is absent, installs an app icon plus a `flinttrade` command in
  `~/.local/bin`, and checks the app survives launch (log at
  `~/.local/state/flinttrade/desktop-launch.log`).

The default channel is `beta` while `v0.6` is a prerelease. Use
`--channel stable` for stable-only installs, `--ref <tag>` for an exact
version (including older releases that still carry `.deb`/`.rpm`),
`--no-launch` to install without opening the app, and
`--build-from-source` only when you intentionally want the contributor build
path. The scripts live at [`scripts/install/`](../scripts/install/) — read them
before piping to a shell if that is your policy (it should be).

### Pre-built installers (manual download — secondary path)

Manual downloads remain possible, but because the beta builds are unsigned
you will hit the OS trust walls the one-command install avoids — the honest
trade-offs are listed under [Installing & uninstalling](#installing--uninstalling).

1. Open [/download](/download) for direct macOS, Windows, and Linux links.
2. Pick the installer for your operating system: the universal `.dmg` for
   macOS (one file for both Apple Silicon and Intel), the NSIS `x64-setup.exe`
   for Windows, or the `.AppImage` for your architecture on Linux.
3. The desktop release manifest (`flinttrade-desktop-manifest.json`) published
   with every release (and with the rolling `updater-beta` / `updater-stable`
   releases, which always point at the newest release of that channel) is the
   canonical machine-readable source; the install scripts read it straight
   from the GitHub release-download URLs.
4. Launch FlintTrade and complete the in-app Setup flow. You do not need a
   `.env` file for desktop use.

### Updating

The desktop app has a built-in updater at **Settings → Updates** (desktop
builds only — the web terminal never shows it). "Check for updates" first asks
Tauri's native updater (fed by the signed `latest.json` on the rolling
`updater-beta` / `updater-stable` release); when an update is available a
single **Update and restart** click downloads, verifies, installs, and
restarts the app. On builds where the native updater is unavailable (for
example a local unsigned build), it falls back to reading
`flinttrade-desktop-manifest.json` from the same GitHub release URLs and
launching the bundled installer script in binary-update mode — no source
checkout required either way.

Independently of the shell update, Settings → Updates also offers **Update
backend** when a newer backend payload is published: the shell downloads the
`flinttrade-payload-<triple>` release asset (the frozen backend, which embeds
the terminal), verifies its SHA-256 against the release manifest, installs it
under `<workspace>/runtime/backend/<version>/`, keeps the previous version for
rollback, and restarts onto it. The thin Tauri shell itself rarely needs an
installer cycle; day-to-day changes ship as payload updates. A payload that
fails to start is rolled back to the retained previous payload if it still
verifies; otherwise the splash shows an actionable error with Retry — never a
crash loop.

If this machine also has a FlintTrade source workspace
(`~/.flinttrade/src/FlintTrade`, or `FLINTTRADE_SRC_DIR`), Settings still shows
**Rebuild from source** as an advanced fallback. That path uses the same
script with `--build-from-source` and keeps the older local-build behaviour.

---

## How it works

The desktop app is a thin [Tauri 2](https://tauri.app) native shell around the
real FlintTrade backend:

```
┌─────────────────────────── FlintTrade.app ───────────────────────────┐
│                                                                       │
│  Tauri shell (Rust)                                                   │
│   1. provisions the credential-vault master password (first run)      │
│   2. first run: downloads + SHA-256-verifies the backend payload      │
│      (progress on the splash; retry on failure — never a crash loop)  │
│   3. spawns the managed backend on a free loopback port (--port 0)    │
│   4. waits for "FLINTTRADE_BACKEND_READY port=<n>" on stdout          │
│   5. opens a native window at http://127.0.0.1:<n>                    │
│                                                                       │
│   ┌──────────── flinttrade-backend (managed payload) ────────────┐  │
│   │  PyInstaller-frozen Python — Flask + Waitress                  │  │
│   │  • serves the built React terminal (embedded)                  │  │
│   │  • serves the full API + gated order path on the same origin   │  │
│   │  • binds 127.0.0.1 only — never the network                    │  │
│   └────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

Because the backend serves *both* the terminal and the API from one loopback
origin, the app's same-origin requests resolve with no in-app URL configuration.

**One app, one port.** In production (desktop and `make start` alike) the
FlintTrade backend serves the terminal UI and the API on a single port — the
same single-origin model Paperclip and OpenAlgo use. You only ever see two
ports in *development* (Vite's dev server proxying to the backend for hot
reload) or when running the optional external OpenAlgo bridge, which is a
separate product with its own port by design.

### Background runtime (the AI-trading shell)

FlintTrade runs an autonomous AI agent and live position monitoring, so closing
the window must **not** stop it. The shell therefore keeps the backend alive in
the background:

- **Close to tray.** Clicking the window's close button hides it to the system
  tray; the sidecar (and the agent) keep running. The app quits only via the
  tray's **Quit FlintTrade** item.
- **System tray.** Left-click the tray icon to toggle the window; right-click for
  the **Show / Quit** menu. On macOS the dock icon re-shows a hidden window.
- **Global hotkey.** `Cmd/Ctrl + Shift + F` summons or hides the window from
  anywhere.
- **Native notifications.** The backend can raise OS notifications for events the
  operator must see with the window hidden — a live order dispatched, or a
  safety-gate block — by printing `FLINTTRADE_NOTIFY\t<title>\t<body>` on stdout
  (only when running under the desktop shell, i.e. `FLINTTRADE_DESKTOP=1`; a
  no-op under `make start`). The shell parses those lines and shows a native
  notification. Producer: [desktop_notify.py](../packages/core/core/src/flinttrade_core/desktop_notify.py); consumer: the Tauri shell's `lib.rs`.

The pieces live under:

| Path | Role |
|---|---|
| [packages/apps/desktop/](../packages/apps/desktop) | Tauri 2 shell (Rust + splash) |
| [packages/core/core/src/flinttrade_core/desktop.py](../packages/core/core/src/flinttrade_core/desktop.py) | Backend sidecar entry point |
| [packages/core/core/src/flinttrade_core/desktop_notify.py](../packages/core/core/src/flinttrade_core/desktop_notify.py) | Backend → shell native-notification producer |
| [packaging/flinttrade-backend.spec](../packaging/flinttrade-backend.spec) | PyInstaller freeze spec |
| [packaging/build-backend.sh](../packaging/build-backend.sh) | Frontend build + freeze + sidecar placement |
| [packaging/make-icons.py](../packaging/make-icons.py) | Brand icon generation |
| [.github/workflows/desktop-release.yml](../.github/workflows/desktop-release.yml) | Cross-platform installer matrix |

---

## Configuration — no `.env`

The desktop app reads **no `.env` file**. All configuration lives in the
workspace, created automatically on first launch:

| OS | Workspace directory |
|---|---|
| macOS | `~/Library/Application Support/flinttrade/` |
| Windows | `%APPDATA%\flinttrade\` |
| Linux | `~/.flinttrade/` |

`workspace.json` (user preferences) and the encrypted credential vault live
there. OpenAlgo (optional) and broker connections are configured **in-app** via
**Settings → Connection**, which persists to `workspace.json`. Sensible defaults
mean a fresh install runs with nothing to edit.

The credential-vault master password is generated on first launch and stored in
the owner-only `master_password` file under the workspace directory (mode `0600`
on Unix). It is never auto-generated by the backend and never placed in an
environment variable.

---

## Installing & uninstalling

### macOS (`.dmg`)
- **Recommended:** `curl -fsSL https://flinttrade.vercel.app/install.sh | bash`
  — the script's download carries no quarantine attribute, so Gatekeeper never
  blocks the app.
- **Manual install:** open the universal `.dmg`
  (`FlintTrade_<version>_universal.dmg` — one file for both Apple Silicon and
  Intel), drag **FlintTrade** to **Applications**. Because the build is
  unsigned, a manually downloaded app is quarantined: on macOS 15 (Sequoia)
  and later, open it once (blocked — choose **Done**), then
  **System Settings → Privacy & Security → Open Anyway**; on macOS 13/14,
  right-click (Control-click) the app and choose **Open**, then **Open**
  again. Needed once per install.
- **Uninstall:** drag **FlintTrade** from **Applications** to the Trash. To also
  remove data: delete `~/Library/Application Support/flinttrade/`.

### Windows (`.exe`)
- **Recommended:** `irm https://flinttrade.vercel.app/install.ps1 | iex` — the
  script verifies the SHA-256 against the release manifest and clears the
  Mark-of-the-Web, so SmartScreen does not block the verified installer.
- **Manual install:** run the NSIS `x64-setup.exe` installer. It installs
  per-user — no admin rights needed. A manually downloaded installer triggers
  SmartScreen (**More info → Run anyway**). The beta release does not publish
  MSI assets because WiX requires numeric product versions and rejects
  prerelease SemVer like `0.6.0-beta.11`.
- The installer fetches the WebView2 runtime during install if it is missing
  (needs internet). Windows 11 on ARM runs the x64 build via emulation.
- Windows Defender may flag the unsigned engine payload under
  `%APPDATA%\flinttrade\runtime\backend`. If the app reports the engine
  "disappeared", restore it from Defender's protection history or add an
  exclusion for that folder.
- **Uninstall:** **Settings → Apps → Installed apps → FlintTrade → Uninstall**,
  or **Control Panel → Programs and Features**. To also remove data: delete
  `%APPDATA%\flinttrade\`.

### Linux
- **Recommended:** `curl -fsSL https://flinttrade.vercel.app/install.sh | bash`
  — it downloads and verifies the right `.AppImage` for your architecture,
  installs it under `~/.local/bin/flinttrade.AppImage` with a desktop entry,
  icon, and `flinttrade` command (no sudo), falls back to FUSE-less
  self-extraction automatically when `libfuse2` is absent, and verifies the
  app survives launch (log: `~/.local/state/flinttrade/desktop-launch.log`).
- **Manual `.AppImage`** (portable, no install):
  `chmod +x FlintTrade_*.AppImage && ./FlintTrade_*.AppImage`. Requires
  `libfuse2`, which modern distros no longer ship — either install it or run
  `./FlintTrade_*.AppImage --appimage-extract-and-run`. Nothing to uninstall —
  just delete the file.
- **`.deb`/`.rpm` are retired** from the current release onward — the
  AppImage (via the script) is the single Linux artefact. Older releases still
  carry `.deb`/`.rpm`; install one with `--ref <tag>` or fetch it from that
  release's assets.
- The desktop app sets `WEBKIT_DISABLE_DMABUF_RENDERER=1` internally by
  default, which fixes the blank-window issue on NVIDIA and virtual-machine
  graphics stacks.
- To also remove data: delete `~/.flinttrade/`.

---

## Building locally

Building produces installers for **the OS you build on** (cross-OS builds happen
in CI — see below). Prerequisites:

- **Rust** (stable) and the [Tauri 2 system dependencies](https://tauri.app/start/prerequisites/)
- **Python 3.12** with [uv](https://docs.astral.sh/uv/)
- **Node 22+** with **pnpm 9**

```bash
# One-time: install deps
uv sync                       # backend
uv pip install pyinstaller    # freeze tool
pnpm install                  # frontend + desktop

# Build everything (frontend → backend sidecar → installers)
make desktop-build

# Or run the app in dev mode (hot window, real backend sidecar)
make desktop-dev
```

Output lands in
`packages/apps/desktop/src-tauri/target/release/bundle/`.

Individual steps:

```bash
make desktop-icons      # regenerate the app icon from the brand mark
make desktop-backend    # freeze the backend sidecar only (current OS/arch)
```

> **First-launch note:** the frozen backend cold-starts in ~30–60 s the first
> time (it initialises the workspace and DuckDB schema). The splash screen
> covers this; subsequent launches are fast.

---

## Cross-platform releases (CI)

`.github/workflows/desktop-release.yml` builds the full matrix and attaches the
installers to a GitHub Release.

- **Trigger:** dispatched automatically by `release-please.yml` with the new
  tag when a release PR merges; can also be run manually
  (**Actions → Desktop Release → Run workflow**) with a tag like
  `v0.6.0-beta.11`. Releases publish non-draft.
- **Matrix:** macOS universal (`macos-14`, `--target universal-apple-darwin`) + macOS x64 payload-only (`macos-15-intel`), Windows x64,
  Linux x64 (`ubuntu-22.04`), Linux arm64 (`ubuntu-22.04-arm`) — AppImage only.
- macOS x64 (`macos-15-intel`) builds only the Intel engine payload — kept
  because PyInstaller cannot cross-freeze and macOS Intel has no compatible
  llvmlite wheel; the `macos-14` job bundles the single universal shell that
  serves both chips.
- Each job freezes the backend, bundles the Tauri app, and uploads the
  per-platform installers as workflow artifacts and, when a release tag is
  supplied, draft release assets.
- A final publish job aggregates the installer artifacts, writes
  `SHA256SUMS.txt`, writes `flinttrade-desktop-manifest.json`, and uploads
  both alongside the installers. The website and installer scripts consume the
  public release manifest; they do not rely on GitHub's `latest` redirect
  because prerelease desktop installers can be newer than the stable tag.

### Code signing

Two independent signing systems are wired in CI; each activates automatically
when its repository secrets exist and stays dormant otherwise:

- **Updater signing (active):** `TAURI_SIGNING_PRIVATE_KEY` (+
  `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`) — Tauri's free minisign key, unrelated
  to Apple code signing. When present, CI emits updater artifacts (`.sig`,
  macOS `.app.tar.gz`) and `latest.json`, which powers the one-click native
  updater on every platform.
- **macOS Gatekeeper signing/notarisation (dormant):** `APPLE_CERTIFICATE`
  (base64 `.p12`) + `APPLE_CERTIFICATE_PASSWORD` + `APPLE_SIGNING_IDENTITY`,
  and `APPLE_ID` + `APPLE_PASSWORD` + `APPLE_TEAM_ID` for notarisation. Until
  those exist, macOS builds ship **unsigned**. The recommended way to avoid
  Gatekeeper entirely is the one-command install
  (`curl -fsSL https://flinttrade.vercel.app/install.sh | bash`) — its
  download carries no quarantine attribute, so the app is never blocked. For
  a manually downloaded `.dmg`: on macOS 15 (Sequoia) and
  later, open the app once (blocked — choose **Done**), then
  **System Settings → Privacy & Security → Open Anyway** (Apple removed the
  right-click override for unnotarised apps); on macOS 13/14, right-click
  (Control-click) the app in Finder and choose **Open**, then **Open** again
  in the Gatekeeper dialog. Needed once per install either way.
- **Windows:** an Authenticode certificate
  (`tauri.conf.json → bundle.windows.certificateThumbprint`) — not configured.

See the [Tauri signing guide](https://tauri.app/distribute/sign/).

---

## Troubleshooting

- **Window stays on the splash / "Backend failed to start":** the sidecar
  crashed. Run the backend directly to see the error:
  `packages/apps/desktop/src-tauri/binaries/flinttrade-backend-<triple> --port 0`.
- **Port in use:** the app always asks the OS for a free port (`--port 0`), so a
  running `make start` backend on 5100 does not conflict.
- **AI / ML features unavailable:** heavy ML stacks (PyTorch, ChromaDB, scikit-
  learn) are intentionally excluded from the desktop bundle and default
  workspace lock to keep installers small and avoid unresolved optional-tooling
  advisories. Those features degrade gracefully; install the reviewed AI
  libraries in your local environment before enabling them.

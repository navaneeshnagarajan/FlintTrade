# FlintTrade Desktop

FlintTrade ships as a **native desktop application** for Linux, Windows, and
macOS. Install it, launch it, then start in Explore or Practice mode.

The app bundles the FlintTrade backend and the React terminal into a single
installable package — there is no separate server to run and **no `.env` to
configure**.

- **macOS** — `.dmg` (drag-to-install) — Apple Silicon (arm64) and Intel (x64)
- **Windows** — `.exe` (NSIS) installer — x64
- **Linux** — `.deb`, `.rpm`, and `.AppImage` — x64 and arm64

## Download or build

The public website links to this guide from the homepage and primary
navigation. Start here when you want to run FlintTrade as an end-user desktop
app rather than as a contributor checkout.

1. Open the [GitHub Releases](https://github.com/navaneeshnagarajan/FlintTrade/releases) page.
2. Pick the latest release that has an installer for your operating system.
3. If the current beta release has no installer asset for your OS yet, build it
   locally with the commands in [Building locally](#building-locally).
4. Launch FlintTrade and complete the in-app Setup flow. You do not need a
   `.env` file for desktop use.

---

## How it works

The desktop app is a thin [Tauri 2](https://tauri.app) native shell around the
real FlintTrade backend:

```
┌─────────────────────────── FlintTrade.app ───────────────────────────┐
│                                                                       │
│  Tauri shell (Rust)                                                   │
│   1. provisions the credential-vault master password (first run)      │
│   2. spawns the backend sidecar on a free loopback port (--port 0)    │
│   3. waits for "FLINTTRADE_BACKEND_READY port=<n>" on stdout          │
│   4. opens a native window at http://127.0.0.1:<n>                    │
│                                                                       │
│   ┌─────────────────── flinttrade-backend (sidecar) ──────────────┐  │
│   │  PyInstaller-frozen Python — Flask + Waitress                  │  │
│   │  • serves the built React terminal (embedded)                  │  │
│   │  • serves the full API + gated order path on the same origin   │  │
│   │  • binds 127.0.0.1 only — never the network                    │  │
│   └────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

Because the backend serves *both* the terminal and the API from one loopback
origin, the app's same-origin requests resolve with no in-app URL configuration.

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
- **Install:** open the `.dmg`, drag **FlintTrade** to **Applications**.
- **Uninstall:** drag **FlintTrade** from **Applications** to the Trash. To also
  remove data: delete `~/Library/Application Support/flinttrade/`.
- The build is unsigned by default; on first launch use **right-click → Open**
  (or **System Settings → Privacy & Security → Open Anyway**).

### Windows (`.exe`)
- **Install:** run the NSIS `.exe` installer. The beta release does not publish
  MSI assets because WiX requires numeric product versions and rejects
  prerelease SemVer like `0.6.0-beta.1`.
- **Uninstall:** **Settings → Apps → Installed apps → FlintTrade → Uninstall**,
  or **Control Panel → Programs and Features**. To also remove data: delete
  `%APPDATA%\flinttrade\`.

### Linux
- **`.deb`** (Debian/Ubuntu): `sudo apt install ./FlintTrade_*.deb` —
  uninstall with `sudo apt remove flinttrade`.
- **`.rpm`** (Fedora/RHEL): `sudo dnf install ./FlintTrade-*.rpm` —
  uninstall with `sudo dnf remove flinttrade`.
- **`.AppImage`** (portable, no install): `chmod +x FlintTrade_*.AppImage && ./FlintTrade_*.AppImage`.
  Nothing to uninstall — just delete the file.
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

- **Trigger:** run the workflow manually
  (**Actions → Desktop Release → Run workflow**), optionally entering a tag like
  `v0.6.0-beta.1` to publish draft release assets.
- **Matrix:** macOS arm64 (`macos-14`), macOS x64 (`macos-15-intel`), Windows x64,
  Linux x64 (`ubuntu-22.04`), Linux arm64 (`ubuntu-22.04-arm`).
- Each job freezes the backend, bundles the Tauri app, and uploads the
  per-platform installers as workflow artifacts and, when a release tag is
  supplied, draft release assets.

### Code signing
The default builds are **unsigned**. For distribution, configure signing via the
standard Tauri mechanisms and CI secrets:

- **macOS:** `APPLE_CERTIFICATE`, `APPLE_SIGNING_IDENTITY`, notarisation creds.
- **Windows:** an Authenticode certificate (`tauri.conf.json → bundle.windows.certificateThumbprint`).

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

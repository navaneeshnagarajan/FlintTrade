# Desktop

> Tauri 2 native thin shell — the cross-OS installer (Linux/Windows/macOS) ships only the shell; on first run it downloads the hash-verified PyInstaller-frozen FlintTrade backend payload (which embeds the built terminal) and serves it from a single loopback origin.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source self-hosted trading software monorepo built with Python, React, TypeScript, and Rust.

**Language:** Rust (Tauri 2) + TypeScript

## Public surface

- `src-tauri/src/lib.rs — shell runtime: managed payload bootstrap (first-run download with progress + retry), backend spawn + ready-port handshake, close-to-tray background runtime, tray menu, global hotkey (Cmd/Ctrl+Shift+F), native notification consumer (FLINTTRADE_NOTIFY stdout protocol)`
- `src-tauri/src/main.rs — Tauri entry point`
- `src-tauri/tauri.conf.json — window, bundle, and plugin configuration`
- `splash/ — boot splash shown while the backend payload downloads (first run) and starts`

(See the source for the full surface.)

## Behaviour that matters

- **Close-to-tray:** closing the window hides it — the backend, autonomous
  agent and position monitoring keep running. Quit fully via the tray menu.
- **First-run bootstrap:** the installer bundles no backend. The splash phase
  downloads the sha256-pinned backend payload from the rolling channel
  release, with a progress bar and an explicit Retry on failure.
- **Single loopback origin:** the shell serves the built terminal and proxies
  to the managed backend on localhost only; nothing listens externally.
- **Native notifications:** the backend emits `FLINTTRADE_NOTIFY` lines
  (order dispatched, safety-gate block) that surface as OS notifications.

See [docs/DESKTOP.md](../../../docs/DESKTOP.md) for the full desktop guide.

## Install

End users should install from the published release assets:

```bash
# macOS / Linux
curl -fsSL https://flinttrade.vercel.app/install.sh | bash
```

```powershell
# Windows 10/11
irm https://flinttrade.vercel.app/install.ps1 | iex
```

The scripts resolve the `flinttrade-desktop-manifest.json` asset straight from
the GitHub release-download URLs (the rolling `updater-beta` / `updater-stable`
releases by default, or an exact tag via `--ref`) and download the matching
`.dmg`, `.exe`, `.AppImage`, `.deb`, or `.rpm`. Source builds are an explicit
advanced path via `--build-from-source` / `-BuildFromSource`.

Contributors working in this package should install via the workspace from the repo root:

```bash
pnpm install
```

Build the installers (thin shell — the backend payload is published separately
and downloaded on first run):

```bash
make desktop-build
```

Run in dev (builds the backend payload first):

```bash
make desktop-dev
```

## Tests

```bash
cd packages/apps/desktop/src-tauri && cargo check && cargo test --lib
```

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in
[docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md). For end-user features it powers, see
[docs/USER_GUIDE.md](../../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`contributing.md`](../../../contributing.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../../LICENSE) for the full text.

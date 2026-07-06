# Desktop

> Tauri 2 native shell — bundles the PyInstaller-frozen FlintTrade backend as a sidecar with the built terminal into one cross-OS installer (Linux/Windows/macOS), served from a single loopback origin.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source self-hosted trading software monorepo built with Python, React, TypeScript, and Rust.

**Language:** Rust (Tauri 2) + TypeScript

## Public surface

- `src-tauri/src/lib.rs — shell runtime: sidecar spawn + ready-port handshake, close-to-tray background runtime, tray menu, global hotkey (Cmd/Ctrl+Shift+F), native notification consumer (FLINTTRADE_NOTIFY stdout protocol)`
- `src-tauri/src/main.rs — Tauri entry point`
- `src-tauri/tauri.conf.json — window, bundle, and plugin configuration`
- `splash/ — boot splash shown while the backend sidecar starts`

(See the source for the full surface.)

## Behaviour that matters

- **Close-to-tray:** closing the window hides it — the backend, autonomous
  agent and position monitoring keep running. Quit fully via the tray menu.
- **Single loopback origin:** the shell serves the built terminal and proxies
  to the sidecar backend on localhost only; nothing listens externally.
- **Native notifications:** the backend emits `FLINTTRADE_NOTIFY` lines
  (order dispatched, safety-gate block) that surface as OS notifications.

See [docs/DESKTOP.md](../../../docs/DESKTOP.md) for the full desktop guide.

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
pnpm install
```

Build the installers (frontend + backend sidecar + Tauri bundle):

```bash
make desktop-build
```

Run in dev (builds the sidecar first):

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

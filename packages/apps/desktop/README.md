# Desktop

> Electron 40 shell migration in progress. The tracked Electron scaffold now
> owns the package's default Node build while the existing Tauri implementation
> remains alongside it under `src-tauri/` until behavioural parity is proved.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source self-hosted trading software monorepo built with Python, React, TypeScript, and Rust.

**Language:** TypeScript (Electron 40) + Rust (Tauri 2 compatibility source)

## Public surface

- `electron/main.ts` — minimal single-instance Electron lifecycle and local splash window.
- `electron/preload.ts` — sandboxed, named `window.flintDesktop` bridge.
- `electron/hardening.ts` — deny-first window, navigation, child-window and permission policy.
- `electron/origins.ts` and `electron/ipc.ts` — exact splash/loopback trust classification and per-handler sender validation.
- `electron/state.ts` and `electron/paths.ts` — typed state/event stores and read-only platform path resolution.
- `src-tauri/` — retained Tauri parity source; it is not deleted during the migration.
- `splash/` — local boot splash staged into the Electron package.

(See the source for the full surface.)

## Migration boundary

- The Electron scaffold includes no trading or broker authority.
- Source checkout bootstrap, backend supervision, close-to-tray and updater
  parity are later migration slices; the retained Tauri source remains the
  behavioural reference until those gates pass.
- The renderer receives named functions only. Node and raw `ipcRenderer` stay
  unavailable, and every main-process handler validates the sender frame.

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

Typecheck, test and bundle the Electron main/preload processes:

```bash
pnpm --filter @flinttrade/desktop build
```

Build an unpacked macOS application directory:

```bash
pnpm --filter @flinttrade/desktop pack:dir
```

## Tests

```bash
pnpm --filter @flinttrade/desktop typecheck
pnpm --filter @flinttrade/desktop test:electron
```

The retained Tauri tests remain available with
`cd packages/apps/desktop/src-tauri && cargo test --lib` during parity work.

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in
[docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md). For end-user features it powers, see
[docs/USER_GUIDE.md](../../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`contributing.md`](../../../contributing.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../../LICENSE) for the full text.

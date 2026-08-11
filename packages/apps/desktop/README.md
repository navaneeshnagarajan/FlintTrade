# Desktop

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** —
the Electron 43 shell for the self-hosted terminal.

**Language:** TypeScript (strict) · **Runtime:** Electron 43.2.0

The package contains only the shell, local splash, bootstrap resources and
licence notices. It does not bundle the Python backend or built terminal. On
first launch the shell verifies pinned tools, builds the official source under
`~/.flinttrade/src/FlintTrade`, and starts the source guardian from that
checkout.

> **Installer acceptance:** the source-built web app is distinct from the
> Electron shell. The public download surface accepts and exposes an Electron
> release only when it contains all four canonical installers plus
> `SHA256SUMS.txt`; retired Tauri and PyInstaller assets never satisfy that gate.

## Main surfaces

- `electron/main.ts` wires the singleton, bootstrap, source updates, guardian
  supervision, windows, tray, hotkey, notifications and shell updates.
- `electron/preload.ts` exposes the named `window.flintDesktop` bridge.
- `electron/hardening.ts`, `electron/origins.ts` and `electron/ipc.ts` enforce
  the deny-first renderer boundary and validate every IPC sender.
- `electron/bootstrap*.ts`, `electron/source-*.ts` and
  `electron/candidate-health.ts` acquire, build, health-prove, promote and roll
  back managed source without mutating the running checkout.
- `electron/backend-*.ts`, `electron/lifecycle.ts` and
  `electron/startup-recovery.ts` own the source guardian lifecycle and crash
  recovery.
- `electron/shell-updater.ts` and `electron/shell-update-io.ts` select and
  verify a complete release before handing off to an installer.
- `splash/` is the local bootstrap and recovery surface.
- `resources/bootstrap/` contains the platform bootstrap entrypoints and
  checksum-bound tool manifest.
- `resources/icons/` contains the packaged application and tray icons.

The full backend guardian remains at `packaging/desktop_backend.py` because it
is executed from the managed source checkout. Trading, broker and safety-gate
authority stays in the loopback Python backend; Electron owns machine lifecycle
only.

## Security and lifecycle contract

- Windows use `contextIsolation: true`, `sandbox: true` and
  `nodeIntegration: false`.
- The preload exposes named methods only; it does not expose Node or raw
  `ipcRenderer`.
- The splash is trusted only at its exact packaged file URL. The terminal is
  trusted only at the selected `127.0.0.1` backend origin.
- Navigation, downloads, webviews, permissions and unexpected child windows
  are denied.
- The main window opens only after the exact ready sentinel and
  `GET /api/v1/ping` both succeed.
- Window close hides to the tray. Explicit quit drains the backend before
  releasing its process containment.
- Source/runtime updates and Electron-shell installer updates are separate
  operations and separate renderer actions.

## Development

Install from the repository root with the locked workspace:

```bash
pnpm install --frozen-lockfile
```

Then use either the root Makefile or package scripts:

```bash
make desktop-test
make desktop-build
make desktop-package
make desktop-dev

pnpm --filter @flinttrade/desktop typecheck
pnpm --filter @flinttrade/desktop test:electron
pnpm --filter @flinttrade/desktop bundle
```

Platform package commands are `pack:mac`, `pack:win`, `pack:linux:x64` and
`pack:linux:arm64`. They write to `release/electron/`; only the command matching
the host platform is expected to work locally. `verify:package` checks the
packaged Electron security and resource contract.

Local macOS packaging always uses an ad-hoc code seal. Apple distribution
signing and notarisation are supported only by release CI when its complete
secret sets are supplied. Windows and Linux package behaviour is verified by
deterministic tests and the cross-platform CI matrix; a local Mac package is
not proof for those platforms.

See [docs/DESKTOP.md](../../../docs/DESKTOP.md) for end-user delivery and the
complete first-run/update/uninstall model, and
[docs/DEVELOPER_GUIDE.md](../../../docs/DEVELOPER_GUIDE.md) for repository-wide
contributor guidance.

## Licence

AGPL-3.0, with retained third-party notices and the Hermes-derived MIT
attribution under `resources/licenses/`.

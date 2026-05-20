# FlintTrade — desktop

> Native desktop shell wrapping the React terminal. Built with Tauri v2

## Key Files
- `src-tauri/` — Rust + Tauri configuration (window setup, entitlements, bundler config)
- `src-tauri/Cargo.toml` — Rust crate manifest for the native shell
- `src-tauri/tauri.conf.json` — Tauri config (window size, security, bundle identifiers)
- `package.json` — Tauri CLI scripts (`npm run dev`, `npm run build`)

## Architecture
- The desktop app does NOT contain its own UI source. It loads the built `packages/terminal/dist/` assets at runtime.
- In `dev`, the Tauri window points at the Vite dev server on `http://localhost:5173`.
- In `build`, Tauri packages the static `terminal/dist/` output into a native bundle (`.dmg` / `.msi` / `.AppImage`).
- No business logic lives here — this is purely a packaging shell.

## Depends on: terminal (must be built first)

## Local development
```bash
# 1. Start the terminal dev server in one shell
cd ../terminal && npm run dev

# 2. Start Tauri (loads the dev URL into a native window)
cd ../desktop && npm run dev
```

## Building a release
```bash
cd ../terminal && npm run build
cd ../desktop && npm run build  # produces native installer in src-tauri/target/release/bundle/
```

## Platform-specific prerequisites
- **Windows:** WebView2 (bundled with Windows 11; install separately on Windows 10)
- **macOS:** Xcode Command Line Tools
- **Linux:** `libwebkit2gtk-4.1-dev`, `libappindicator3-dev`, `librsvg2-dev`, `patchelf`

## Rules
- Read root CLAUDE.md for project-wide rules.
- DO NOT add UI code here — all UI changes go in `packages/terminal/`. This package is a thin shell.
- Tauri config (`tauri.conf.json`) governs window chrome, deep-link handlers, and bundle identifiers. Treat changes here as platform-config changes, not feature work.
- Update root CHANGELOG.md on any release-affecting change (new bundle target, deep-link scheme, entitlement, etc.).
- Branch: main (pre-release, all commits to main).

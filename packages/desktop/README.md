# @flinttrade/desktop

Native desktop wrapper for FlintTrade using Tauri v2. Wraps the existing React terminal app in a native window.

## Prerequisites

- [Rust](https://rustup.rs/) (stable toolchain)
- [Node.js](https://nodejs.org/) 20+
- The terminal package built first: `cd ../terminal && npm run build`
- Platform-specific dependencies:
  - **Windows:** WebView2 (included in Windows 11, install manually on Windows 10)
  - **macOS:** Xcode Command Line Tools
  - **Linux:** `libwebkit2gtk-4.1-dev`, `libappindicator3-dev`, `librsvg2-dev`, `patchelf`

## Development

```bash
# Ensure the terminal dev server is running first
cd ../terminal && npm run dev

# In another terminal, start Tauri dev mode (hot-reloads the native window)
npm run dev
```

This opens a native window pointing at `http://localhost:5173` (the Vite dev server).

## Building

```bash
# Build the terminal frontend first
cd ../terminal && npm run build

# Build the native binary
npm run build
```

The compiled binary and installer will be in `src-tauri/target/release/bundle/`.

## Architecture

- `src-tauri/tauri.conf.json` -- Tauri configuration (window size, dev URL, bundle settings)
- `src-tauri/Cargo.toml` -- Rust dependencies
- `src-tauri/src/main.rs` -- Rust entry point (minimal, just launches the webview)
- The frontend is the terminal package (`packages/terminal/dist`) -- no code is duplicated.

#!/usr/bin/env bash
# Build the FlintTrade backend sidecar for the native desktop app.
#
# Steps:
#   1. Build the React terminal (so the freeze can embed it).
#   2. Freeze the backend with PyInstaller (packaging/flinttrade-backend.spec).
#   3. Copy the binary into the Tauri sidecar dir, named with the Rust target
#      triple so `tauri build` picks it up (externalBin convention).
#
# Cross-platform: runs on macOS, Linux, and Windows (Git Bash / MSYS in CI).
# Honours these env overrides:
#   PYTHON          python interpreter (default: auto-detect; prefers .venv)
#   SKIP_FRONTEND   set to 1 to reuse an existing terminal/dist
#   TARGET_TRIPLE   override the detected Rust target triple
#
# Usage: packaging/build-backend.sh
set -euo pipefail

# ---------------------------------------------------------------------------
# Locate the repo root (this script lives in <root>/packaging/).
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

SIDECAR_DIR="packages/apps/desktop/src-tauri/binaries"
DIST_DIR="packages/apps/terminal/dist"

# ---------------------------------------------------------------------------
# Resolve the Python interpreter. Prefer an explicit $PYTHON, then the repo
# virtualenv, then a system python3/python.
# ---------------------------------------------------------------------------
if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
elif [[ -x ".venv/Scripts/python.exe" ]]; then
  PY=".venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi
echo "==> Python: $("$PY" --version 2>&1)  ($PY)"

# ---------------------------------------------------------------------------
# Determine the Rust target triple — the suffix Tauri expects on a sidecar.
# ---------------------------------------------------------------------------
if [[ -n "${TARGET_TRIPLE:-}" ]]; then
  TRIPLE="$TARGET_TRIPLE"
elif command -v rustc >/dev/null 2>&1; then
  TRIPLE="$(rustc -Vv | sed -n 's/^host: //p')"
else
  echo "ERROR: rustc not found and TARGET_TRIPLE unset — cannot name the sidecar." >&2
  exit 1
fi
echo "==> Target triple: $TRIPLE"

# Windows binaries carry a .exe suffix (before the triple, Tauri appends it).
EXE_SUFFIX=""
case "$TRIPLE" in
  *windows*) EXE_SUFFIX=".exe" ;;
esac

# ---------------------------------------------------------------------------
# 1. Build the frontend (unless reusing an existing dist).
# ---------------------------------------------------------------------------
if [[ "${SKIP_FRONTEND:-0}" == "1" && -f "$DIST_DIR/index.html" ]]; then
  echo "==> SKIP_FRONTEND=1 — reusing existing $DIST_DIR"
else
  # Force base "/" so the desktop bundle is never contaminated by a leftover
  # site-demo build (which uses base "/demo-app/"). The backend serves the SPA
  # from the loopback root, so assets MUST be referenced root-relative.
  echo "==> Building terminal frontend (base=/)…"
  ( cd packages/apps/terminal && npm run build -- --base=/ )
fi
[[ -f "$DIST_DIR/index.html" ]] || { echo "ERROR: $DIST_DIR/index.html missing after build." >&2; exit 1; }

# Guard: a /demo-app/ (or other non-root) base would make every asset 404 in the
# desktop app. Fail loudly rather than ship a blank window.
if grep -q '"/demo-app/' "$DIST_DIR/index.html" || grep -qE '(src|href)="/[^"/]+/assets/' "$DIST_DIR/index.html"; then
  echo "ERROR: $DIST_DIR/index.html has a non-root asset base — rebuild with --base=/ (SKIP_FRONTEND must be unset)." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Freeze the backend.
# ---------------------------------------------------------------------------
echo "==> Freezing backend with PyInstaller…"
rm -rf build "dist/flinttrade-backend" "dist/flinttrade-backend$EXE_SUFFIX"
"$PY" -m PyInstaller packaging/flinttrade-backend.spec --noconfirm --clean

FROZEN="dist/flinttrade-backend$EXE_SUFFIX"
[[ -f "$FROZEN" ]] || { echo "ERROR: expected frozen binary at $FROZEN" >&2; ls -la dist || true; exit 1; }

# ---------------------------------------------------------------------------
# 3. Place the sidecar where Tauri expects it.
# ---------------------------------------------------------------------------
mkdir -p "$SIDECAR_DIR"
TARGET="$SIDECAR_DIR/flinttrade-backend-$TRIPLE$EXE_SUFFIX"
cp "$FROZEN" "$TARGET"
chmod +x "$TARGET" 2>/dev/null || true

echo ""
echo "==> Sidecar ready: $TARGET"
echo "    size: $(du -h "$TARGET" | cut -f1)"

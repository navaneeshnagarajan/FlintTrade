#!/usr/bin/env bash
# =============================================================================
# FlintTrade — bootstrap installer / updater (macOS + Linux)
# =============================================================================
#
# Fetches the latest FlintTrade release tag from GitHub, builds the native
# desktop app ON THIS MACHINE (backend sidecar + Tauri bundle), and installs
# it. Because the binary is built locally, there is no unsigned-installer
# warning and nothing to trust beyond the source you can read.
#
#   curl -fsSL https://flinttrade.vercel.app/install.sh | bash
#
# Re-running the same command (or passing --update) updates an existing
# install: it fetches the newest tag into the same source workspace and
# rebuilds. The in-app updater invokes this script the same way.
#
# Flags / environment:
#   --ref <tag|branch>   build a specific ref instead of the newest v* tag
#   --update             explicit update mode (same as re-running)
#   --src <dir>          source workspace (default: ~/.flinttrade/src/FlintTrade)
#   --no-launch          do not open the app after installing
#   --yes                consent to auto-installing missing tools (uv, pnpm)
#   FLINTTRADE_YES=1     same as --yes
#   FLINTTRADE_SRC_DIR   same as --src
#
# What it will NEVER do: run sudo silently, install system packages without
# telling you the exact command, or send anything anywhere. First build takes
# roughly 10–20 minutes and needs ~4 GB (Rust + Node + Python toolchains).
# =============================================================================

set -euo pipefail

REPO_URL="https://github.com/navaneeshnagarajan/FlintTrade.git"
SRC_DIR="${FLINTTRADE_SRC_DIR:-$HOME/.flinttrade/src/FlintTrade}"
REF=""
NO_LAUNCH=0
ASSUME_YES="${FLINTTRADE_YES:-0}"

# --- logging -----------------------------------------------------------------
say()  { printf '\033[1;36m[flinttrade]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[flinttrade]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[flinttrade]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

on_err() {
  warn "The build did not finish. The source workspace is kept at:"
  warn "  $SRC_DIR"
  warn "Fix the reported problem and re-run the same command — it resumes there."
}
trap on_err ERR

# --- args --------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --ref)       REF="${2:?--ref needs a value}"; shift 2 ;;
    --update)    shift ;;                        # same flow; kept for clarity
    --src)       SRC_DIR="${2:?--src needs a value}"; shift 2 ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    --yes)       ASSUME_YES=1; shift ;;
    -h|--help)   grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           die "Unknown flag: $1 (see --help)" ;;
  esac
done

OS="$(uname -s)"
case "$OS" in
  Darwin|Linux) ;;
  *) die "Unsupported OS '$OS'. On Windows, use install.ps1 instead." ;;
esac

# --- consent helper (works when piped: prompts via /dev/tty) ------------------
consent() {
  local question="$1"
  if [ "$ASSUME_YES" = "1" ]; then return 0; fi
  if [ -r /dev/tty ] && [ -w /dev/tty ]; then
    local answer
    printf '\033[1;36m[flinttrade]\033[0m %s [y/N] ' "$question" > /dev/tty
    read -r answer < /dev/tty
    [ "$answer" = "y" ] || [ "$answer" = "Y" ]
  else
    return 1
  fi
}

# --- prerequisites -------------------------------------------------------------
say "Checking build prerequisites…"
MISSING_HINTS=()

need() { command -v "$1" >/dev/null 2>&1; }

need git  || MISSING_HINTS+=("git — install from https://git-scm.com or your package manager")
need curl || MISSING_HINTS+=("curl — install via your package manager")
need make || MISSING_HINTS+=("make — macOS: xcode-select --install; Debian/Ubuntu: sudo apt install build-essential")

if [ "$OS" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
  MISSING_HINTS+=("Xcode Command Line Tools — run: xcode-select --install")
fi

if ! need cargo; then
  MISSING_HINTS+=("Rust (stable) — run: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh   then restart your shell")
fi

if need node; then
  NODE_MAJOR="$(node -e 'process.stdout.write(String(process.versions.node.split(".")[0]))')"
  if [ "$NODE_MAJOR" -lt 22 ]; then
    MISSING_HINTS+=("Node.js >= 22 (found $(node --version)) — https://nodejs.org or your version manager")
  fi
else
  MISSING_HINTS+=("Node.js >= 22 — https://nodejs.org or your version manager")
fi

if [ "$OS" = "Linux" ]; then
  if need pkg-config && ! pkg-config --exists webkit2gtk-4.1 2>/dev/null; then
    MISSING_HINTS+=("Tauri system libraries — Debian/Ubuntu: sudo apt install libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf; Fedora: sudo dnf install webkit2gtk4.1-devel libappindicator-gtk3-devel librsvg2-devel")
  fi
fi

# uv and pnpm can be auto-installed with consent (user-local, no sudo).
if ! need uv; then
  if consent "uv (Python package manager) is missing. Install it now (user-local, from astral.sh)?"; then
    say "Installing uv…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    need uv || die "uv installed but not on PATH — restart your shell and re-run."
  else
    MISSING_HINTS+=("uv — run: curl -LsSf https://astral.sh/uv/install.sh | sh   (or pass --yes to let this script do it)")
  fi
fi

if ! need pnpm; then
  if need corepack && consent "pnpm is missing. Enable it via Node's corepack (user-local)?"; then
    say "Enabling pnpm via corepack…"
    corepack enable pnpm 2>/dev/null || corepack enable
    need pnpm || MISSING_HINTS+=("pnpm — corepack enable did not expose it; see https://pnpm.io/installation")
  else
    MISSING_HINTS+=("pnpm — run: corepack enable pnpm   (ships with Node 22; or pass --yes to let this script do it)")
  fi
fi

if [ ${#MISSING_HINTS[@]} -gt 0 ]; then
  warn "Missing prerequisites:"
  for hint in "${MISSING_HINTS[@]}"; do warn "  • $hint"; done
  die "Install the tools above, then re-run this command."
fi
say "All prerequisites present."

# --- resolve the version to build ---------------------------------------------
if [ -z "$REF" ]; then
  say "Resolving the newest release tag from GitHub…"
  REF="$(git ls-remote --tags --refs "$REPO_URL" 'v*' \
          | awk -F/ '{print $NF}' | sort -V | tail -1)"
  [ -n "$REF" ] || die "Could not resolve a release tag from $REPO_URL"
fi
say "Target version: $REF"

# --- clone or update the source workspace -------------------------------------
if [ -d "$SRC_DIR/.git" ]; then
  say "Updating existing source workspace at $SRC_DIR…"
  git -C "$SRC_DIR" fetch --tags origin
  CURRENT="$(git -C "$SRC_DIR" describe --tags --exact-match 2>/dev/null || echo '')"
  if [ "$CURRENT" = "$REF" ]; then
    if [ "${FLINTTRADE_SKIP_IF_CURRENT:-0}" = "1" ]; then
      say "Already on $REF — nothing to update."
      exit 0
    fi
    say "Source already at $REF — rebuilding (a rebuild is idempotent)."
  fi
  git -C "$SRC_DIR" checkout --quiet "$REF"
else
  say "Cloning FlintTrade ($REF) into $SRC_DIR…"
  mkdir -p "$(dirname "$SRC_DIR")"
  git clone --branch "$REF" --depth 1 "$REPO_URL" "$SRC_DIR"
fi
cd "$SRC_DIR"

# --- build ---------------------------------------------------------------------
say "Installing Python dependencies (uv sync)…"
uv sync
say "Ensuring PyInstaller is available…"
uv pip install pyinstaller
say "Installing JS workspace dependencies (pnpm)…"
pnpm install --frozen-lockfile
say "Building the desktop app (backend sidecar + Tauri bundle) — this is the long step…"
make desktop-build

BUNDLE_DIR="packages/apps/desktop/src-tauri/target/release/bundle"
[ -d "$BUNDLE_DIR" ] || die "Build finished but no bundle directory at $BUNDLE_DIR"

# --- install -------------------------------------------------------------------
if [ "$OS" = "Darwin" ]; then
  APP_PATH="$(find "$BUNDLE_DIR/macos" -maxdepth 1 -name '*.app' | head -1)"
  [ -n "$APP_PATH" ] || die "No .app produced under $BUNDLE_DIR/macos"
  DEST="/Applications"
  [ -w "$DEST" ] || DEST="$HOME/Applications"
  mkdir -p "$DEST"
  APP_NAME="$(basename "$APP_PATH")"
  say "Installing $APP_NAME into $DEST…"
  rm -rf "${DEST:?}/$APP_NAME"
  ditto "$APP_PATH" "$DEST/$APP_NAME"
  say "Installed: $DEST/$APP_NAME ($REF)"
  if [ "$NO_LAUNCH" = "0" ]; then open "$DEST/$APP_NAME"; fi
else
  APPIMAGE="$(find "$BUNDLE_DIR/appimage" -maxdepth 1 -name '*.AppImage' 2>/dev/null | head -1 || true)"
  if [ -n "$APPIMAGE" ]; then
    DEST_BIN="$HOME/.local/bin"
    mkdir -p "$DEST_BIN"
    install -m 0755 "$APPIMAGE" "$DEST_BIN/flinttrade.AppImage"
    say "Installed: $DEST_BIN/flinttrade.AppImage ($REF)"
    DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/flinttrade.desktop" <<DESKTOP
[Desktop Entry]
Name=FlintTrade
Exec=$DEST_BIN/flinttrade.AppImage
Type=Application
Categories=Office;Finance;
Comment=Open-source self-hosted trading software
DESKTOP
    if [ "$NO_LAUNCH" = "0" ]; then
      say "Launching FlintTrade…"
      nohup "$DEST_BIN/flinttrade.AppImage" >/dev/null 2>&1 &
    fi
  else
    DEB="$(find "$BUNDLE_DIR/deb" -maxdepth 1 -name '*.deb' 2>/dev/null | head -1 || true)"
    RPM="$(find "$BUNDLE_DIR/rpm" -maxdepth 1 -name '*.rpm' 2>/dev/null | head -1 || true)"
    say "No AppImage produced. Install the package for your distro yourself:"
    [ -n "$DEB" ] && say "  sudo apt install '$SRC_DIR/$DEB'"
    [ -n "$RPM" ] && say "  sudo dnf install '$SRC_DIR/$RPM'"
    [ -n "$DEB$RPM" ] || die "No installable bundle found under $BUNDLE_DIR"
  fi
fi

say "Done. To update later, re-run the same install command — it fetches the"
say "newest tag into $SRC_DIR and rebuilds."

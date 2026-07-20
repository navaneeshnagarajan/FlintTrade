#!/usr/bin/env bash
# FlintTrade desktop uninstaller (macOS + Linux)
#
# Default mode removes the application and every application-side residue the
# installer or the Tauri runtime creates (app bundle / AppImage, launcher
# wrapper, desktop entry, icon, WebView caches and profiles, launch logs, and
# the build-from-source clone). Your trading data — the FlintTrade workspace
# with the encrypted credential vault, auth database, journals, and
# workspace.json — is kept unless you explicitly pass --purge.
#
#   curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash
#   curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash -s -- --purge
#
# Flags:
#   --purge     Also delete the FlintTrade workspace (credential vault,
#               auth.db, journals, workspace.json). Irreversible.
#   --yes       Skip the --purge confirmation prompt (for scripted use).
#   --dry-run   Print what would be removed without deleting anything.

set -euo pipefail

BUNDLE_ID="com.flinttrade.app"
PURGE="${FLINTTRADE_PURGE:-0}"
ASSUME_YES="${FLINTTRADE_YES:-0}"
DRY_RUN="${FLINTTRADE_DRY_RUN:-0}"
REMOVED_ANY=0
FAILED_ANY=0

say() { printf '%s\n' "==> $*"; }
die() { printf '%s\n' "error: $*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
FlintTrade desktop uninstaller (macOS + Linux)

  curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash
  curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash -s -- --purge

Flags:
  --purge     Also delete the FlintTrade workspace (credential vault,
              auth.db, journals, workspace.json). Irreversible.
  --yes       Skip the --purge confirmation prompt (for scripted use).
  --dry-run   Print what would be removed without deleting anything.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown flag: $1 (see --help)" ;;
  esac
done

OS="$(uname -s)"
case "$OS" in
  Darwin|Linux) ;;
  *) die "Unsupported OS: $OS (Windows uses flinttrade-uninstall.ps1)" ;;
esac

# Remove a path if it exists; honours --dry-run, never follows the failure
# into an abort (a locked file should not strand the rest of the sweep).
remove_path() {
  local target="$1"
  [ -e "$target" ] || [ -L "$target" ] || return 0
  if [ "$DRY_RUN" = "1" ]; then
    say "[dry-run] would remove $target"
    return 0
  fi
  if rm -rf "$target" 2>/dev/null; then
    say "Removed $target"
    REMOVED_ANY=1
  else
    say "Could not remove $target (try: sudo rm -rf \"$target\")"
    FAILED_ANY=1
  fi
}

stop_running_app() {
  # Stop the desktop app and its backend sidecar so files are not busy.
  # Port 5100 is FlintTrade's backend; OpenAlgo (5000-5009) is left alone.
  if [ "$DRY_RUN" = "1" ]; then
    say "[dry-run] would stop any running FlintTrade app/backend"
    return 0
  fi
  pkill -x FlintTrade 2>/dev/null && say "Stopped the FlintTrade app" || true
  if command -v lsof >/dev/null 2>&1; then
    local backend_pid
    backend_pid="$(lsof -tiTCP:5100 -sTCP:LISTEN 2>/dev/null | head -1 || true)"
    if [ -n "${backend_pid:-}" ]; then
      kill "$backend_pid" 2>/dev/null || true
      say "Stopped the FlintTrade backend (PID $backend_pid)"
    fi
  fi
  sleep 1
}

uninstall_macos() {
  stop_running_app

  # The app bundle (install script targets /Applications, falling back to
  # ~/Applications when that is not writable).
  remove_path "/Applications/FlintTrade.app"
  remove_path "$HOME/Applications/FlintTrade.app"

  # Tauri/WKWebView residue keyed by the bundle identifier. These are the
  # folders macOS keeps after a plain drag-to-Trash uninstall.
  remove_path "$HOME/Library/WebKit/$BUNDLE_ID"
  remove_path "$HOME/Library/Caches/$BUNDLE_ID"
  remove_path "$HOME/Library/HTTPStorages/$BUNDLE_ID"
  remove_path "$HOME/Library/HTTPStorages/$BUNDLE_ID.binarycookies"
  remove_path "$HOME/Library/Application Support/$BUNDLE_ID"
  remove_path "$HOME/Library/Saved Application State/$BUNDLE_ID.savedState"
  remove_path "$HOME/Library/Logs/$BUNDLE_ID"
  if [ "$DRY_RUN" != "1" ]; then
    defaults delete "$BUNDLE_ID" >/dev/null 2>&1 || true
  fi
  remove_path "$HOME/Library/Preferences/$BUNDLE_ID.plist"

  # Install-script residue: launch log and the build-from-source clone.
  # On macOS ~/.flinttrade holds only the source clone (the workspace lives
  # under ~/Library/Application Support/flinttrade/), so it is app-side.
  remove_path "$HOME/.local/state/flinttrade"
  remove_path "$HOME/.flinttrade/src"
  rmdir "$HOME/.flinttrade" 2>/dev/null || true

  if [ "$PURGE" = "1" ]; then
    purge_workspace "$HOME/Library/Application Support/flinttrade"
  else
    keep_notice "$HOME/Library/Application Support/flinttrade"
  fi
}

uninstall_linux() {
  stop_running_app

  # Launcher footprint written by flinttrade-install.sh.
  remove_path "$HOME/.local/bin/flinttrade"
  remove_path "$HOME/.local/bin/flinttrade.AppImage"
  remove_path "$HOME/.local/opt/flinttrade"
  remove_path "$HOME/.local/share/applications/flinttrade.desktop"
  remove_path "$HOME/.local/share/icons/hicolor/128x128/apps/flinttrade.png"
  remove_path "$HOME/.local/state/flinttrade"

  # Tauri/WebKitGTK residue keyed by the bundle identifier.
  remove_path "$HOME/.local/share/$BUNDLE_ID"
  remove_path "$HOME/.cache/$BUNDLE_ID"
  remove_path "$HOME/.config/$BUNDLE_ID"

  # Build-from-source clone (the workspace itself is handled below).
  remove_path "$HOME/.flinttrade/src"

  if [ "$DRY_RUN" != "1" ]; then
    command -v update-desktop-database >/dev/null 2>&1 \
      && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
  fi

  # Legacy .deb/.rpm installs (retired artefacts from older releases) live in
  # system paths the package manager owns — point at it rather than rm.
  if [ -e /usr/bin/flinttrade ] || [ -e /usr/share/applications/flinttrade.desktop ]; then
    say "A system-wide install from a retired .deb/.rpm remains."
    say "Remove it with your package manager: sudo apt remove flinttrade  (or: sudo dnf remove flinttrade)"
  fi

  if [ "$PURGE" = "1" ]; then
    purge_workspace "$HOME/.flinttrade"
  else
    keep_notice "$HOME/.flinttrade"
  fi
}

purge_workspace() {
  local workspace="$1"
  [ -e "$workspace" ] || { say "No workspace data at $workspace"; return 0; }
  if [ "$DRY_RUN" = "1" ]; then
    say "[dry-run] would DELETE workspace data at $workspace"
    return 0
  fi
  if [ "$ASSUME_YES" != "1" ]; then
    # When piped through `curl | bash` stdin carries the script, so the
    # confirmation must come from the TTY. Without one (CI, scripts), refuse
    # rather than block or guess: --yes is the only non-interactive consent.
    if [ ! -t 1 ] || [ ! -r /dev/tty ]; then
      say "Non-interactive session: workspace data kept at $workspace (pass --yes with --purge to confirm deletion)."
      return 0
    fi
    printf '%s' "About to DELETE all FlintTrade data at $workspace (credential vault, auth.db, journals, workspace.json). This is irreversible. Type 'purge' to continue: "
    local answer=""
    read -r answer < /dev/tty || true
    if [ "$answer" != "purge" ]; then
      say "Purge cancelled — workspace data kept at $workspace"
      return 0
    fi
  fi
  remove_path "$workspace"
}

keep_notice() {
  local workspace="$1"
  if [ -e "$workspace" ]; then
    say "Workspace data kept at $workspace (credential vault, journals, settings)."
    say "To delete it too, re-run with --purge."
  fi
}

case "$OS" in
  Darwin) uninstall_macos ;;
  Linux) uninstall_linux ;;
esac

if [ "$DRY_RUN" = "1" ]; then
  say "Dry run complete — nothing was deleted."
elif [ "$FAILED_ANY" = "1" ]; then
  say "Uninstall finished with some paths left behind (see above)."
  exit 1
elif [ "$REMOVED_ANY" = "1" ]; then
  say "FlintTrade uninstalled cleanly."
else
  say "Nothing to remove — FlintTrade does not appear to be installed."
fi

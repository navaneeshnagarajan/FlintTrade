#!/usr/bin/env bash
# FlintTrade desktop uninstaller (macOS + Linux)
#
# Default mode removes the application and its disposable residue (app bundle /
# AppImage, launcher wrapper, desktop entry, icon, caches, preferences, launch
# logs, and the build-from-source clone). Two kinds of data are ALWAYS kept
# unless you explicitly pass --purge:
#   1. The FlintTrade workspace (encrypted credential vault, auth database,
#      journals, workspace.json).
#   2. The app's WebView storage, which holds in-app saved content (trade
#      journal notes and screenshots, flow-builder workflows, saved AI chats).
#
#   curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash
#   curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash -s -- --purge
#
# Flags:
#   --purge     Also delete the workspace and WebView storage above. Irreversible.
#   --yes       Skip the --purge confirmation prompt (for scripted use).
#   --dry-run   Print what would be removed without deleting anything.
#
# Environment (uninstall-specific; the install scripts never read these):
#   FLINTTRADE_UNINSTALL_PURGE=1    same as --purge
#   FLINTTRADE_UNINSTALL_YES=1      same as --yes
#   FLINTTRADE_UNINSTALL_DRY_RUN=1  same as --dry-run
#   FLINTTRADE_WORKSPACE_DIR / FLINTTRADE_HOME are honoured the same way the
#   backend honours them when resolving the workspace to purge.

set -euo pipefail

BUNDLE_ID="com.flinttrade.app"
PURGE="${FLINTTRADE_UNINSTALL_PURGE:-0}"
ASSUME_YES="${FLINTTRADE_UNINSTALL_YES:-0}"
DRY_RUN="${FLINTTRADE_UNINSTALL_DRY_RUN:-0}"
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
  --purge     Also delete the FlintTrade workspace (credential vault, auth.db,
              journals, workspace.json) and the app's WebView storage (in-app
              journal notes, flows, saved AI chats). Irreversible.
  --yes       Skip the --purge confirmation prompt (for scripted use).
  --dry-run   Print what would be removed without deleting anything.

Environment (uninstall-specific; the install scripts never read these):
  FLINTTRADE_UNINSTALL_PURGE=1 / FLINTTRADE_UNINSTALL_YES=1 /
  FLINTTRADE_UNINSTALL_DRY_RUN=1 mirror the flags for piped non-interactive
  runs, e.g.: curl -fsSL .../uninstall.sh | FLINTTRADE_UNINSTALL_PURGE=1 FLINTTRADE_UNINSTALL_YES=1 bash
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

# Resolve the workspace the way the backend does
# (flinttrade_core.workspace): FLINTTRADE_WORKSPACE_DIR beats FLINTTRADE_HOME
# beats the platform default, with a leading ~ expanded like the backend's
# expanduser(). Purging a hardcoded default while the real vault lives behind
# an override would report success and leave the data on disk — and the
# platform default stays on the data-target list even under an override,
# because pre-override data may still live there.
default_workspace() {
  if [ "$OS" = "Darwin" ]; then
    printf '%s' "$HOME/Library/Application Support/flinttrade"
  else
    printf '%s' "$HOME/.flinttrade"
  fi
}
expand_tilde() {
  case "$1" in
    "~") printf '%s' "$HOME" ;;
    "~/"*) printf '%s' "$HOME/${1#\~/}" ;;
    *) printf '%s' "$1" ;;
  esac
}
WORKSPACE_DIR="$(expand_tilde "${FLINTTRADE_WORKSPACE_DIR:-${FLINTTRADE_HOME:-$(default_workspace)}}")"
# Set per-OS before purge/keep run; labels the in-app-content line.
WEBVIEW_STORAGE_DIR=""
DATA_TARGETS=()

# Collect every FlintTrade data location that exists, deduplicated: the
# resolved workspace, the platform default (an override must not orphan it),
# the WebView storage, and any extra legacy dirs.
collect_data_targets() {
  local candidates=("$WORKSPACE_DIR" "$(default_workspace)" "$WEBVIEW_STORAGE_DIR" "$@")
  DATA_TARGETS=()
  local candidate existing seen
  for candidate in "${candidates[@]}"; do
    [ -n "$candidate" ] || continue
    [ -e "$candidate" ] || continue
    seen=0
    if [ "${#DATA_TARGETS[@]}" -gt 0 ]; then
      for existing in "${DATA_TARGETS[@]}"; do
        [ "$existing" = "$candidate" ] && seen=1
      done
    fi
    [ "$seen" = "1" ] || DATA_TARGETS+=("$candidate")
  done
}

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

# Remove a directory only when it is already empty; honours --dry-run.
remove_empty_dir() {
  local target="$1"
  [ -d "$target" ] || return 0
  [ "$DRY_RUN" = "1" ] && return 0
  rmdir "$target" 2>/dev/null || true
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
    local backend_pid owner
    backend_pid="$(lsof -tiTCP:5100 -sTCP:LISTEN 2>/dev/null | head -1 || true)"
    if [ -n "${backend_pid:-}" ]; then
      # Only kill the listener if it is actually FlintTrade's backend — 5100
      # could be an unrelated local service on a machine without FlintTrade.
      owner="$(ps -p "$backend_pid" -o command= 2>/dev/null || true)"
      if printf '%s' "$owner" | grep -qi flinttrade; then
        kill "$backend_pid" 2>/dev/null || true
        say "Stopped the FlintTrade backend (PID $backend_pid)"
      else
        say "Port 5100 is held by a non-FlintTrade process (PID $backend_pid) — leaving it alone."
      fi
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

  # Disposable Tauri/WKWebView residue keyed by the bundle identifier.
  # ~/Library/WebKit/$BUNDLE_ID is NOT here: it holds WebView localStorage,
  # the only home of in-app journal notes, flows, and saved AI chats — it is
  # data, and is only removed by --purge below.
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
  remove_path "$HOME/.local/state/flinttrade"
  remove_path "$HOME/.flinttrade/src"
  remove_empty_dir "$HOME/.flinttrade"

  WEBVIEW_STORAGE_DIR="$HOME/Library/WebKit/$BUNDLE_ID"
  if [ "$PURGE" = "1" ]; then
    purge_all_data "$HOME/.flinttrade"
  else
    keep_notice "$HOME/.flinttrade"
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

  # Disposable Tauri/WebKitGTK residue keyed by the bundle identifier.
  # ~/.local/share/$BUNDLE_ID is NOT here: it holds WebView localStorage
  # (in-app journal notes, flows, saved AI chats) and is only removed by
  # --purge below.
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

  WEBVIEW_STORAGE_DIR="$HOME/.local/share/$BUNDLE_ID"
  if [ "$PURGE" = "1" ]; then
    purge_all_data
  else
    keep_notice
  fi
}

# Purge everything the app has created: the resolved workspace, the platform
# default, the WebView storage (in-app saved content), and any extra legacy
# dirs passed in.
purge_all_data() {
  collect_data_targets "$@"
  if [ "${#DATA_TARGETS[@]}" -eq 0 ]; then
    say "No FlintTrade data to purge."
    return 0
  fi
  # An env-supplied override names an arbitrary path; --yes consent was given
  # for "the FlintTrade workspace", not for whatever the environment says.
  # Refuse the obviously-wrong targets outright.
  local target safe=()
  for target in "${DATA_TARGETS[@]}"; do
    case "${target%/}" in
      ""|"$HOME"|"${HOME%/}")
        say "Refusing to purge $target — not a FlintTrade data directory."
        FAILED_ANY=1
        ;;
      *) safe+=("$target") ;;
    esac
  done
  if [ "${#safe[@]}" -eq 0 ]; then
    return 0
  fi
  if [ "$DRY_RUN" = "1" ]; then
    for target in "${safe[@]}"; do
      say "[dry-run] would DELETE FlintTrade data at $target"
    done
    return 0
  fi
  if [ "$ASSUME_YES" = "1" ]; then
    # Scripted consent still gets told exactly what is being deleted.
    say "Purging FlintTrade data:"
    for target in "${safe[@]}"; do
      say "  $target"
    done
  else
    # When piped through `curl | bash` stdin carries the script, so the
    # confirmation must come from the TTY. Without one (CI, scripts), refuse
    # rather than block or guess: --yes is the only non-interactive consent.
    if [ ! -t 1 ] || [ ! -r /dev/tty ]; then
      say "Non-interactive session: FlintTrade data kept (pass --yes with --purge to confirm deletion)."
      return 0
    fi
    say "About to DELETE all FlintTrade data:"
    for target in "${safe[@]}"; do
      say "  $target"
    done
    printf '%s' "This removes the credential vault, auth.db, journals, settings, and in-app saved content (journal notes, flows, AI chats). Irreversible. Type 'purge' to continue: "
    local answer=""
    read -r answer < /dev/tty || true
    if [ "$answer" != "purge" ]; then
      say "Purge cancelled — FlintTrade data kept."
      return 0
    fi
  fi
  for target in "${safe[@]}"; do
    remove_path "$target"
  done
}

# Reports the same target set purge_all_data would delete, so nothing --purge
# would remove goes unmentioned on a default run.
keep_notice() {
  collect_data_targets "$@"
  [ "${#DATA_TARGETS[@]}" -gt 0 ] || return 0
  local target
  for target in "${DATA_TARGETS[@]}"; do
    if [ "$target" = "$WEBVIEW_STORAGE_DIR" ]; then
      say "In-app saved content kept at $target (journal notes, flows, saved AI chats)."
    else
      say "Workspace data kept at $target (credential vault, journals, settings)."
    fi
  done
  say "To delete all FlintTrade data too, re-run with --purge."
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

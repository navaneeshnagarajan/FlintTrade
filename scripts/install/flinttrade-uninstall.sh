#!/usr/bin/env bash
# FlintTrade Electron shell uninstaller (macOS + Linux)
#
# Ordinary uninstall removes only the shell and launch integration. The trading
# workspace, Electron profile, managed source/toolchain, the contributor
# source-build checkout, the pre-workspace data directories and legacy desktop
# data are all retained. --purge lists every resolved path and requires explicit
# confirmation before deleting them, because for an upgraded install the
# pre-workspace directories still hold real trading state.
#
#   curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash
#   curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash -s -- --purge

set -euo pipefail

LEGACY_BUNDLE_ID="com.flinttrade.app"
PURGE="${FLINTTRADE_UNINSTALL_PURGE:-0}"
ASSUME_YES="${FLINTTRADE_UNINSTALL_YES:-0}"
DRY_RUN="${FLINTTRADE_UNINSTALL_DRY_RUN:-0}"
REMOVED_ANY=0
SHELL_REMOVED_ANY=0
WEB_REMOVED_ANY=0
FAILED_ANY=0
PURGE_COMPLETED=0
PURGED_DATA_ANY=0
DATA_FOUND_ANY=0
DATA_RETAINED_ANY=0
DATA_TARGETS=()
SHELL_RECEIPT_DIR="$HOME/.local/state/flinttrade"
SHELL_RECEIPT_PATH="$SHELL_RECEIPT_DIR/shell-install.receipt"
SHELL_LAUNCH_LOG="$SHELL_RECEIPT_DIR/desktop-launch.log"
# The one-line web installer records everything it writes outside the managed
# root here (flinttrade-web-install.sh). Without it the launcher shim was
# orphaned residue: no uninstall path could prove it, so it was either left
# forever (macOS) or reported as an unprovable failure (Linux).
WEB_RECEIPT_DIR="$HOME/.local/state/flinttrade-web"
WEB_RECEIPT_PATH="$WEB_RECEIPT_DIR/web-install.receipt"
WEB_RECEIPT_VALID=0
WEB_SHIM_PROVEN=0
WEB_RECEIPT_RETAINED=0
WEB_RECEIPT_SHIM=""
WEB_RECEIPT_SHIM_SHA256=""
WEB_RECEIPT_SHORTCUT=""
WEB_RECEIPT_SOURCE=""
WEB_RECEIPT_TOOLS=""
RECEIPT_KIND=""
RECEIPT_TARGET=""
RECEIPT_EXECUTABLE=""
RECEIPT_EXECUTABLE_SHA256=""
RECEIPT_WRAPPER=""
RECEIPT_DESKTOP=""
RECEIPT_ICON=""
RECEIPT_ICON_SHA256=""

say() { printf '%s\n' "==> $*"; }
die() { printf '%s\n' "error: $*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
FlintTrade Electron shell uninstaller (macOS + Linux)

Flags:
  --purge    Also delete the workspace, Electron profile, managed source/tools,
             the source-build checkout (~/.flinttrade/source-build, or
             FLINTTRADE_SRC_DIR only when an installer receipt proves it is a
             FlintTrade-managed checkout), the pre-workspace ~/.flinttrade
             data/archive/sandbox directories, the whole ~/.flinttrade managed
             root and legacy desktop storage. Every resolved path is printed
             first. Irreversible after confirmation.
  --yes      Skip the typed --purge confirmation for scripted use. The full
             list of paths is still printed before anything is deleted.
  --dry-run  Print what would be removed without deleting anything.
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
case "$OS" in Darwin|Linux) ;; *) die "Unsupported OS: $OS (Windows uses flinttrade-uninstall.ps1)" ;; esac

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
    "~"*) die "Named-user home paths are not supported: $1" ;;
    *) printf '%s' "$1" ;;
  esac
}

# A relative override otherwise resolves against the uninstaller's own working
# directory at every later use, so the path that gets printed is not necessarily
# the path that would be deleted. Resolve it once, up front.
absolute_path() {
  local value="$1"
  [ -n "$value" ] || return 0
  case "$value" in
    /*) printf '%s' "$value" ;;
    *) printf '%s/%s' "$(pwd -P)" "$value" ;;
  esac
}

WORKSPACE_DIR="$(expand_tilde "${FLINTTRADE_WORKSPACE_DIR:-${FLINTTRADE_HOME:-$(default_workspace)}}")"
MANAGED_ROOT="$HOME/.flinttrade"
SOURCE_ROOT="$MANAGED_ROOT/src"
TOOLS_ROOT="$MANAGED_ROOT/tools"
# The same installer family clones the contributor checkout here
# (flinttrade-install.sh --src defaults to $SOURCE_BUILD_ROOT/FlintTrade;
# FLINTTRADE_SRC_DIR overrides it). On macOS the workspace lives under
# ~/Library/Application Support, so nothing else in the purge list would ever
# reach this tree — a multi-GB clone plus node_modules survived forever while
# keep_notice claimed nothing else remained.
SOURCE_BUILD_ROOT="$MANAGED_ROOT/source-build"
SRC_DIR_OVERRIDE="$(absolute_path "$(expand_tilde "${FLINTTRADE_SRC_DIR:-}")")"
# Pre-workspace data directories. workspace.py still reads these at every
# backend start, and its migration COPIES rather than moves — so they retain a
# live copy of the DuckDB store, the append-only audit chain and the encrypted
# broker-credential vault. Purging them is real data loss for an upgraded
# install, which is why every path is printed before any confirmation.
LEGACY_DATA_DIR="$MANAGED_ROOT/data"
LEGACY_ARCHIVE_DIR="$MANAGED_ROOT/archive"
LEGACY_SANDBOX_DIR="$MANAGED_ROOT/sandbox"
LEGACY_DITTO_VAULT="$LEGACY_DATA_DIR/ditto_credentials.db"
ELECTRON_PROFILE=""

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
    say "Could not remove $target (try removing it manually)."
    FAILED_ANY=1
  fi
}

canonical_existing_path() {
  local target="$1" parent
  if [ -d "$target" ]; then
    (cd -P "$target" 2>/dev/null && pwd -P)
    return
  fi
  parent="$(cd -P "$(dirname "$target")" 2>/dev/null && pwd -P)" || return 1
  printf '%s/%s' "${parent%/}" "$(basename "$target")"
}

sha256_file() {
  local target="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$target" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$target" | awk '{print $1}'
  else
    return 1
  fi
}

private_mode() {
  /usr/bin/stat -c '%a' "$1" 2>/dev/null || /usr/bin/stat -f '%Lp' "$1" 2>/dev/null
}

refuse_unproven_shell() {
  say "Refusing to remove $1 — $2."
  FAILED_ANY=1
}

lower_hex() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

# ---------------------------------------------------------------------------
# Web-install receipt.
#
# Exit status: 0 the receipt is valid, 1 no web install was ever recorded,
# 2 the receipt exists but does not prove itself. Only status 0 authorises
# removing anything, and status 1 is never an uninstall failure — a machine
# without the one-line web install simply has nothing here to remove.
# ---------------------------------------------------------------------------

read_web_receipt() {
  local line1 line2 line3 line4 line5 line6 line7 extra mode default_shim owned shim_owned
  [ -e "$WEB_RECEIPT_PATH" ] || [ -L "$WEB_RECEIPT_PATH" ] || return 1
  if [ ! -d "$WEB_RECEIPT_DIR" ] || [ -L "$WEB_RECEIPT_DIR" ] || [ ! -O "$WEB_RECEIPT_DIR" ]; then
    say "Leaving $WEB_RECEIPT_PATH — its receipt directory is not owner-local."
    return 2
  fi
  mode="$(private_mode "$WEB_RECEIPT_DIR")"
  if [ "$mode" != "700" ]; then
    say "Leaving $WEB_RECEIPT_PATH — its receipt directory is not private."
    return 2
  fi
  if [ ! -f "$WEB_RECEIPT_PATH" ] || [ -L "$WEB_RECEIPT_PATH" ] || [ ! -O "$WEB_RECEIPT_PATH" ]; then
    say "Leaving $WEB_RECEIPT_PATH — the receipt is not an owner-local ordinary file."
    return 2
  fi
  mode="$(private_mode "$WEB_RECEIPT_PATH")"
  if [ "$mode" != "600" ]; then
    say "Leaving $WEB_RECEIPT_PATH — the receipt is not private."
    return 2
  fi
  if ! {
    IFS= read -r line1 && IFS= read -r line2 && IFS= read -r line3 && IFS= read -r line4 \
      && IFS= read -r line5 && IFS= read -r line6 && IFS= read -r line7 && ! IFS= read -r extra
  } < "$WEB_RECEIPT_PATH"; then
    say "Leaving $WEB_RECEIPT_PATH — the receipt shape is invalid."
    return 2
  fi
  if [ "$line1" != "format=flinttrade-web-install-v1" ] || [ "$line2" != "platform=$OS" ]; then
    say "Leaving $WEB_RECEIPT_PATH — the receipt format or platform does not match."
    return 2
  fi
  if [[ "$line3" != shim=* || "$line4" != shim_sha256=* || "$line5" != shortcut=* \
      || "$line6" != source=* || "$line7" != tools=* ]]; then
    say "Leaving $WEB_RECEIPT_PATH — the receipt field names are invalid."
    return 2
  fi
  WEB_RECEIPT_SHIM="${line3#shim=}"
  WEB_RECEIPT_SHIM_SHA256="${line4#shim_sha256=}"
  WEB_RECEIPT_SHORTCUT="${line5#shortcut=}"
  WEB_RECEIPT_SOURCE="${line6#source=}"
  WEB_RECEIPT_TOOLS="${line7#tools=}"
  if [ -z "$WEB_RECEIPT_SHIM" ] || [ "${#WEB_RECEIPT_SHIM_SHA256}" -ne 64 ]; then
    say "Leaving $WEB_RECEIPT_PATH — the receipt omits exact launcher identity."
    return 2
  fi
  # The shortcut field is Windows-only; a POSIX receipt that fills it in was not
  # written by flinttrade-web-install.sh.
  if [ -n "$WEB_RECEIPT_SHORTCUT" ]; then
    say "Leaving $WEB_RECEIPT_PATH — the receipt records a shortcut this platform never installs."
    return 2
  fi
  # The receipt may only ever aim the remover at a location the web installer
  # writes a launcher to; it is not a general deletion instruction. Both the
  # current name and the pre-collision one are accepted: revisions before
  # ~/.local/bin/flinttrade-web wrote ~/.local/bin/flinttrade, which the Electron
  # desktop installer also owns, and those machines still deserve a clean
  # uninstall. Identity is not assumed from the path either way — the launcher is
  # removed only when its SHA-256 still matches the receipt.
  shim_owned=0
  for owned in "$HOME/.local/bin/flinttrade-web" "$HOME/.local/bin/flinttrade"; do
    default_shim="$(canonical_existing_path "$owned" 2>/dev/null)" || default_shim="$owned"
    if [ "$WEB_RECEIPT_SHIM" = "$default_shim" ] || [ "$WEB_RECEIPT_SHIM" = "$owned" ]; then
      shim_owned=1
      break
    fi
  done
  if [ "$shim_owned" != "1" ]; then
    say "Leaving $WEB_RECEIPT_PATH — the recorded launcher is not the installer-owned location."
    return 2
  fi
  case "$WEB_RECEIPT_SHIM_SHA256" in
    *[!0-9A-Fa-f]*)
      say "Leaving $WEB_RECEIPT_PATH — the receipt contains an invalid digest."
      return 2
      ;;
  esac
  WEB_RECEIPT_VALID=1
  return 0
}

remove_web_install() {
  local receipt_status=0 actual
  if read_web_receipt; then
    receipt_status=0
  else
    receipt_status=$?
  fi
  # A missing or unproven receipt never authorises deleting a launcher, and an
  # absent web install is not a failure.
  [ "$receipt_status" = "0" ] || return 0
  if [ -e "$WEB_RECEIPT_SHIM" ] || [ -L "$WEB_RECEIPT_SHIM" ]; then
    if [ ! -f "$WEB_RECEIPT_SHIM" ] || [ -L "$WEB_RECEIPT_SHIM" ]; then
      say "Leaving $WEB_RECEIPT_SHIM — the recorded launcher is not an ordinary file."
      say "Keeping $WEB_RECEIPT_PATH so a later run can retry."
      return 0
    fi
    actual="$(sha256_file "$WEB_RECEIPT_SHIM" 2>/dev/null || true)"
    if [ -z "$actual" ] || [ "$(lower_hex "$actual")" != "$(lower_hex "$WEB_RECEIPT_SHIM_SHA256")" ]; then
      say "Leaving $WEB_RECEIPT_SHIM — its SHA-256 identity does not match the web-install receipt."
      say "Keeping $WEB_RECEIPT_PATH so a later run can retry."
      return 0
    fi
    WEB_SHIM_PROVEN=1
    remove_path "$WEB_RECEIPT_SHIM"
    if [ "$DRY_RUN" != "1" ] && { [ -e "$WEB_RECEIPT_SHIM" ] || [ -L "$WEB_RECEIPT_SHIM" ]; }; then
      say "Keeping $WEB_RECEIPT_PATH because the recorded launcher could not be removed."
      return 0
    fi
    if [ "$DRY_RUN" != "1" ]; then
      say "Removed the launcher recorded by $WEB_RECEIPT_PATH."
      WEB_REMOVED_ANY=1
    fi
  fi
  # An ordinary uninstall deliberately RETAINS the managed source and tools the
  # receipt records — and for a custom --src outside ~/.flinttrade that receipt
  # is the only thing that names them. Deleting it here left a later --purge
  # with no proof and no path, so the custom checkout was omitted permanently.
  # Keep the receipt for exactly as long as it still proves retained data.
  if web_install_data_still_present; then
    WEB_RECEIPT_RETAINED=1
    say "Keeping $WEB_RECEIPT_PATH — it is the only proof of the retained web-install data below,"
    say "so a later --purge can still find and authorise it:"
    [ -z "$WEB_RECEIPT_SOURCE" ] || say "  $WEB_RECEIPT_SOURCE"
    [ -z "$WEB_RECEIPT_TOOLS" ] || say "  $WEB_RECEIPT_TOOLS"
    return 0
  fi
  remove_path "$WEB_RECEIPT_PATH"
  if [ "$DRY_RUN" != "1" ] && [ -d "$WEB_RECEIPT_DIR" ]; then
    if rmdir "$WEB_RECEIPT_DIR" 2>/dev/null; then
      say "Removed $WEB_RECEIPT_DIR"
      REMOVED_ANY=1
    fi
  fi
}

# Whether anything the web-install receipt records as retained data is still on
# disk. The launcher is not retained data — it is removed by the ordinary
# uninstall — so only the managed source and tools count here.
web_install_data_still_present() {
  local candidate
  [ "$WEB_RECEIPT_VALID" = "1" ] || return 1
  for candidate in "$WEB_RECEIPT_SOURCE" "$WEB_RECEIPT_TOOLS"; do
    [ -n "$candidate" ] || continue
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then return 0; fi
  done
  return 1
}

# The retained receipt is retired once it no longer proves anything: a --purge
# in this same run has just removed the recorded source and tools, so the
# receipt is removed exactly as an ordinary uninstall would have removed it.
remove_retained_web_receipt() {
  [ "$WEB_RECEIPT_RETAINED" = "1" ] || return 0
  [ "$DRY_RUN" != "1" ] || return 0
  if web_install_data_still_present; then return 0; fi
  remove_path "$WEB_RECEIPT_PATH"
  if [ -d "$WEB_RECEIPT_DIR" ]; then
    if rmdir "$WEB_RECEIPT_DIR" 2>/dev/null; then
      say "Removed $WEB_RECEIPT_DIR"
      REMOVED_ANY=1
    fi
  fi
}

read_shell_receipt() {
  local line1 line2 line3 line4 line5 line6 line7 line8 line9 line10 extra mode
  [ -e "$SHELL_RECEIPT_PATH" ] || [ -L "$SHELL_RECEIPT_PATH" ] || return 1
  if [ ! -d "$SHELL_RECEIPT_DIR" ] || [ -L "$SHELL_RECEIPT_DIR" ] || [ ! -O "$SHELL_RECEIPT_DIR" ]; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "its receipt directory is not owner-local"
    return 2
  fi
  mode="$(private_mode "$SHELL_RECEIPT_DIR")"
  if [ "$mode" != "700" ]; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "its receipt directory is not private"
    return 2
  fi
  if [ ! -f "$SHELL_RECEIPT_PATH" ] || [ -L "$SHELL_RECEIPT_PATH" ] || [ ! -O "$SHELL_RECEIPT_PATH" ]; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the receipt is not an owner-local ordinary file"
    return 2
  fi
  mode="$(private_mode "$SHELL_RECEIPT_PATH")"
  if [ "$mode" != "600" ]; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the receipt is not private"
    return 2
  fi
  if ! {
    IFS= read -r line1 && IFS= read -r line2 && IFS= read -r line3 && IFS= read -r line4 \
      && IFS= read -r line5 && IFS= read -r line6 && IFS= read -r line7 && IFS= read -r line8 \
      && IFS= read -r line9 && IFS= read -r line10 && ! IFS= read -r extra
  } < "$SHELL_RECEIPT_PATH"; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the receipt shape is invalid"
    return 2
  fi
  if [ "$line1" != "format=flinttrade-electron-shell-v1" ] \
      || [ "$line2" != "platform=$OS" ]; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the receipt format or platform does not match"
    return 2
  fi
  if [[ "$line3" != kind=* || "$line4" != target=* || "$line5" != executable=* \
      || "$line6" != executable_sha256=* || "$line7" != wrapper=* || "$line8" != desktop=* \
      || "$line9" != icon=* || "$line10" != icon_sha256=* ]]; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the receipt field names are invalid"
    return 2
  fi
  RECEIPT_KIND="${line3#kind=}"
  RECEIPT_TARGET="${line4#target=}"
  RECEIPT_EXECUTABLE="${line5#executable=}"
  RECEIPT_EXECUTABLE_SHA256="${line6#executable_sha256=}"
  RECEIPT_WRAPPER="${line7#wrapper=}"
  RECEIPT_DESKTOP="${line8#desktop=}"
  RECEIPT_ICON="${line9#icon=}"
  RECEIPT_ICON_SHA256="${line10#icon_sha256=}"
  if [ -z "$RECEIPT_TARGET" ] || [ -z "$RECEIPT_EXECUTABLE" ] \
      || [ "${#RECEIPT_EXECUTABLE_SHA256}" -ne 64 ]; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the receipt omits exact shell identity"
    return 2
  fi
  case "$RECEIPT_EXECUTABLE_SHA256$RECEIPT_ICON_SHA256" in
    *[!0-9A-Fa-f]*)
      refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the receipt contains an invalid digest"
      return 2
      ;;
  esac
  if { [ -n "$RECEIPT_ICON" ] && [ "${#RECEIPT_ICON_SHA256}" -ne 64 ]; } \
      || { [ -z "$RECEIPT_ICON" ] && [ -n "$RECEIPT_ICON_SHA256" ]; }; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the receipt icon identity is inconsistent"
    return 2
  fi
  return 0
}

verify_file_digest() {
  local target="$1" expected="$2" actual
  actual="$(sha256_file "$target")" || {
    refuse_unproven_shell "$target" "its SHA-256 identity cannot be checked"
    return 1
  }
  if [ "$(printf '%s' "$actual" | tr '[:upper:]' '[:lower:]')" \
      != "$(printf '%s' "$expected" | tr '[:upper:]' '[:lower:]')" ]; then
    refuse_unproven_shell "$target" "its SHA-256 identity does not match the install receipt"
    return 1
  fi
}

verify_receipt_state_directory() {
  local candidate name
  if [ -e "$SHELL_LAUNCH_LOG" ] || [ -L "$SHELL_LAUNCH_LOG" ]; then
    if [ ! -f "$SHELL_LAUNCH_LOG" ] || [ -L "$SHELL_LAUNCH_LOG" ] || [ ! -O "$SHELL_LAUNCH_LOG" ]; then
      refuse_unproven_shell "$SHELL_LAUNCH_LOG" "the launch log is not an owner-local ordinary file"
      return 1
    fi
  fi
  for candidate in "$SHELL_RECEIPT_DIR"/* "$SHELL_RECEIPT_DIR"/.[!.]* "$SHELL_RECEIPT_DIR"/..?*; do
    [ -e "$candidate" ] || [ -L "$candidate" ] || continue
    name="$(basename "$candidate")"
    case "$name" in shell-install.receipt|desktop-launch.log) ;;
      *)
        refuse_unproven_shell "$candidate" "it is not recorded shell state"
        return 1
        ;;
    esac
  done
}

canonical_receipt_path_matches() {
  local target="$1" expected="$2" canonical
  canonical="$(canonical_existing_path "$target")" || return 1
  [ "$canonical" = "$expected" ]
}

path_inside_proven_target() {
  local candidate="$1"
  if [ -d "$RECEIPT_TARGET" ]; then
    case "$candidate" in "$RECEIPT_TARGET"|"$RECEIPT_TARGET"/*) return 0 ;; esac
  else
    [ "$candidate" = "$RECEIPT_TARGET" ] && return 0
  fi
  return 1
}

process_executable() {
  local pid="$1" executable command candidate="" part command_parts=("")
  if [ "$OS" = "Linux" ]; then
    executable="$(/usr/bin/readlink "/proc/$pid/exe" 2>/dev/null)" || return 1
    executable="${executable% (deleted)}"
  else
    command="$(/bin/ps -ww -p "$pid" -o command= 2>/dev/null)" || return 1
    command="${command#${command%%[![:space:]]*}}"
    IFS=' ' read -r -a command_parts <<< "$command"
    for part in "${command_parts[@]}"; do
      if [ -n "$candidate" ]; then candidate="$candidate $part"; else candidate="$part"; fi
      if [ -f "$candidate" ] && [ -x "$candidate" ]; then
        executable="$candidate"
        break
      fi
    done
  fi
  [ -n "$executable" ] && [ -e "$executable" ] || return 1
  canonical_existing_path "$executable"
}

direct_appimage_process_matches() {
  local pid="$1" executable="$2" entry appimage_match=0
  [ "$OS" = "Linux" ] && [ "$RECEIPT_KIND" = "linux-appimage" ] || return 1
  case "$executable" in */.mount_*/*) ;; *) return 1 ;; esac
  [ -f "$executable" ] && [ -x "$executable" ] || return 1
  while IFS= read -r -d '' entry; do
    if [ "$entry" = "APPIMAGE=$RECEIPT_TARGET" ]; then appimage_match=1; break; fi
  done < "/proc/$pid/environ" 2>/dev/null || true
  [ "$appimage_match" = "1" ]
}

process_matches_proven_shell() {
  local pid="$1" executable="$2"
  path_inside_proven_target "$executable" || direct_appimage_process_matches "$pid" "$executable"
}

matching_shell_processes() {
  local pid executable process
  if [ "$OS" = "Linux" ]; then
    for process in /proc/[0-9]*; do
      [ -d "$process" ] || continue
      pid="${process##*/}"
      [ "$pid" != "$$" ] || continue
      executable="$(process_executable "$pid")" || continue
      process_matches_proven_shell "$pid" "$executable" && printf '%s\n' "$pid"
    done
  else
    while read -r pid executable; do
      case "$pid" in ''|*[!0-9]*) continue ;; esac
      [ "$pid" != "$$" ] || continue
      executable="$(process_executable "$pid")" || continue
      process_matches_proven_shell "$pid" "$executable" && printf '%s\n' "$pid"
    done < <(/bin/ps -axo pid=,comm= 2>/dev/null)
  fi
}

process_still_matches() {
  local pid="$1" executable
  kill -0 "$pid" 2>/dev/null || return 1
  executable="$(process_executable "$pid")" || return 1
  process_matches_proven_shell "$pid" "$executable"
}

stop_proven_shell_processes() {
  local pids=("") pid attempt survivors=("")
  while IFS= read -r pid; do [ -n "$pid" ] && pids+=("$pid"); done < <(matching_shell_processes)
  [ "${#pids[@]}" -gt 1 ] || return 0
  if [ "$DRY_RUN" = "1" ]; then
    for pid in "${pids[@]}"; do [ -n "$pid" ] && say "[dry-run] would stop proved FlintTrade shell process $pid"; done
    return 0
  fi
  for pid in "${pids[@]}"; do
    [ -n "$pid" ] || continue
    process_still_matches "$pid" && kill -TERM "$pid" 2>/dev/null || true
  done
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    survivors=("")
    for pid in "${pids[@]}"; do
      [ -n "$pid" ] && process_still_matches "$pid" && survivors+=("$pid")
    done
    [ "${#survivors[@]}" -eq 1 ] && break
    /bin/sleep 0.1
  done
  if [ "${#survivors[@]}" -gt 1 ]; then
    for pid in "${survivors[@]}"; do
      [ -n "$pid" ] || continue
      process_still_matches "$pid" && kill -KILL "$pid" 2>/dev/null || true
    done
    /bin/sleep 0.1
  fi
  for pid in "${pids[@]}"; do
    [ -n "$pid" ] || continue
    if process_still_matches "$pid"; then
      refuse_unproven_shell "$RECEIPT_TARGET" "proved shell process $pid could not be stopped"
      return 1
    fi
  done
  say "Stopped the proved FlintTrade shell process set"
}

add_data_target() {
  local candidate="$1" existing
  [ -n "$candidate" ] || return 0
  [ -e "$candidate" ] || [ -L "$candidate" ] || return 0
  if [ "${#DATA_TARGETS[@]}" -gt 0 ]; then
    for existing in "${DATA_TARGETS[@]}"; do
      [ "$existing" = "$candidate" ] && return 0
    done
  fi
  DATA_TARGETS+=("$candidate")
}

collect_data_targets() {
  DATA_TARGETS=()
  DATA_FOUND_ANY=0
  add_data_target "$WORKSPACE_DIR"
  add_data_target "$(default_workspace)"
  add_data_target "$ELECTRON_PROFILE"
  add_data_target "$SOURCE_ROOT"
  add_data_target "$TOOLS_ROOT"
  add_data_target "$SOURCE_BUILD_ROOT"
  # An FLINTTRADE_SRC_DIR override is only honoured when an installer receipt
  # proves the checkout is FlintTrade's own. A shape match alone is every
  # contributor clone, so it must never aim rm -rf at a working tree that holds
  # uncommitted work.
  if [ -n "$SRC_DIR_OVERRIDE" ]; then
    if proven_source_checkout "$SRC_DIR_OVERRIDE"; then
      add_data_target "$SRC_DIR_OVERRIDE"
    elif [ -d "$SRC_DIR_OVERRIDE" ]; then
      say "Leaving $SRC_DIR_OVERRIDE — no FlintTrade installer receipt proves this source checkout."
    fi
  fi
  if [ "$WEB_RECEIPT_VALID" = "1" ]; then
    add_data_target "$WEB_RECEIPT_SOURCE"
    add_data_target "$WEB_RECEIPT_TOOLS"
    # Only a launcher whose digest still matched the receipt is purge-eligible;
    # --purge must not finish a deletion the ordinary path already refused.
    if [ "$WEB_SHIM_PROVEN" = "1" ]; then add_data_target "$WEB_RECEIPT_SHIM"; fi
  fi
  add_data_target "$LEGACY_DATA_DIR"
  add_data_target "$LEGACY_ARCHIVE_DIR"
  add_data_target "$LEGACY_SANDBOX_DIR"
  add_data_target "$LEGACY_DITTO_VAULT"
  # The managed root itself, after the specific subtrees above so the printed
  # list still names them explicitly. On macOS and Windows around nineteen
  # modules write DIRECTLY at ~/.flinttrade/<name> — totp_auth.duckdb,
  # totp_install_key, shortcuts.duckdb, journal.sqlite, qty_freeze.duckdb,
  # action_center.duckdb, watchlist.db, flows/ and strategies/ among them — so
  # enumerating only the subdirectories left TOTP secrets and realised-P&L
  # state behind while claiming everything had been purged.
  add_data_target "$MANAGED_ROOT"
  local candidate
  for candidate in "$@"; do add_data_target "$candidate"; done
  [ "${#DATA_TARGETS[@]}" -eq 0 ] || DATA_FOUND_ANY=1
}

web_receipt_names_source() {
  local target="${1%/}" canonical
  [ "$WEB_RECEIPT_VALID" = "1" ] || return 1
  [ -n "$WEB_RECEIPT_SOURCE" ] || return 1
  [ "$target" = "${WEB_RECEIPT_SOURCE%/}" ] && return 0
  canonical="$(canonical_existing_path "$target")" || return 1
  [ "$canonical" = "${WEB_RECEIPT_SOURCE%/}" ]
}

proven_source_checkout() {
  local target="$1" marker
  [ -d "$target" ] && [ ! -L "$target" ] || return 1
  for marker in .git pnpm-lock.yaml uv.lock pyproject.toml; do
    [ -e "$target/$marker" ] || return 1
  done
  # Shape is not identity: .git + pnpm-lock.yaml + uv.lock + pyproject.toml is
  # every contributor clone of this repository. Recursive deletion of a source
  # checkout is authorised only by an installer-written receipt, exactly as the
  # shell-removal path requires its own receipt.
  web_receipt_names_source "$target" || return 1
  return 0
}

proven_custom_workspace() {
  local target="$1" marker
  [ -d "$target" ] && [ ! -L "$target" ] \
    && [ -f "$target/workspace.json" ] && [ ! -L "$target/workspace.json" ] \
    || return 1
  for marker in credentials.db auth.db security.db master_password api_key_pepper safety_gate_secret; do
    if [ -f "$target/$marker" ] && [ ! -L "$target/$marker" ]; then return 0; fi
  done
  return 1
}

path_has_symlink_below_anchor() {
  local anchor="${1%/}" target="${2%/}" relative current component
  case "$target" in
    "$anchor"/*) relative="${target#"$anchor"/}" ;;
    *) return 2 ;;
  esac
  current="$anchor"
  while [ -n "$relative" ]; do
    case "$relative" in
      */*) component="${relative%%/*}"; relative="${relative#*/}" ;;
      *) component="$relative"; relative="" ;;
    esac
    [ -n "$component" ] || continue
    current="${current%/}/$component"
    [ ! -L "$current" ] || return 0
  done
  return 1
}

safe_purge_targets() {
  local target canonical home_canonical existing duplicate safe=()
  home_canonical="$(cd -P "$HOME" 2>/dev/null && pwd -P)" || home_canonical="$HOME"
  # Bash 3.2 treats expansion of a declared-but-empty array as an unbound
  # variable under `set -u`; guard the expansion for a genuinely empty home.
  if [ "${#DATA_TARGETS[@]}" -eq 0 ]; then
    DATA_TARGETS=()
    return 0
  fi
  for target in "${DATA_TARGETS[@]}"; do
    target="${target%/}"
    if [ -L "$target" ]; then
      say "Refusing to purge $target — purge targets cannot be symbolic links."
      FAILED_ANY=1
      continue
    fi
    canonical="$(cd -P "$(dirname "$target")" 2>/dev/null && printf '%s/%s' "$(pwd -P)" "$(basename "$target")")" \
      || canonical="$target"
    case "$canonical" in
      ""|"/"|"$home_canonical"|"${home_canonical%/}")
        say "Refusing to purge $target — not a FlintTrade data directory."
        FAILED_ANY=1
        continue
        ;;
    esac

    if [ "$target" = "${WORKSPACE_DIR%/}" ] && [ "${WORKSPACE_DIR%/}" != "$(default_workspace)" ]; then
      if ! proven_custom_workspace "$target"; then
        say "Refusing to purge $target — custom workspace identity is not proven."
        FAILED_ANY=1
        continue
      fi
    fi

    case "$target" in
      "${HOME%/}"/*) ;;
      *)
        say "Refusing to purge $target — not a recognised FlintTrade data path inside the current user's home."
        FAILED_ANY=1
        continue
        ;;
    esac
    if path_has_symlink_below_anchor "$HOME" "$target"; then
      say "Refusing to purge $target — a path component is a symbolic link."
      FAILED_ANY=1
      continue
    fi
    case "$canonical" in
      "${home_canonical%/}"/*) ;;
      *)
        say "Refusing to purge $target — it resolves outside the current user's home."
        FAILED_ANY=1
        continue
        ;;
    esac

    duplicate=0
    if [ "${#safe[@]}" -gt 0 ]; then
      for existing in "${safe[@]}"; do
        [ "$existing" != "$canonical" ] || duplicate=1
      done
    fi
    [ "$duplicate" = "1" ] || safe+=("$canonical")
  done
  DATA_TARGETS=()
  if [ "${#safe[@]}" -gt 0 ]; then DATA_TARGETS=("${safe[@]}"); fi
}

purge_all_data() {
  collect_data_targets "$@"
  safe_purge_targets
  if [ "${#DATA_TARGETS[@]}" -eq 0 ]; then
    if [ "$DATA_FOUND_ANY" = "1" ]; then
      say "No identity-proven FlintTrade data was eligible for purge."
    else
      say "No FlintTrade data to purge."
    fi
    return 0
  fi
  if [ "$DRY_RUN" = "1" ]; then
    local target
    for target in "${DATA_TARGETS[@]}"; do say "[dry-run] would DELETE FlintTrade data at $target"; done
    return 0
  fi

  # Bail out of an unconfirmable session BEFORE announcing the deletion list:
  # a piped run used to print the full scary "About to DELETE" list and then
  # keep everything, which read as a deletion that had already happened.
  if [ "$ASSUME_YES" != "1" ] && { [ ! -t 1 ] || [ ! -r /dev/tty ]; }; then
    say "Non-interactive session: FlintTrade data kept (pass --yes with --purge to confirm deletion)."
    DATA_RETAINED_ANY=1
    return 0
  fi
  announce_purge_targets
  if [ "$ASSUME_YES" != "1" ]; then
    local answer=""
    printf '%s' "This is irreversible. Type 'purge' to continue: "
    read -r answer < /dev/tty || true
    if [ "$answer" != "purge" ]; then
      say "Purge cancelled — FlintTrade data kept."
      DATA_RETAINED_ANY=1
      return 0
    fi
  else
    say "Purge explicitly confirmed with --yes; deleting every path listed above."
  fi

  local target
  for target in "${DATA_TARGETS[@]}"; do remove_path "$target"; done
  if [ "$FAILED_ANY" != "1" ]; then
    PURGE_COMPLETED=1
    PURGED_DATA_ANY=1
  fi
}

announce_purge_targets() {
  local target
  say "About to DELETE the FlintTrade workspace, Electron profile, managed source/tools,"
  say "source-build checkout, pre-workspace storage, the whole ~/.flinttrade managed root"
  say "and legacy desktop data listed below:"
  for target in "${DATA_TARGETS[@]}"; do say "  $target"; done
  say "~/.flinttrade itself also holds files written directly at its top level — the TOTP"
  say "secret store and install key, shortcuts, the trade journal, quantity-freeze and"
  say "action-centre stores, the watchlist, flows/ and strategies/ — so purging it is real"
  say "trading state, not just the subdirectories named above."
  say "Any ~/.flinttrade/data, ~/.flinttrade/archive or ~/.flinttrade/sandbox path above is"
  say "pre-workspace storage that the backend still reads: the DuckDB store, the append-only"
  say "audit chain and the encrypted broker-credential vault live there, so an upgraded"
  say "install loses real trading state here — not just a cache."
}

keep_notice() {
  collect_data_targets "$@"
  [ "${#DATA_TARGETS[@]}" -gt 0 ] || return 0
  DATA_RETAINED_ANY=1
  say "The following FlintTrade data was kept:"
  local target
  for target in "${DATA_TARGETS[@]}"; do say "  $target"; done
  say "This includes the workspace, Electron profile, managed source/tools, the source-build"
  say "checkout, the whole ~/.flinttrade managed root (its top-level TOTP, journal, shortcuts,"
  say "quantity-freeze, action-centre, watchlist, flows and strategies state included), any"
  say "pre-workspace ~/.flinttrade data/archive/sandbox storage (including the encrypted"
  say "broker-credential vault) and any legacy desktop storage."
  say "To delete it too, re-run with --purge and confirm explicitly."
}

validate_common_receipt_target() {
  if [ ! -e "$RECEIPT_TARGET" ] || [ -L "$RECEIPT_TARGET" ]; then
    refuse_unproven_shell "$RECEIPT_TARGET" "the recorded shell target is missing or symbolic"
    return 1
  fi
  if [ ! -f "$RECEIPT_EXECUTABLE" ] || [ -L "$RECEIPT_EXECUTABLE" ] || [ ! -x "$RECEIPT_EXECUTABLE" ]; then
    refuse_unproven_shell "$RECEIPT_EXECUTABLE" "the recorded shell executable is not an ordinary executable"
    return 1
  fi
  if ! canonical_receipt_path_matches "$RECEIPT_TARGET" "$RECEIPT_TARGET" \
      || ! canonical_receipt_path_matches "$RECEIPT_EXECUTABLE" "$RECEIPT_EXECUTABLE"; then
    refuse_unproven_shell "$RECEIPT_TARGET" "the recorded shell path is not canonical"
    return 1
  fi
  verify_file_digest "$RECEIPT_EXECUTABLE" "$RECEIPT_EXECUTABLE_SHA256" || return 1
  verify_receipt_state_directory || return 1
}

verify_optional_ordinary_file() {
  local target="$1" label="$2"
  [ -e "$target" ] || [ -L "$target" ] || return 0
  if [ ! -f "$target" ] || [ -L "$target" ]; then
    refuse_unproven_shell "$target" "$label is not an ordinary file"
    return 1
  fi
  canonical_receipt_path_matches "$target" "$target" || {
    refuse_unproven_shell "$target" "$label is reached through a path alias"
    return 1
  }
}

validate_macos_receipt() {
  local plist bundle_id candidate canonical_candidate
  if [ "$RECEIPT_KIND" != "mac-app" ] || [ -n "$RECEIPT_WRAPPER$RECEIPT_DESKTOP$RECEIPT_ICON$RECEIPT_ICON_SHA256" ]; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the receipt is not a macOS application receipt"
    return 1
  fi
  case "$RECEIPT_TARGET" in /*/FlintTrade.app) ;; *)
    refuse_unproven_shell "$RECEIPT_TARGET" "the recorded macOS target is not FlintTrade.app"
    return 1
    ;;
  esac
  if [ "$RECEIPT_EXECUTABLE" != "$RECEIPT_TARGET/Contents/MacOS/FlintTrade" ] \
      || [ ! -d "$RECEIPT_TARGET" ]; then
    refuse_unproven_shell "$RECEIPT_TARGET" "the recorded macOS bundle layout is invalid"
    return 1
  fi
  validate_common_receipt_target || return 1
  plist="$RECEIPT_TARGET/Contents/Info.plist"
  if [ ! -f "$plist" ] || [ -L "$plist" ]; then
    refuse_unproven_shell "$RECEIPT_TARGET" "the bundle metadata is not an ordinary file"
    return 1
  fi
  bundle_id="$(/usr/bin/plutil -extract CFBundleIdentifier raw -o - "$plist" 2>/dev/null || true)"
  if [ "$bundle_id" != "$LEGACY_BUNDLE_ID" ]; then
    refuse_unproven_shell "$RECEIPT_TARGET" "the bundle identifier is not $LEGACY_BUNDLE_ID"
    return 1
  fi
  for candidate in "/Applications/FlintTrade.app" "$HOME/Applications/FlintTrade.app"; do
    [ -e "$candidate" ] || [ -L "$candidate" ] || continue
    if [ -L "$candidate" ]; then
      refuse_unproven_shell "$candidate" "a same-name application is a symbolic link"
      return 1
    fi
    canonical_candidate="$(canonical_existing_path "$candidate")" || {
      refuse_unproven_shell "$candidate" "the same-name application path cannot be canonicalised"
      return 1
    }
    if [ "$canonical_candidate" != "$RECEIPT_TARGET" ]; then
      refuse_unproven_shell "$candidate" "it is a same-name application not named by the install receipt"
      return 1
    fi
  done
}

expected_linux_wrapper() {
  printf '#!/bin/sh\nexec "%s" "$@"' "$RECEIPT_EXECUTABLE"
}

expected_linux_desktop_entry() {
  printf '%s\n' \
    '[Desktop Entry]' \
    'Name=FlintTrade' \
    "Exec=$RECEIPT_WRAPPER" \
    'Icon=flinttrade' \
    'Type=Application' \
    'Categories=Office;Finance;' \
    'Comment=Open-source self-hosted trading software' \
    'StartupWMClass=FlintTrade'
}

validate_linux_integration() {
  local expected_wrapper expected_desktop actual default_wrapper default_desktop default_icon home_canonical
  default_wrapper="$(canonical_existing_path "$HOME/.local/bin/flinttrade")" || {
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the recorded Linux wrapper parent cannot be canonicalised"
    return 1
  }
  default_desktop="$(canonical_existing_path "$HOME/.local/share/applications/flinttrade.desktop")" || {
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the recorded Linux desktop-entry parent cannot be canonicalised"
    return 1
  }
  if [ -d "$HOME/.local/share/icons/hicolor/128x128/apps" ]; then
    default_icon="$(canonical_existing_path "$HOME/.local/share/icons/hicolor/128x128/apps/flinttrade.png")" || {
      refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the recorded Linux icon parent cannot be canonicalised"
      return 1
    }
  else
    home_canonical="$(cd -P "$HOME" 2>/dev/null && pwd -P)" || {
      refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the current home cannot be canonicalised"
      return 1
    }
    default_icon="$home_canonical/.local/share/icons/hicolor/128x128/apps/flinttrade.png"
  fi
  if [ "$RECEIPT_WRAPPER" != "$default_wrapper" ] || [ "$RECEIPT_DESKTOP" != "$default_desktop" ]; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the Linux integration paths are not the installer-owned locations"
    return 1
  fi
  if [ -n "$RECEIPT_ICON" ] && [ "$RECEIPT_ICON" != "$default_icon" ]; then
    refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the Linux icon path is not the installer-owned location"
    return 1
  fi
  verify_optional_ordinary_file "$RECEIPT_WRAPPER" "the command wrapper" || return 1
  verify_optional_ordinary_file "$RECEIPT_DESKTOP" "the desktop entry" || return 1
  if [ -e "$RECEIPT_WRAPPER" ] && [ "$RECEIPT_WRAPPER" != "$RECEIPT_TARGET" ]; then
    [ -x "$RECEIPT_WRAPPER" ] || {
      refuse_unproven_shell "$RECEIPT_WRAPPER" "the command wrapper is not executable"
      return 1
    }
    expected_wrapper="$(expected_linux_wrapper)"
    actual="$(cat "$RECEIPT_WRAPPER")"
    if [ "$actual" != "$expected_wrapper" ]; then
      refuse_unproven_shell "$RECEIPT_WRAPPER" "the command wrapper content is not installer-owned"
      return 1
    fi
  fi
  if [ -e "$RECEIPT_DESKTOP" ]; then
    expected_desktop="$(expected_linux_desktop_entry)"
    actual="$(cat "$RECEIPT_DESKTOP")"
    if [ "$actual" != "$expected_desktop" ]; then
      refuse_unproven_shell "$RECEIPT_DESKTOP" "the desktop entry content is not installer-owned"
      return 1
    fi
  fi
  if [ -n "$RECEIPT_ICON" ]; then
    verify_optional_ordinary_file "$RECEIPT_ICON" "the application icon" || return 1
    [ ! -e "$RECEIPT_ICON" ] || verify_file_digest "$RECEIPT_ICON" "$RECEIPT_ICON_SHA256" || return 1
  elif [ -e "$default_icon" ] || [ -L "$default_icon" ]; then
    refuse_unproven_shell "$default_icon" "the same-name icon is not named by the install receipt"
    return 1
  fi
}

linux_path_is_recorded() {
  local candidate="$1"
  [ "$candidate" = "$RECEIPT_TARGET" ] || [ "$candidate" = "$RECEIPT_WRAPPER" ] \
    || [ "$candidate" = "$RECEIPT_DESKTOP" ] || { [ -n "$RECEIPT_ICON" ] && [ "$candidate" = "$RECEIPT_ICON" ]; }
}

validate_linux_receipt() {
  local candidate
  case "$RECEIPT_KIND" in
    linux-appimage)
      if [ "$RECEIPT_EXECUTABLE" != "$RECEIPT_TARGET" ] || [ ! -f "$RECEIPT_TARGET" ] \
          || [ ! -x "$RECEIPT_TARGET" ]; then
        refuse_unproven_shell "$RECEIPT_TARGET" "the direct AppImage receipt layout is invalid"
        return 1
      fi
      ;;
    linux-extracted)
      if [ "$RECEIPT_EXECUTABLE" != "$RECEIPT_TARGET/squashfs-root/AppRun" ] \
          || [ ! -d "$RECEIPT_TARGET" ]; then
        refuse_unproven_shell "$RECEIPT_TARGET" "the extracted AppImage receipt layout is invalid"
        return 1
      fi
      ;;
    *)
      refuse_unproven_shell "$SHELL_RECEIPT_PATH" "the receipt is not a supported Linux shell receipt"
      return 1
      ;;
  esac
  validate_common_receipt_target || return 1
  validate_linux_integration || return 1
  for candidate in \
      "$HOME/.local/bin/flinttrade" \
      "$HOME/.local/bin/flinttrade.AppImage" \
      "$HOME/.local/opt/flinttrade" \
      "$HOME/.local/share/applications/flinttrade.desktop" \
      "$HOME/.local/share/icons/hicolor/128x128/apps/flinttrade.png"; do
    [ -e "$candidate" ] || [ -L "$candidate" ] || continue
    if [ -L "$candidate" ]; then
      refuse_unproven_shell "$candidate" "a same-name Linux path is a symbolic link"
      return 1
    fi
    candidate="$(canonical_existing_path "$candidate" 2>/dev/null || printf '%s' "$candidate")"
    if ! linux_path_is_recorded "$candidate"; then
      refuse_unproven_shell "$candidate" "it is a same-name Linux path not named by the install receipt"
      return 1
    fi
  done
}

report_unreceipted_shell_paths() {
  local candidate found=0 candidates=()
  if [ "$OS" = "Darwin" ]; then
    # ~/.local/bin holds two different launchers, and both land at the same path
    # on macOS as on Linux: the desktop shell's own flinttrade wrapper, and the
    # web installer's flinttrade-web launcher (which earlier revisions wrote as
    # flinttrade). Leaving either out meant an uninstall silently kept a launcher
    # pointing at a source tree it had just deleted. A launcher its own receipt
    # proves is already gone by the time this report runs — remove_web_install
    # is called first — so anything still here is orphaned residue.
    candidates=(
      "/Applications/FlintTrade.app"
      "$HOME/Applications/FlintTrade.app"
      "$HOME/.local/bin/flinttrade"
      "$HOME/.local/bin/flinttrade-web"
      "$SHELL_RECEIPT_DIR"
    )
  else
    candidates=(
      "$HOME/.local/bin/flinttrade"
      "$HOME/.local/bin/flinttrade-web"
      "$HOME/.local/bin/flinttrade.AppImage"
      "$HOME/.local/opt/flinttrade"
      "$HOME/.local/share/applications/flinttrade.desktop"
      "$HOME/.local/share/icons/hicolor/128x128/apps/flinttrade.png"
      "$SHELL_RECEIPT_DIR"
    )
  fi
  for candidate in "${candidates[@]}"; do
    [ -e "$candidate" ] || [ -L "$candidate" ] || continue
    refuse_unproven_shell "$candidate" "no valid owner-local shell install receipt proves this path"
    found=1
  done
  return "$found"
}

remove_receipt_state() {
  remove_shell_path "$SHELL_LAUNCH_LOG" || return 1
  remove_shell_path "$SHELL_RECEIPT_PATH" || return 1
  if [ -d "$SHELL_RECEIPT_DIR" ]; then
    if [ "$DRY_RUN" = "1" ]; then
      say "[dry-run] would remove empty receipt directory $SHELL_RECEIPT_DIR"
    elif rmdir "$SHELL_RECEIPT_DIR" 2>/dev/null; then
      say "Removed $SHELL_RECEIPT_DIR"
      REMOVED_ANY=1
    else
      refuse_unproven_shell "$SHELL_RECEIPT_DIR" "the receipt directory changed during uninstall"
    fi
  fi
}

remove_shell_path() {
  local target="$1"
  remove_path "$target"
  [ "$DRY_RUN" = "1" ] && return 0
  if [ -e "$target" ] || [ -L "$target" ]; then
    # remove_path already emitted the filesystem error and set FAILED_ANY.
    return 1
  fi
}

uninstall_receipted_shell() {
  local receipt_status removal_failed=0
  if read_shell_receipt; then
    if [ "$OS" = "Darwin" ]; then
      validate_macos_receipt || return 1
    else
      validate_linux_receipt || return 1
    fi
    stop_proven_shell_processes || return 1
    remove_shell_path "$RECEIPT_TARGET" || removal_failed=1
    if [ "$OS" = "Linux" ]; then
      if [ "$RECEIPT_WRAPPER" != "$RECEIPT_TARGET" ]; then
        remove_shell_path "$RECEIPT_WRAPPER" || removal_failed=1
      fi
      remove_shell_path "$RECEIPT_DESKTOP" || removal_failed=1
      if [ -n "$RECEIPT_ICON" ]; then remove_shell_path "$RECEIPT_ICON" || removal_failed=1; fi
    fi
    [ "$removal_failed" = "0" ] || {
      say "Keeping $SHELL_RECEIPT_PATH because a proved shell path could not be removed."
      return 1
    }
    remove_receipt_state || return 1
    SHELL_REMOVED_ANY=1
    return 0
  else
    receipt_status=$?
  fi
  [ "$receipt_status" -ne 1 ] || report_unreceipted_shell_paths || true
  return 1
}

uninstall_macos() {
  ELECTRON_PROFILE="$HOME/Library/Application Support/flinttrade-shell"
  # Before the shell sweep, so a proved web launcher is already gone by the time
  # the unreceipted-path report looks at ~/.local/bin/flinttrade.
  remove_web_install
  uninstall_receipted_shell || true

  local legacy=(
    "$HOME/Library/Caches/$LEGACY_BUNDLE_ID"
    "$HOME/Library/HTTPStorages/$LEGACY_BUNDLE_ID"
    "$HOME/Library/HTTPStorages/$LEGACY_BUNDLE_ID.binarycookies"
    "$HOME/Library/Application Support/$LEGACY_BUNDLE_ID"
    "$HOME/Library/Saved Application State/$LEGACY_BUNDLE_ID.savedState"
    "$HOME/Library/Logs/$LEGACY_BUNDLE_ID"
    "$HOME/Library/Preferences/$LEGACY_BUNDLE_ID.plist"
    "$HOME/Library/WebKit/$LEGACY_BUNDLE_ID"
  )
  if [ "$PURGE" = "1" ]; then purge_all_data "${legacy[@]}"; else keep_notice "${legacy[@]}"; fi
  remove_retained_web_receipt
}

uninstall_linux() {
  ELECTRON_PROFILE="$HOME/.config/flinttrade-shell"
  # Before the shell sweep, so a proved web launcher is already gone by the time
  # the unreceipted-path report looks at ~/.local/bin/flinttrade.
  remove_web_install
  uninstall_receipted_shell || true
  if [ "$DRY_RUN" != "1" ] && command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
  fi

  local legacy=(
    "$HOME/.cache/$LEGACY_BUNDLE_ID"
    "$HOME/.config/$LEGACY_BUNDLE_ID"
    "$HOME/.local/share/$LEGACY_BUNDLE_ID"
  )
  if [ "$PURGE" = "1" ]; then purge_all_data "${legacy[@]}"; else keep_notice "${legacy[@]}"; fi
  remove_retained_web_receipt
}

case "$OS" in Darwin) uninstall_macos ;; Linux) uninstall_linux ;; esac

if [ "$DRY_RUN" = "1" ]; then
  say "Dry run complete — nothing was deleted."
elif [ "$FAILED_ANY" = "1" ]; then
  say "Uninstall finished with some paths left behind (see above)."
  exit 1
elif [ "$PURGED_DATA_ANY" = "1" ] && [ "$PURGE_COMPLETED" = "1" ]; then
  say "FlintTrade cleanup completed; explicitly confirmed data was purged."
elif [ "$REMOVED_ANY" = "1" ]; then
  # Removing only the one-line web install's launcher is not a shell uninstall,
  # and saying so would be untrue on a machine that never had the desktop shell.
  REMOVAL_SUBJECT="FlintTrade shell uninstalled cleanly"
  if [ "$SHELL_REMOVED_ANY" != "1" ] && [ "$WEB_REMOVED_ANY" = "1" ]; then
    REMOVAL_SUBJECT="FlintTrade web-app launcher removed cleanly"
  fi
  if [ "$DATA_RETAINED_ANY" = "1" ]; then
    say "$REMOVAL_SUBJECT; retained data remains available for reinstall."
  elif [ "$PURGE" = "1" ]; then
    say "$REMOVAL_SUBJECT; no recognised FlintTrade data was found to purge."
  else
    say "$REMOVAL_SUBJECT; no recognised FlintTrade data was found."
  fi
elif [ "$DATA_RETAINED_ANY" = "1" ]; then
  say "No FlintTrade shell was removed; retained data remains available for reinstall."
else
  say "Nothing to remove — the FlintTrade shell does not appear to be installed."
fi

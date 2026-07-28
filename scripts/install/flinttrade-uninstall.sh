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
FAILED_ANY=0
PURGE_COMPLETED=0
PURGED_DATA_ANY=0
DATA_FOUND_ANY=0
DATA_RETAINED_ANY=0
DATA_TARGETS=()
SHELL_RECEIPT_DIR="$HOME/.local/state/flinttrade"
SHELL_RECEIPT_PATH="$SHELL_RECEIPT_DIR/shell-install.receipt"
SHELL_LAUNCH_LOG="$SHELL_RECEIPT_DIR/desktop-launch.log"
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
             FLINTTRADE_SRC_DIR when it proves to be a FlintTrade checkout),
             the pre-workspace ~/.flinttrade data/archive/sandbox directories,
             and legacy desktop storage. Every resolved path is printed first.
             Irreversible after confirmation.
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
SRC_DIR_OVERRIDE="$(expand_tilde "${FLINTTRADE_SRC_DIR:-}")"
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
  # An FLINTTRADE_SRC_DIR override is only honoured when the directory still
  # proves itself a FlintTrade checkout; an arbitrary env var must never be
  # able to aim rm -rf at, say, ~/Documents.
  if [ -n "$SRC_DIR_OVERRIDE" ] && proven_source_checkout "$SRC_DIR_OVERRIDE"; then
    add_data_target "$SRC_DIR_OVERRIDE"
  fi
  add_data_target "$LEGACY_DATA_DIR"
  add_data_target "$LEGACY_ARCHIVE_DIR"
  add_data_target "$LEGACY_SANDBOX_DIR"
  add_data_target "$LEGACY_DITTO_VAULT"
  local candidate
  for candidate in "$@"; do add_data_target "$candidate"; done
  [ "${#DATA_TARGETS[@]}" -eq 0 ] || DATA_FOUND_ANY=1
}

proven_source_checkout() {
  local target="$1" marker
  [ -d "$target" ] && [ ! -L "$target" ] || return 1
  for marker in .git pnpm-lock.yaml uv.lock pyproject.toml; do
    [ -e "$target/$marker" ] || return 1
  done
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
  local target canonical home_canonical is_custom existing duplicate safe=()
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

    is_custom=0
    if [ "$target" = "${WORKSPACE_DIR%/}" ] && [ "${WORKSPACE_DIR%/}" != "$(default_workspace)" ]; then
      is_custom=1
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

  announce_purge_targets
  if [ "$ASSUME_YES" != "1" ]; then
    if [ ! -t 1 ] || [ ! -r /dev/tty ]; then
      say "Non-interactive session: FlintTrade data kept (pass --yes with --purge to confirm deletion)."
      DATA_RETAINED_ANY=1
      return 0
    fi
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
  say "source-build checkout, pre-workspace storage and legacy desktop data listed below:"
  for target in "${DATA_TARGETS[@]}"; do say "  $target"; done
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
  say "checkout, any pre-workspace ~/.flinttrade data/archive/sandbox storage (including the"
  say "encrypted broker-credential vault) and any legacy desktop storage."
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
    candidates=("/Applications/FlintTrade.app" "$HOME/Applications/FlintTrade.app" "$SHELL_RECEIPT_DIR")
  else
    candidates=(
      "$HOME/.local/bin/flinttrade"
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
    return 0
  else
    receipt_status=$?
  fi
  [ "$receipt_status" -ne 1 ] || report_unreceipted_shell_paths || true
  return 1
}

uninstall_macos() {
  ELECTRON_PROFILE="$HOME/Library/Application Support/flinttrade-shell"
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
}

uninstall_linux() {
  ELECTRON_PROFILE="$HOME/.config/flinttrade-shell"
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
  if [ "$DATA_RETAINED_ANY" = "1" ]; then
    say "FlintTrade shell uninstalled cleanly; retained data remains available for reinstall."
  elif [ "$PURGE" = "1" ]; then
    say "FlintTrade shell uninstalled cleanly; no recognised FlintTrade data was found to purge."
  else
    say "FlintTrade shell uninstalled cleanly; no recognised FlintTrade data was found."
  fi
elif [ "$DATA_RETAINED_ANY" = "1" ]; then
  say "No FlintTrade shell was removed; retained data remains available for reinstall."
else
  say "Nothing to remove — the FlintTrade shell does not appear to be installed."
fi

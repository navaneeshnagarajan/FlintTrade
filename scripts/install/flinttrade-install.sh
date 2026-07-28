#!/usr/bin/env bash
# FlintTrade Electron shell installer / updater (macOS + Linux)
#
# The default path installs the small published Electron shell. On first
# launch, that shell acquires and builds FlintTrade source with its bundled,
# checksum-pinned bootstrap. Contributors can instead package the Electron
# shell from a trusted source checkout with --build-from-source.
#
#   curl -fsSL https://flinttrade.vercel.app/install.sh | bash
#   curl -fsSL https://flinttrade.vercel.app/install.sh | bash -s -- --build-from-source

set -euo pipefail

REPO_SLUG="navaneeshnagarajan/FlintTrade"
REPO_URL="https://github.com/$REPO_SLUG.git"
GITHUB_API_BASE="https://api.github.com/repos/$REPO_SLUG"
RELEASE_DOWNLOAD_BASE="https://github.com/$REPO_SLUG/releases/download"
RELEASE_API_OVERRIDE="${FLINTTRADE_GITHUB_RELEASES_API:-}"
PINNED_PNPM_VERSION="9.15.0"
RELEASE_TAG_PATTERN='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$'
SRC_DIR="${FLINTTRADE_SRC_DIR:-$HOME/.flinttrade/source-build/FlintTrade}"
REF="${FLINTTRADE_REF:-}"
CHANNEL="${FLINTTRADE_CHANNEL:-beta}"
NO_LAUNCH="${FLINTTRADE_NO_LAUNCH:-0}"
BUILD_FROM_SOURCE="${FLINTTRADE_BUILD_FROM_SOURCE:-0}"
DRY_RUN="${FLINTTRADE_DRY_RUN:-0}"
DOWNLOADED_ASSET_PATH=""
DMG_MOUNT_DIR=""
RELEASE_ASSET_VERIFIED=0
UPDATE_ATTESTATION_BOUND=0
ACTIVE_SWAP_BACKUP=""
ACTIVE_SWAP_HAD_PREVIOUS=0
ACTIVE_SWAP_PENDING=0
ACTIVE_SWAP_TARGET=""
ACTIVE_SWAP_TRANSACTION_DIR=""
INSTALL_TRANSACTION_ACTIVE=0
INSTALL_TRANSACTION_TARGETS=("")
INSTALL_TRANSACTION_BACKUPS=("")
INSTALL_TRANSACTION_HAD_PREVIOUS=("")
DEFERRED_INSTALL_SIGNAL=0
SHELL_RECEIPT_DIR="$HOME/.local/state/flinttrade"
SHELL_RECEIPT_PATH="$SHELL_RECEIPT_DIR/shell-install.receipt"
INSTALLED_LINUX_ICON=""
LINUX_EXISTING_INSTALL_PROVED=0
TMP_DIRS=("")

say()  { printf '\033[1;36m[flinttrade]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[flinttrade]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[flinttrade]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1; }
valid_release_tag() { printf '%s\n' "$1" | grep -Eq "$RELEASE_TAG_PATTERN"; }

usage() {
  cat <<'USAGE'
FlintTrade Electron shell installer / updater (macOS + Linux)

Flags:
  --channel beta|stable  Release channel to install (default: beta)
  --ref <tag>            Install an exact release tag
  --build-from-source    Package the Electron shell from a trusted checkout
  --src <dir>            Checkout used by --build-from-source
  --update               Alias for the default install/update flow
  --yes                  Compatibility flag for the bundled updater
  --no-launch            Do not launch FlintTrade after installing
  --dry-run              Resolve and verify policy without installing
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --channel) CHANNEL="${2:?--channel needs beta or stable}"; shift 2 ;;
    --ref) REF="${2:?--ref needs a value}"; shift 2 ;;
    --build-from-source) BUILD_FROM_SOURCE=1; shift ;;
    --src) SRC_DIR="${2:?--src needs a value}"; shift 2 ;;
    --update) shift ;;
    --yes) shift ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown flag: $1 (see --help)" ;;
  esac
done

case "$CHANNEL" in
  beta|stable) ;;
  *) die "--channel must be beta or stable" ;;
esac
if [ -n "$REF" ] && ! valid_release_tag "$REF"; then
  die "--ref must be a semantic-version release tag such as v0.6.0-beta.13"
fi

detach_dmg_mount() {
  [ -n "$DMG_MOUNT_DIR" ] || return 0
  local target="$DMG_MOUNT_DIR" i
  for i in 1 2 3 4 5; do
    if hdiutil detach "$target" -quiet >/dev/null 2>&1; then
      DMG_MOUNT_DIR=""
      return 0
    fi
    sleep 1
  done
  hdiutil detach "$target" -force -quiet >/dev/null 2>&1 || true
  DMG_MOUNT_DIR=""
}

restore_interrupted_swap() {
  [ "$ACTIVE_SWAP_PENDING" = "1" ] || return 0
  if [ -e "$ACTIVE_SWAP_TARGET" ] || [ -L "$ACTIVE_SWAP_TARGET" ]; then
    rm -rf "$ACTIVE_SWAP_TARGET" 2>/dev/null \
      || return 1
  fi
  if [ "$ACTIVE_SWAP_HAD_PREVIOUS" = "1" ]; then
    [ -n "$ACTIVE_SWAP_BACKUP" ] && { [ -e "$ACTIVE_SWAP_BACKUP" ] || [ -L "$ACTIVE_SWAP_BACKUP" ]; } \
      || return 1
    mv "$ACTIVE_SWAP_BACKUP" "$ACTIVE_SWAP_TARGET" 2>/dev/null || return 1
  fi
  ACTIVE_SWAP_BACKUP=""
  ACTIVE_SWAP_HAD_PREVIOUS=0
  ACTIVE_SWAP_PENDING=0
  ACTIVE_SWAP_TARGET=""
  ACTIVE_SWAP_TRANSACTION_DIR=""
}

rollback_install_files() {
  [ "$INSTALL_TRANSACTION_ACTIVE" = "1" ] || return 0
  local index target backup had_previous failed=0
  for ((index=${#INSTALL_TRANSACTION_TARGETS[@]} - 1; index >= 1; index--)); do
    target="${INSTALL_TRANSACTION_TARGETS[$index]}"
    backup="${INSTALL_TRANSACTION_BACKUPS[$index]}"
    had_previous="${INSTALL_TRANSACTION_HAD_PREVIOUS[$index]}"
    if [ -e "$target" ] || [ -L "$target" ]; then
      rm -f "$target" 2>/dev/null || { failed=1; continue; }
    fi
    if [ "$had_previous" = "1" ]; then
      mv "$backup" "$target" 2>/dev/null || failed=1
    fi
  done
  [ "$failed" = "0" ] || return 1
  INSTALL_TRANSACTION_TARGETS=("")
  INSTALL_TRANSACTION_BACKUPS=("")
  INSTALL_TRANSACTION_HAD_PREVIOUS=("")
  INSTALL_TRANSACTION_ACTIVE=0
}

begin_install_transaction() {
  [ "$INSTALL_TRANSACTION_ACTIVE" = "0" ] \
    || die "An Electron shell install transaction is already active."
  INSTALL_TRANSACTION_TARGETS=("")
  INSTALL_TRANSACTION_BACKUPS=("")
  INSTALL_TRANSACTION_HAD_PREVIOUS=("")
  INSTALL_TRANSACTION_ACTIVE=1
}

defer_install_transaction_signals() {
  DEFERRED_INSTALL_SIGNAL=0
  trap 'DEFERRED_INSTALL_SIGNAL=129' HUP
  trap 'DEFERRED_INSTALL_SIGNAL=130' INT
  trap 'DEFERRED_INSTALL_SIGNAL=143' TERM
}

restore_install_signal_traps() {
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

publish_file_transactionally() {
  local staged="$1" target="$2" backup had_previous=0 preserve_status=0 deferred_signal
  [ "$INSTALL_TRANSACTION_ACTIVE" = "1" ] \
    || die "Refusing to publish an installer-owned file outside the shell transaction."
  [ -f "$staged" ] && [ ! -L "$staged" ] \
    || die "The staged installer-owned file is not ordinary: $staged"
  backup="$(mktemp "$(dirname "$target")/.flinttrade-rollback.XXXXXX")" \
    || die "Could not reserve rollback state for $target."
  rm -f "$backup" || die "Could not prepare rollback state for $target."
  TMP_DIRS+=("$backup")
  # A signal handled after the old target moves but before its rollback record
  # is complete would otherwise make cleanup delete the only backup. Defer the
  # exit (not the signal observation) across this tiny move+journal section.
  defer_install_transaction_signals
  if [ -e "$target" ] || [ -L "$target" ]; then
    if mv "$target" "$backup"; then
      had_previous=1
    else
      preserve_status=$?
      if { [ -e "$backup" ] || [ -L "$backup" ]; } \
          && [ ! -e "$target" ] && [ ! -L "$target" ]; then
        # The rename completed before the signal/failure status was observed;
        # journal the only surviving copy so cleanup can restore it.
        had_previous=1
        preserve_status=0
      fi
    fi
  fi
  if [ "$preserve_status" = "0" ]; then
    INSTALL_TRANSACTION_TARGETS+=("$target")
    INSTALL_TRANSACTION_BACKUPS+=("$backup")
    INSTALL_TRANSACTION_HAD_PREVIOUS+=("$had_previous")
  fi
  restore_install_signal_traps
  # Once normal exit traps are restored, a newly delivered signal exits
  # immediately; any signal observed while deferred is now stable to inspect.
  deferred_signal="$DEFERRED_INSTALL_SIGNAL"
  [ "$preserve_status" = "0" ] \
    || die "Could not preserve the previous installer-owned file at $target."
  [ "$deferred_signal" = "0" ] || exit "$deferred_signal"
  mv "$staged" "$target" || die "Could not publish the installer-owned file at $target."
}

commit_install_transaction() {
  [ "$INSTALL_TRANSACTION_ACTIVE" = "1" ] \
    || die "No Electron shell install transaction is active."
  INSTALL_TRANSACTION_TARGETS=("")
  INSTALL_TRANSACTION_BACKUPS=("")
  INSTALL_TRANSACTION_HAD_PREVIOUS=("")
  INSTALL_TRANSACTION_ACTIVE=0
  ACTIVE_SWAP_BACKUP=""
  ACTIVE_SWAP_HAD_PREVIOUS=0
  ACTIVE_SWAP_PENDING=0
  ACTIVE_SWAP_TARGET=""
  ACTIVE_SWAP_TRANSACTION_DIR=""
}

cleanup() {
  trap - HUP INT TERM
  detach_dmg_mount
  local dir protected="" backup keep
  if ! rollback_install_files; then
    warn "Interrupted shell integration publication could not fully restore its previous files."
  fi
  if ! restore_interrupted_swap; then
    protected="$ACTIVE_SWAP_TRANSACTION_DIR"
    warn "Interrupted shell replacement could not restore its backup; preserving it at $ACTIVE_SWAP_BACKUP."
  fi
  for dir in "${TMP_DIRS[@]}"; do
    [ -n "$protected" ] && [ "$dir" = "$protected" ] && continue
    keep=0
    if [ "$INSTALL_TRANSACTION_ACTIVE" = "1" ]; then
      for backup in "${INSTALL_TRANSACTION_BACKUPS[@]}"; do
        [ -n "$backup" ] && [ "$dir" = "$backup" ] && keep=1
      done
    fi
    [ "$keep" = "1" ] && continue
    [ -n "$dir" ] && rm -rf "$dir" 2>/dev/null || true
  done
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

lowercase() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

update_parent_identity() {
  local pid="$1"
  if [ -r "/proc/$pid/stat" ]; then
    # The start-time field is number 20 after Linux's parenthesised comm field.
    /usr/bin/sed 's/^[^)]*) //' "/proc/$pid/stat" 2>/dev/null | /usr/bin/awk '{print $20}'
    return 0
  fi
  /bin/ps -p "$pid" -o lstart= -o command= 2>/dev/null || true
}

wait_for_update_parent_exit() {
  local pid="$1" original_identity="$2"
  local timeout="${FLINTTRADE_UPDATE_PARENT_TIMEOUT_SECONDS:-3600}" elapsed=0 current_identity state
  case "$timeout" in ''|*[!0-9]*) die "The update-parent timeout must be an integer." ;; esac
  [ "$timeout" -ge 1 ] && [ "$timeout" -le 3900 ] \
    || die "The update-parent timeout must be between 1 and 3900 seconds."
  while kill -0 "$pid" 2>/dev/null; do
    state="$(/bin/ps -p "$pid" -o state= 2>/dev/null | /usr/bin/tr -d '[:space:]' || true)"
    case "$state" in Z*) return 0 ;; esac
    current_identity="$(update_parent_identity "$pid")"
    if [ -n "$original_identity" ] && [ -n "$current_identity" ] \
        && [ "$current_identity" != "$original_identity" ]; then
      # The exact parent exited and the OS reused its numeric PID.
      return 0
    fi
    if [ "$elapsed" -ge $((timeout * 5)) ]; then
      kill -0 "$pid" 2>/dev/null || return 0
      current_identity="$(update_parent_identity "$pid")"
      if [ -n "$original_identity" ] && [ -n "$current_identity" ] \
          && [ "$current_identity" != "$original_identity" ]; then
        return 0
      fi
      die "The verified shell installer timed out waiting for its exact Electron parent to exit; no installed shell was changed."
    fi
    /bin/sleep 0.2
    elapsed=$((elapsed + 1))
  done
}

signal_update_handoff() {
  [ "$DRY_RUN" = "1" ] && return 0
  local marker="${FLINTTRADE_UPDATE_HANDOFF:-}"
  [ -n "$marker" ] || return 0
  [ "$RELEASE_ASSET_VERIFIED" = "1" ] \
    || die "Refusing an updater handoff before release checksum verification."
  [ "$UPDATE_ATTESTATION_BOUND" = "1" ] \
    || die "Refusing an updater handoff before app-verified release attestation binding."
  [ -x /bin/ps ] && [ -x /bin/sleep ] && [ -x /usr/bin/tr ] \
    || die "The verified installer handoff cannot inspect the exact parent on this system."
  if [ -r "/proc/${FLINTTRADE_UPDATE_PARENT_PID:-}/stat" ]; then
    [ -x /usr/bin/sed ] && [ -x /usr/bin/awk ] \
      || die "The verified installer handoff cannot inspect the exact parent on this system."
  fi
  local parent_pid="${FLINTTRADE_UPDATE_PARENT_PID:-}" parent_identity
  case "$parent_pid" in ''|*[!0-9]*) die "The verified installer handoff requires an exact numeric parent PID." ;; esac
  [ "${#parent_pid}" -le 10 ] && [ "$parent_pid" -gt 1 ] \
    && [ "$parent_pid" -le 4294967295 ] && [ "$parent_pid" -ne "$$" ] \
    || die "The verified installer handoff parent PID is invalid."
  kill -0 "$parent_pid" 2>/dev/null \
    || die "The verified installer handoff parent is no longer running."
  parent_identity="$(update_parent_identity "$parent_pid")"
  [ -n "$parent_identity" ] \
    || die "The verified installer handoff could not bind the exact parent identity."
  (set -o noclobber; : > "$marker") 2>/dev/null \
    || die "Could not create the new verified installer handoff marker."
  say "Verified handoff marker created; waiting for the exact Electron parent to exit."
  wait_for_update_parent_exit "$parent_pid" "$parent_identity"
  say "The exact Electron parent exited; beginning transactional shell replacement."
}

replace_directory_transactionally() {
  local staged="$1" target="$2" transaction_dir="$3" required_executable="$4"
  local backup="$transaction_dir/previous" had_previous=0
  [ -d "$staged" ] && [ -x "$staged/$required_executable" ] \
    || { warn "The staged shell failed executable validation."; return 1; }
  if [ -e "$backup" ] || [ -L "$backup" ]; then
    warn "The shell replacement backup path already exists."
    return 1
  fi
  ACTIVE_SWAP_BACKUP="$backup"
  ACTIVE_SWAP_HAD_PREVIOUS=0
  ACTIVE_SWAP_PENDING=1
  ACTIVE_SWAP_TARGET="$target"
  ACTIVE_SWAP_TRANSACTION_DIR="$transaction_dir"
  if [ -e "$target" ] || [ -L "$target" ]; then
    ACTIVE_SWAP_HAD_PREVIOUS=1
    if ! mv "$target" "$backup"; then
      ACTIVE_SWAP_BACKUP=""
      ACTIVE_SWAP_HAD_PREVIOUS=0
      ACTIVE_SWAP_PENDING=0
      ACTIVE_SWAP_TARGET=""
      ACTIVE_SWAP_TRANSACTION_DIR=""
      warn "Could not preserve the currently installed shell before replacement."
      return 1
    fi
    had_previous=1
  fi
  if ! mv "$staged" "$target"; then
    if restore_interrupted_swap; then
      [ "$had_previous" = "1" ] \
        && warn "Shell replacement failed; restored the previous installed shell."
    else
      die "Shell replacement failed and the previous shell could not be restored from $backup."
    fi
    return 1
  fi
  if [ ! -x "$target/$required_executable" ]; then
    if restore_interrupted_swap; then
      [ "$had_previous" = "1" ] \
        && warn "Installed-shell validation failed; restored the previous installed shell."
    else
      die "Installed-shell validation failed and the previous shell could not be restored from $backup."
    fi
    return 1
  fi
}

ensure_shell_receipt_storage() {
  local current="${HOME%/}" component candidate name
  for component in .local state flinttrade; do
    current="$current/$component"
    [ ! -L "$current" ] || die "Refusing installer receipt storage through a symbolic-link path component: $current"
    if [ -e "$current" ]; then
      [ -d "$current" ] && [ -O "$current" ] \
        || die "Refusing installer receipt storage through a non-owner-local path component: $current"
    fi
  done
  mkdir -p "$SHELL_RECEIPT_DIR" \
    || die "Could not create the private Electron shell receipt directory."
  [ -d "$SHELL_RECEIPT_DIR" ] && [ ! -L "$SHELL_RECEIPT_DIR" ] && [ -O "$SHELL_RECEIPT_DIR" ] \
    || die "The Electron shell receipt directory is not an owner-local ordinary directory."
  chmod 0700 "$SHELL_RECEIPT_DIR" \
    || die "Could not make the Electron shell receipt directory private."
  for candidate in "$SHELL_RECEIPT_DIR"/* "$SHELL_RECEIPT_DIR"/.[!.]* "$SHELL_RECEIPT_DIR"/..?*; do
    [ -e "$candidate" ] || [ -L "$candidate" ] || continue
    name="$(basename "$candidate")"
    case "$name" in
      shell-install.receipt) ;;
      desktop-launch.log)
        [ -f "$candidate" ] && [ ! -L "$candidate" ] && [ -O "$candidate" ] \
          || die "The existing shell launch log is not an owner-local ordinary file: $candidate"
        ;;
      *) die "Refusing to mix the shell receipt with unrecognised state: $candidate" ;;
    esac
  done
}

canonical_installed_path() {
  local target="$1" parent
  if [ -d "$target" ]; then
    (cd -P "$target" 2>/dev/null && pwd -P)
    return
  fi
  parent="$(cd -P "$(dirname "$target")" 2>/dev/null && pwd -P)" || return 1
  printf '%s/%s' "${parent%/}" "$(basename "$target")"
}

receipt_sha256_file() {
  local target="$1"
  if need sha256sum; then
    sha256sum "$target" | awk '{print $1}'
  elif need shasum; then
    shasum -a 256 "$target" | awk '{print $1}'
  else
    die "Neither sha256sum nor shasum is available; refusing to create an unverifiable shell receipt."
  fi
}

receipt_safe_value() {
  case "$1" in
    *$'\n'*|*$'\r'*) die "Installer receipt values must be single-line paths." ;;
  esac
}

write_shell_receipt() {
  local kind="$1" target="$2" executable="$3" wrapper="$4" desktop="$5" icon="$6"
  local platform canonical_target canonical_executable canonical_wrapper="" canonical_desktop="" canonical_icon=""
  local executable_hash icon_hash="" receipt_tmp
  ensure_shell_receipt_storage
  [ -e "$target" ] && [ ! -L "$target" ] \
    || die "The installed Electron shell target is not an ordinary receipt candidate."
  [ -f "$executable" ] && [ ! -L "$executable" ] && [ -x "$executable" ] \
    || die "The installed Electron shell executable is not an ordinary receipt candidate."
  canonical_target="$(canonical_installed_path "$target")" \
    || die "Could not canonicalise the installed Electron shell target for its receipt."
  canonical_executable="$(canonical_installed_path "$executable")" \
    || die "Could not canonicalise the installed Electron shell executable for its receipt."
  if [ -n "$wrapper" ]; then
    [ -f "$wrapper" ] && [ ! -L "$wrapper" ] && [ -x "$wrapper" ] \
      || die "The installed FlintTrade command wrapper is not an ordinary receipt candidate."
    canonical_wrapper="$(canonical_installed_path "$wrapper")" \
      || die "Could not canonicalise the FlintTrade command wrapper for its receipt."
  fi
  if [ -n "$desktop" ]; then
    [ -f "$desktop" ] && [ ! -L "$desktop" ] \
      || die "The installed FlintTrade desktop entry is not an ordinary receipt candidate."
    canonical_desktop="$(canonical_installed_path "$desktop")" \
      || die "Could not canonicalise the FlintTrade desktop entry for its receipt."
  fi
  if [ -n "$icon" ]; then
    [ -f "$icon" ] && [ ! -L "$icon" ] \
      || die "The installed FlintTrade icon is not an ordinary receipt candidate."
    canonical_icon="$(canonical_installed_path "$icon")" \
      || die "Could not canonicalise the FlintTrade icon for its receipt."
    icon_hash="$(receipt_sha256_file "$canonical_icon")"
  fi
  platform="$(uname -s)"
  executable_hash="$(receipt_sha256_file "$canonical_executable")"
  for target in "$platform" "$kind" "$canonical_target" "$canonical_executable" "$canonical_wrapper" \
      "$canonical_desktop" "$canonical_icon" "$executable_hash" "$icon_hash"; do
    receipt_safe_value "$target"
  done
  receipt_tmp="$(mktemp "$SHELL_RECEIPT_DIR/.shell-install.receipt.XXXXXX")" \
    || die "Could not stage the Electron shell install receipt."
  TMP_DIRS+=("$receipt_tmp")
  chmod 0600 "$receipt_tmp"
  {
    printf '%s\n' \
      'format=flinttrade-electron-shell-v1' \
      "platform=$platform" \
      "kind=$kind" \
      "target=$canonical_target" \
      "executable=$canonical_executable" \
      "executable_sha256=$executable_hash" \
      "wrapper=$canonical_wrapper" \
      "desktop=$canonical_desktop" \
      "icon=$canonical_icon" \
      "icon_sha256=$icon_hash"
  } > "$receipt_tmp" || die "Could not write the Electron shell install receipt."
  publish_file_transactionally "$receipt_tmp" "$SHELL_RECEIPT_PATH"
}

ensure_owner_local_directory() {
  local target="${1%/}" current="${HOME%/}" relative component
  case "$target" in "$HOME"|"$HOME"/*) ;; *) die "Refusing an integration directory outside the current user's home: $target" ;; esac
  relative="${target#"${HOME%/}"/}"
  while [ -n "$relative" ]; do
    case "$relative" in
      */*) component="${relative%%/*}"; relative="${relative#*/}" ;;
      *) component="$relative"; relative="" ;;
    esac
    current="$current/$component"
    [ ! -L "$current" ] || die "Refusing an installer integration path through a symbolic link: $current"
    if [ -e "$current" ] && [ ! -d "$current" ]; then
      die "Refusing a non-directory installer integration parent: $current"
    fi
    if [ -d "$current" ] && [ ! -O "$current" ]; then
      die "Refusing a non-owner-local installer integration parent: $current"
    fi
  done
  mkdir -p "$target" || die "Could not create installer integration directory $target."
  [ -d "$target" ] && [ ! -L "$target" ] && [ -O "$target" ] \
    || die "Installer integration directory is not owner-local: $target"
}

prepare_integration_leaf() {
  local target="$1"
  ensure_owner_local_directory "$(dirname "$target")"
  if [ -L "$target" ] || { [ -e "$target" ] && [ ! -f "$target" ]; }; then
    die "Refusing to replace a non-ordinary installer integration path: $target"
  fi
}

preflight_linux_text_integration() {
  local target="$1" expected="$2"
  prepare_integration_leaf "$target"
  [ -e "$target" ] || return 0
  [ "$LINUX_EXISTING_INSTALL_PROVED" = "1" ] \
    || die "Refusing to replace an unproven same-name integration file: $target"
  [ "$(cat "$target")" = "$expected" ] \
    || die "Refusing to replace a modified FlintTrade integration file: $target"
}

preflight_linux_integrations() {
  local executable="$1" wrapper="$HOME/.local/bin/flinttrade"
  local desktop="$HOME/.local/share/applications/flinttrade.desktop"
  local icon="$HOME/.local/share/icons/hicolor/128x128/apps/flinttrade.png"
  preflight_linux_text_integration "$wrapper" "$(linux_wrapper_content "$executable")"
  preflight_linux_text_integration "$desktop" "$(linux_desktop_content "$wrapper")"
  prepare_integration_leaf "$icon"
  if [ -e "$icon" ] && [ "$LINUX_EXISTING_INSTALL_PROVED" != "1" ]; then
    die "Refusing to replace an unproven same-name integration file: $icon"
  fi
}

atomic_write_integration_file() {
  local target="$1" mode="$2" content="$3" tmp
  prepare_integration_leaf "$target"
  if [ -e "$target" ]; then
    [ "$LINUX_EXISTING_INSTALL_PROVED" = "1" ] \
      || die "Refusing to replace an unproven same-name integration file: $target"
    [ "$(cat "$target")" = "$content" ] \
      || die "Refusing to replace a modified FlintTrade integration file: $target"
  fi
  tmp="$(mktemp "$(dirname "$target")/.flinttrade-integration.XXXXXX")" \
    || die "Could not stage installer integration at $target."
  TMP_DIRS+=("$tmp")
  printf '%s\n' "$content" > "$tmp"
  chmod "$mode" "$tmp"
  publish_file_transactionally "$tmp" "$target"
}

atomic_copy_integration_file() {
  local source="$1" target="$2" tmp
  prepare_integration_leaf "$target"
  if [ -e "$target" ] && [ "$LINUX_EXISTING_INSTALL_PROVED" != "1" ]; then
    die "Refusing to replace an unproven same-name integration file: $target"
  fi
  tmp="$(mktemp "$(dirname "$target")/.flinttrade-integration.XXXXXX")" \
    || die "Could not stage installer integration at $target."
  TMP_DIRS+=("$tmp")
  cp "$source" "$tmp" || die "Could not stage the FlintTrade application icon."
  chmod 0644 "$tmp"
  publish_file_transactionally "$tmp" "$target"
}

linux_wrapper_content() {
  printf '#!/bin/sh\nexec "%s" "$@"' "$1"
}

linux_desktop_content() {
  printf '%s\n' \
    '[Desktop Entry]' \
    'Name=FlintTrade' \
    "Exec=$1" \
    'Icon=flinttrade' \
    'Type=Application' \
    'Categories=Office;Finance;' \
    'Comment=Open-source self-hosted trading software' \
    'StartupWMClass=FlintTrade'
}

receipt_proves_existing_linux_target() {
  local kind="$1" target="$2" executable="$3"
  local line1 line2 line3 line4 line5 line6 line7 line8 line9 line10 extra actual mode
  [ -d "$SHELL_RECEIPT_DIR" ] && [ ! -L "$SHELL_RECEIPT_DIR" ] && [ -O "$SHELL_RECEIPT_DIR" ] || return 1
  mode="$(/usr/bin/stat -c '%a' "$SHELL_RECEIPT_DIR" 2>/dev/null \
    || /usr/bin/stat -f '%Lp' "$SHELL_RECEIPT_DIR" 2>/dev/null)" || return 1
  [ "$mode" = "700" ] || return 1
  [ -f "$SHELL_RECEIPT_PATH" ] && [ ! -L "$SHELL_RECEIPT_PATH" ] && [ -O "$SHELL_RECEIPT_PATH" ] || return 1
  mode="$(/usr/bin/stat -c '%a' "$SHELL_RECEIPT_PATH" 2>/dev/null \
    || /usr/bin/stat -f '%Lp' "$SHELL_RECEIPT_PATH" 2>/dev/null)" || return 1
  [ "$mode" = "600" ] || return 1
  {
    IFS= read -r line1 && IFS= read -r line2 && IFS= read -r line3 \
      && IFS= read -r line4 && IFS= read -r line5 && IFS= read -r line6 \
      && IFS= read -r line7 && IFS= read -r line8 && IFS= read -r line9 \
      && IFS= read -r line10 && ! IFS= read -r extra
  } < "$SHELL_RECEIPT_PATH" || return 1
  [ "$line1" = "format=flinttrade-electron-shell-v1" ] \
    && [ "$line2" = "platform=Linux" ] \
    && [ "$line3" = "kind=$kind" ] \
    && [ "$line4" = "target=$target" ] \
    && [ "$line5" = "executable=$executable" ] \
    || return 1
  case "$line6" in executable_sha256=*) ;; *) return 1 ;; esac
  case "$line7" in wrapper=*) ;; *) return 1 ;; esac
  case "$line8" in desktop=*) ;; *) return 1 ;; esac
  case "$line9" in icon=*) ;; *) return 1 ;; esac
  case "$line10" in icon_sha256=*) ;; *) return 1 ;; esac
  [ "${#line6}" -eq 82 ] || return 1
  actual="$(receipt_sha256_file "$executable")" || return 1
  [ "$(lowercase "$actual")" = "$(lowercase "${line6#executable_sha256=}")" ]
}

legacy_linux_integration_proves_target() {
  local executable="$1" wrapper="$HOME/.local/bin/flinttrade" desktop="$HOME/.local/share/applications/flinttrade.desktop"
  [ -f "$wrapper" ] && [ ! -L "$wrapper" ] && [ -x "$wrapper" ] \
    && [ -f "$desktop" ] && [ ! -L "$desktop" ] \
    && [ "$(cat "$wrapper")" = "$(linux_wrapper_content "$executable")" ] \
    && [ "$(cat "$desktop")" = "$(linux_desktop_content "$wrapper")" ]
}

assert_existing_linux_target_owned() {
  local kind="$1" target="$2" executable="$3" update_mode="$4" canonical_target canonical_executable
  LINUX_EXISTING_INSTALL_PROVED=0
  [ -e "$target" ] || [ -L "$target" ] || return 0
  [ ! -L "$target" ] || die "Refusing to replace a symbolic-link shell target: $target"
  [ -f "$executable" ] && [ ! -L "$executable" ] && [ -x "$executable" ] \
    || die "Refusing to replace an unproven same-name shell target: $target"
  canonical_target="$(canonical_installed_path "$target")" || die "Could not canonicalise existing shell target $target."
  canonical_executable="$(canonical_installed_path "$executable")" || die "Could not canonicalise existing shell executable $executable."
  if [ "$update_mode" != "fresh" ] \
      || receipt_proves_existing_linux_target "$kind" "$canonical_target" "$canonical_executable" \
      || legacy_linux_integration_proves_target "$canonical_executable"; then
    LINUX_EXISTING_INSTALL_PROVED=1
    return 0
  fi
  die "Refusing to replace an unrelated same-name shell target without a valid receipt or legacy FlintTrade integration proof: $target"
}

assert_existing_macos_target_owned() {
  local target="$1" update_mode="$2" bundle_id
  [ -e "$target" ] || [ -L "$target" ] || return 0
  [ ! -L "$target" ] && [ -d "$target" ] \
    || die "Refusing to replace a non-ordinary same-name macOS application: $target"
  [ "$update_mode" != "fresh" ] && return 0
  [ -f "$target/Contents/Info.plist" ] && [ ! -L "$target/Contents/Info.plist" ] \
    && [ -f "$target/Contents/MacOS/FlintTrade" ] && [ ! -L "$target/Contents/MacOS/FlintTrade" ] \
    && [ -x "$target/Contents/MacOS/FlintTrade" ] \
    || die "Refusing to replace an unproven same-name macOS application: $target"
  bundle_id="$(/usr/bin/plutil -extract CFBundleIdentifier raw -o - "$target/Contents/Info.plist" 2>/dev/null || true)"
  [ "$bundle_id" = "com.flinttrade.app" ] \
    || die "Refusing to replace a same-name macOS application with a different bundle identity: $target"
}

assert_no_other_linux_shell_target() {
  local selected="$1" candidate canonical_selected canonical_candidate
  canonical_selected="$(canonical_installed_path "$selected")" \
    || die "Could not canonicalise the selected Linux shell target."
  for candidate in "$HOME/.local/bin/flinttrade.AppImage" "$HOME/.local/opt/flinttrade"; do
    [ -e "$candidate" ] || [ -L "$candidate" ] || continue
    [ ! -L "$candidate" ] \
      || die "Refusing to install while a symbolic-link same-name Linux shell target is present: $candidate"
    canonical_candidate="$(canonical_installed_path "$candidate" 2>/dev/null || printf '%s' "$candidate")"
    [ "$canonical_candidate" = "$canonical_selected" ] \
      || die "Refusing to install while another same-name Linux shell target is present: $candidate"
  done
}

assert_no_other_macos_shell_target() {
  local selected="$1" candidate canonical_selected canonical_candidate
  canonical_selected="$(canonical_installed_path "$selected")" \
    || die "Could not canonicalise the selected macOS shell target."
  for candidate in "/Applications/FlintTrade.app" "$HOME/Applications/FlintTrade.app"; do
    [ -e "$candidate" ] || [ -L "$candidate" ] || continue
    [ ! -L "$candidate" ] \
      || die "Refusing to install while a symbolic-link same-name macOS application is present: $candidate"
    canonical_candidate="$(canonical_installed_path "$candidate" 2>/dev/null || printf '%s' "$candidate")"
    [ "$canonical_candidate" = "$canonical_selected" ] \
      || die "Refusing to install while another same-name macOS application is present: $candidate"
  done
}

pnpm_run() {
  if need corepack; then
    corepack pnpm "$@"
    return $?
  fi
  if need pnpm && [ "$(pnpm --version 2>/dev/null)" = "$PINNED_PNPM_VERSION" ]; then
    pnpm "$@"
    return $?
  fi
  if need npx; then
    npx --yes "pnpm@$PINNED_PNPM_VERSION" "$@"
    return $?
  fi
  return 127
}

resolve_latest_tag() {
  sed 's/-/~/' | sort -V | tail -1 | sed 's/~/-/'
}

filter_release_tags_for_channel() {
  local tag without_build prerelease
  while IFS= read -r tag; do
    [ -n "$tag" ] || continue
    without_build="${tag%%+*}"
    prerelease=""
    case "$without_build" in *-*) prerelease="${without_build#*-}" ;; esac
    if [ "$CHANNEL" = "stable" ]; then
      [ -z "$prerelease" ] && printf '%s\n' "$tag"
    else
      case "$prerelease" in ""|beta|beta.*) printf '%s\n' "$tag" ;; esac
    fi
  done
}

normalised_arch() {
  case "$(uname -m)" in
    arm64|aarch64) printf 'arm64' ;;
    x86_64|amd64) printf 'x64' ;;
    *) die "Unsupported CPU architecture: $(uname -m)" ;;
  esac
}

release_api_url() {
  if [ -n "$RELEASE_API_OVERRIDE" ]; then
    case "$RELEASE_API_OVERRIDE" in
      https://*) printf '%s' "$RELEASE_API_OVERRIDE" ;;
      file://*)
        [ "${FLINTTRADE_ALLOW_LOCAL_ASSET:-0}" = "1" ] \
          || die "Refusing non-HTTPS GitHub release API override"
        printf '%s' "$RELEASE_API_OVERRIDE"
        ;;
      *) die "Refusing non-HTTPS GitHub release API override" ;;
    esac
  elif [ -n "$REF" ]; then
    printf '%s/releases/tags/%s' "$GITHUB_API_BASE" "$REF"
  else
    printf '%s/releases?per_page=100' "$GITHUB_API_BASE"
  fi
}

# Select one complete top-level release object without depending on jq or a
# system Python. The scanner tracks JSON strings and nested braces, so braces
# in release notes cannot truncate the object. GitHub returns newest first.
select_release_object() {
  local wanted="$1" required_suffix="$2"
  LC_ALL=C fold -w 8192 | awk -v wanted="$wanted" -v required_suffix="$required_suffix" \
      -v download_base="$RELEASE_DOWNLOAD_BASE" '
    function occurrences(text, marker, count, offset) {
      count = 0
      while ((offset = index(text, marker)) > 0) {
        count++
        text = substr(text, offset + length(marker))
      }
      return count
    }
    BEGIN { depth = 0; started = 0; quoted = 0; escaped = 0; object = "" }
    {
      chunk = $0
      segment_start = started ? 1 : 0
      for (i = 1; i <= length(chunk); i++) {
        c = substr(chunk, i, 1)
        if (!started) {
          if (c == "{") { started = 1; depth = 1; segment_start = i }
          continue
        }
        if (quoted) {
          if (escaped) escaped = 0
          else if (c == "\\") escaped = 1
          else if (c == "\"") quoted = 0
          continue
        }
        if (c == "\"") quoted = 1
        else if (c == "{") depth++
        else if (c == "}") {
          depth--
          if (depth == 0) {
            object = object substr(chunk, segment_start, i - segment_start + 1)
            compact = object
            gsub(/[[:space:]]/, "", compact)
            tag_marker = "\"tag_name\":\""
            tag_start = index(compact, tag_marker)
            tag = ""
            if (tag_start) {
              tag_rest = substr(compact, tag_start + length(tag_marker))
              tag_finish = index(tag_rest, "\"")
              if (tag_finish) tag = substr(tag_rest, 1, tag_finish - 1)
            }
            metadata_prerelease = index(compact, "\"prerelease\":true") > 0
            metadata_stable = index(compact, "\"prerelease\":false") > 0
            tag_prerelease = tag ~ /^v[^+]*-/
            semver = tag ~ /^v(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)(-[0-9A-Za-z-]+([.][0-9A-Za-z-]+)*)?([+][0-9A-Za-z-]+([.][0-9A-Za-z-]+)*)?$/
            acceptable = index(compact, "\"draft\":false") > 0 && semver
            acceptable = acceptable && ((metadata_prerelease && tag_prerelease) || (metadata_stable && !tag_prerelease))
            if (wanted == "stable") acceptable = acceptable && !tag_prerelease
            else if (wanted == "beta") acceptable = acceptable && (!tag_prerelease || tag ~ /-beta(\.|\+|$)/)
            if (acceptable && wanted != "exact") {
              version = tag
              sub(/^v/, "", version)
              asset_name = "FlintTrade-" version "-" required_suffix
              asset_url = download_base "/" tag "/" asset_name
              sums_url = download_base "/" tag "/SHA256SUMS.txt"
              acceptable = occurrences(compact, "\"name\":\"" asset_name "\"") == 1
              acceptable = acceptable && occurrences(compact, "\"name\":\"SHA256SUMS.txt\"") == 1
              acceptable = acceptable && occurrences(compact, "\"browser_download_url\":\"" asset_url "\"") == 1
              acceptable = acceptable && occurrences(compact, "\"browser_download_url\":\"" sums_url "\"") == 1
            }
            if (acceptable && selected == "") selected = object
            started = 0; quoted = 0; escaped = 0; object = ""; segment_start = 0
          }
        }
      }
      if (started && segment_start > 0) object = object substr(chunk, segment_start)
    }
    END { if (selected != "") printf "%s", selected }
  '
}

json_string_field() {
  local json="$1" field="$2"
  printf '%s' "$json" | tr -d '\n\r\t ' | awk -v field="$field" '
    {
      marker = "\"" field "\":\""
      start = index($0, marker)
      if (!start) exit 1
      rest = substr($0, start + length(marker))
      finish = index(rest, "\"")
      if (!finish) exit 1
      print substr(rest, 1, finish - 1)
    }
  '
}

asset_url_named() {
  local json="$1" name="$2"
  printf '%s' "$json" | tr -d '\n\r\t ' | awk -v name="$name" '
    {
      name_marker = "\"name\":\"" name "\""
      remaining = $0
      count = 0
      while ((name_start = index(remaining, name_marker)) > 0) {
        count++
        if (count == 1) after_name = substr(remaining, name_start + length(name_marker))
        remaining = substr(remaining, name_start + length(name_marker))
      }
      if (count != 1) exit 1
      marker = "\"browser_download_url\":\""
      start = index(after_name, marker)
      if (!start) exit 1
      rest = substr(after_name, start + length(marker))
      finish = index(rest, "\"")
      if (!finish) exit 1
      print substr(rest, 1, finish - 1)
    }
  '
}

trusted_release_asset_url() {
  local url="$1" tag="$2" name="$3"
  [ "$url" = "$RELEASE_DOWNLOAD_BASE/$tag/$name" ] \
    || die "Refusing asset URL outside the selected official release: $url"
}

checksum_for_asset() {
  local sums="$1" name="$2" hash
  hash="$(printf '%s\n' "$sums" | awk -v name="$name" '
    ($2 == name || $2 == "*" name) {
      count++
      value = $1
    }
    END {
      if (count != 1) exit 1
      print value
    }
  ')" || die "SHA256SUMS.txt does not contain exactly one checksum for $name"
  [ "${#hash}" -eq 64 ] || die "SHA256SUMS.txt has an invalid checksum for $name"
  case "$hash" in
    *[!0-9A-Fa-f]*) die "SHA256SUMS.txt has an invalid checksum for $name" ;;
  esac
  printf '%s' "$hash"
}

verify_sha256() {
  local file="$1" expected="$2" actual
  if need sha256sum; then
    actual="$(sha256sum "$file" | awk '{print $1}')"
  elif need shasum; then
    actual="$(shasum -a 256 "$file" | awk '{print $1}')"
  else
    die "Neither sha256sum nor shasum is available; refusing an unverified installer."
  fi
  if [ "$(lowercase "$actual")" != "$(lowercase "$expected")" ]; then
    die "Checksum mismatch for $(basename "$file"). Expected $expected, got $actual."
  fi
  say "Verified SHA-256 checksum from the selected release."
}

download_release_asset() {
  need curl || die "curl is required to download the FlintTrade installer."
  local os_name="$1" arch="$2" extension="$3"
  local api_url response wanted release tag version asset_name asset_url sums_name sums_url sums expected
  api_url="$(release_api_url)"
  say "Resolving FlintTrade shell release from GitHub ($api_url)..."
  response="$(curl -fsSL -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' "$api_url")" \
    || die "Could not query the official GitHub release API."

  wanted="exact"
  if [ -z "$REF" ]; then
    wanted="$CHANNEL"
  fi
  release="$(printf '%s' "$response" | select_release_object "$wanted" "$os_name-$arch.$extension")"
  if [ -z "$release" ]; then
    if [ "$wanted" = "exact" ]; then
      die "No non-draft release was found for exact ref $REF."
    fi
    die "No complete non-draft $CHANNEL release was found for $os_name-$arch."
  fi
  tag="$(json_string_field "$release" tag_name)" || die "GitHub release metadata has no tag_name."
  valid_release_tag "$tag" || die "GitHub returned an invalid release tag."
  [ -z "$REF" ] || [ "$tag" = "$REF" ] || die "GitHub returned tag $tag while $REF was requested."
  version="${tag#v}"

  asset_name="FlintTrade-$version-$os_name-$arch.$extension"
  sums_name="SHA256SUMS.txt"
  asset_url="$(asset_url_named "$release" "$asset_name" || true)"
  sums_url="$(asset_url_named "$release" "$sums_name" || true)"
  [ -n "$asset_url" ] || die "Release $tag has no required $asset_name shell installer."
  [ -n "$sums_url" ] || die "Release $tag has no required SHA256SUMS.txt asset."
  trusted_release_asset_url "$asset_url" "$tag" "$asset_name"
  trusted_release_asset_url "$sums_url" "$tag" "$sums_name"

  sums="$(curl -fsSL "$sums_url")" || die "Could not download SHA256SUMS.txt from release $tag."
  expected="$(checksum_for_asset "$sums" "$asset_name")"
  if [ -n "${FLINTTRADE_UPDATE_HANDOFF:-}" ]; then
    local attested_name="${FLINTTRADE_UPDATE_ASSET_NAME:-}"
    local attested_hash="${FLINTTRADE_UPDATE_ASSET_SHA256:-}"
    [ "$attested_name" = "$asset_name" ] \
      || die "The selected installer name did not match the app-verified release attestation."
    [ "${#attested_hash}" -eq 64 ] \
      || die "The app-verified release attestation digest was invalid."
    case "$attested_hash" in
      *[!0-9a-f]*) die "The app-verified release attestation digest was invalid." ;;
    esac
    [ "$(lowercase "$expected")" = "$attested_hash" ] \
      || die "SHA256SUMS.txt did not match the app-verified release attestation digest."
    expected="$attested_hash"
    UPDATE_ATTESTATION_BOUND=1
  fi
  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would download $asset_name"
    say "DRY-RUN: $asset_url"
    say "DRY-RUN: would verify sha256 $expected from $sums_url"
    DOWNLOADED_ASSET_PATH="/tmp/$asset_name"
    return 0
  fi

  local tmp_dir dest
  tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/flinttrade.XXXXXX")"
  TMP_DIRS+=("$tmp_dir")
  dest="$tmp_dir/$asset_name"
  say "Downloading $asset_name..."
  curl -fL "$asset_url" -o "$dest"
  verify_sha256 "$dest" "$expected"
  RELEASE_ASSET_VERIFIED=1
  DOWNLOADED_ASSET_PATH="$dest"
}

install_macos_dmg() {
  local dmg="$1" mount_dir="${TMPDIR:-/tmp}/flinttrade-dmg-$$" dest="/Applications"
  local target_app requested_target canonical_parent update_mode="fresh"
  if [ -n "${FLINTTRADE_UPDATE_HANDOFF:-}" ] && [ "$DRY_RUN" != "1" ]; then
    requested_target="${FLINTTRADE_UPDATE_MACOS_APP_BUNDLE:-}"
    case "$requested_target" in
      /*/FlintTrade.app) ;;
      *) die "The macOS updater requires the exact absolute FlintTrade.app bundle path." ;;
    esac
    case "$requested_target" in
      */AppTranslocation/*) die "Refusing to update a translocated macOS app bundle." ;;
    esac
    [ -d "$requested_target" ] && [ ! -L "$requested_target" ] \
      && [ -x "$requested_target/Contents/MacOS/FlintTrade" ] \
      || die "The macOS updater target is not an ordinary installed FlintTrade.app bundle."
    canonical_parent="$(cd -P "$(dirname "$requested_target")" 2>/dev/null && pwd)" \
      || die "The macOS updater target parent cannot be canonicalised."
    target_app="$canonical_parent/FlintTrade.app"
    [ "$target_app" = "$requested_target" ] \
      || die "The macOS updater target must already be canonical and free of symlink aliases."
    [ -w "$requested_target" ] && [ -w "$canonical_parent" ] \
      || die "The exact running macOS app bundle is not writable; no update was signalled."
    dest="$canonical_parent"
    update_mode="mac-update"
  else
    [ -w "$dest" ] || dest="$HOME/Applications"
    target_app="$dest/FlintTrade.app"
  fi
  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would mount $dmg and install FlintTrade.app at $target_app"
    return 0
  fi

  ensure_shell_receipt_storage
  case "$dest" in
    "$HOME"|"$HOME"/*) ensure_owner_local_directory "$dest" ;;
    *) [ -d "$dest" ] && [ ! -L "$dest" ] || die "The macOS application destination is not an ordinary directory: $dest" ;;
  esac
  assert_existing_macos_target_owned "$target_app" "$update_mode"
  assert_no_other_macos_shell_target "$target_app"
  mkdir -p "$mount_dir"
  TMP_DIRS+=("$mount_dir")
  local attach_status=0
  set +e +o pipefail
  yes 2>/dev/null | hdiutil attach "$dmg" -nobrowse -readonly -mountpoint "$mount_dir" >/dev/null 2>&1
  attach_status=${PIPESTATUS[1]}
  set -e -o pipefail
  [ "$attach_status" -eq 0 ] || die "Could not mount $dmg. Download and open it manually."
  DMG_MOUNT_DIR="$mount_dir"

  local app_path transaction_dir staged_app
  app_path="$(find "$mount_dir" -maxdepth 2 -name 'FlintTrade.app' -type d | head -1)"
  [ -n "$app_path" ] || die "No FlintTrade.app found in $dmg"
  transaction_dir="$(mktemp -d "$dest/.flinttrade-install.XXXXXX")" \
    || die "Could not create an adjacent macOS shell staging directory."
  TMP_DIRS+=("$transaction_dir")
  staged_app="$transaction_dir/FlintTrade.app"
  if ! ditto "$app_path" "$staged_app"; then
    die "Could not stage FlintTrade.app from the verified disk image."
  fi
  [ -f "$staged_app/Contents/Info.plist" ] \
    && [ -x "$staged_app/Contents/MacOS/FlintTrade" ] \
    || die "The staged macOS shell is missing its expected bundle metadata or executable."
  signal_update_handoff
  begin_install_transaction
  say "Installing FlintTrade.app at $target_app..."
  replace_directory_transactionally \
    "$staged_app" "$target_app" "$transaction_dir" "Contents/MacOS/FlintTrade" \
    || die "Could not transactionally replace FlintTrade.app; the previous shell was preserved when present."
  write_shell_receipt \
    "mac-app" "$target_app" "$target_app/Contents/MacOS/FlintTrade" "" "" ""
  commit_install_transaction
  detach_dmg_mount
  rm -rf "$mount_dir"
  say "Installed: $target_app"
  if [ "$NO_LAUNCH" != "1" ]; then open "$target_app"; fi
}

linux_fuse_available() {
  [ -e /dev/fuse ] || return 1
  need fusermount || need fusermount3 || return 1
  if need ldconfig && ldconfig -p 2>/dev/null | grep -q 'libfuse\.so\.2'; then return 0; fi
  local lib
  for lib in /usr/lib/*/libfuse.so.2 /usr/lib/libfuse.so.2 /usr/lib64/libfuse.so.2; do
    [ -e "$lib" ] && return 0
  done
  return 1
}

install_linux_launcher_extras() {
  local exec_target="$1" dest_bin="$2" icon_source="$3"
  local icon_dir="$HOME/.local/share/icons/hicolor/128x128/apps"
  INSTALLED_LINUX_ICON=""
  if [ -n "$icon_source" ] && [ -f "$icon_source" ]; then
    atomic_copy_integration_file "$icon_source" "$icon_dir/flinttrade.png"
    INSTALLED_LINUX_ICON="$icon_dir/flinttrade.png"
  elif [ -f "$icon_dir/flinttrade.png" ] && [ ! -L "$icon_dir/flinttrade.png" ] \
      && [ "$LINUX_EXISTING_INSTALL_PROVED" = "1" ]; then
    INSTALLED_LINUX_ICON="$icon_dir/flinttrade.png"
  fi
  if [ "$exec_target" != "$dest_bin/flinttrade" ]; then
    atomic_write_integration_file \
      "$dest_bin/flinttrade" 0755 "$(linux_wrapper_content "$exec_target")"
  fi
  case ":$PATH:" in
    *":$dest_bin:"*) ;;
    *) warn "$dest_bin is not on PATH; add it to run 'flinttrade' from a shell." ;;
  esac
}

launch_linux_app() {
  local executable="$1" log_dir="$HOME/.local/state/flinttrade" log pid
  mkdir -p "$log_dir"
  log="$log_dir/desktop-launch.log"
  nohup "$executable" > "$log" 2>&1 &
  pid=$!
  sleep 3
  if ! kill -0 "$pid" 2>/dev/null; then
    tail -20 "$log" >&2 || true
    die "FlintTrade exited immediately; full log: $log"
  fi
  say "FlintTrade is starting. First launch builds the verified local source checkout (log: $log)."
}

install_linux_appimage_extracted() {
  local appimage="$1" dest_bin="$2" desktop_dir="$3"
  local opt_dir="${4:-$HOME/.local/opt/flinttrade}"
  local update_mode="${5:-fresh}"
  local opt_parent transaction_dir staged wrapper icon
  say "FUSE is unavailable; using the AppImage self-extraction install."
  opt_parent="$(dirname "$opt_dir")"
  if [ "$update_mode" = "fresh" ]; then
    ensure_owner_local_directory "$opt_parent"
  fi
  transaction_dir="$(mktemp -d "$opt_parent/.flinttrade-install.XXXXXX")" \
    || die "Could not create an adjacent extracted-shell staging directory."
  TMP_DIRS+=("$transaction_dir")
  staged="$transaction_dir/new"
  mkdir -p "$staged"
  if ! (cd "$staged" && "$appimage" --appimage-extract >/dev/null 2>&1) \
      || [ ! -x "$staged/squashfs-root/AppRun" ]; then
    warn "AppImage self-extraction failed; installing the image directly. libfuse2 may be needed to launch it."
    return 1
  fi
  assert_existing_linux_target_owned \
    "linux-extracted" "$opt_dir" "$opt_dir/squashfs-root/AppRun" "$update_mode"
  assert_no_other_linux_shell_target "$opt_dir"
  wrapper="$dest_bin/flinttrade"
  preflight_linux_integrations "$opt_dir/squashfs-root/AppRun"
  signal_update_handoff
  begin_install_transaction
  replace_directory_transactionally \
    "$staged" "$opt_dir" "$transaction_dir" "squashfs-root/AppRun" \
    || die "Could not transactionally replace the extracted FlintTrade shell; the previous shell was preserved when present."
  icon="$opt_dir/squashfs-root/resources/icons/app.png"
  install_linux_launcher_extras "$opt_dir/squashfs-root/AppRun" "$dest_bin" "$icon"
  atomic_write_integration_file \
    "$desktop_dir/flinttrade.desktop" 0644 "$(linux_desktop_content "$wrapper")"
  write_shell_receipt \
    "linux-extracted" "$opt_dir" "$opt_dir/squashfs-root/AppRun" \
    "$wrapper" "$desktop_dir/flinttrade.desktop" "$INSTALLED_LINUX_ICON"
  commit_install_transaction
  say "Installed: $opt_dir (launcher: $wrapper)"
  if [ "$NO_LAUNCH" != "1" ]; then launch_linux_app "$wrapper"; fi
}

install_linux_appimage() {
  local appimage="$1" dest_bin="$HOME/.local/bin" desktop_dir="$HOME/.local/share/applications"
  local dest="$HOME/.local/bin/flinttrade.AppImage" canonical_parent canonical_target
  local extracted_root="" update_mode="fresh" has_appimage=0 has_extracted=0
  if [ -n "${FLINTTRADE_UPDATE_HANDOFF:-}" ] && [ "$DRY_RUN" != "1" ]; then
    [ -n "${APPIMAGE:-}" ] && has_appimage=1
    [ -n "${FLINTTRADE_UPDATE_LINUX_EXTRACTED_ROOT:-}" ] && has_extracted=1
    [ $((has_appimage + has_extracted)) -eq 1 ] \
      || die "The Linux updater requires exactly one exact target mode (AppImage or managed extracted root)."
    if [ "$has_appimage" = "1" ]; then
      case "$APPIMAGE" in
        /*) ;;
        *) die "The Linux updater requires the exact absolute running APPIMAGE path." ;;
      esac
      [ -f "$APPIMAGE" ] && [ ! -L "$APPIMAGE" ] \
        || die "The Linux updater target is not an ordinary AppImage file."
      canonical_parent="$(cd -P "$(dirname "$APPIMAGE")" 2>/dev/null && pwd)" \
        || die "The Linux updater target parent cannot be canonicalised."
      canonical_target="$canonical_parent/$(basename "$APPIMAGE")"
      [ "$canonical_target" = "$APPIMAGE" ] \
        || die "The Linux updater target must already be canonical and free of symlink aliases."
      [ -w "$APPIMAGE" ] && [ -w "$canonical_parent" ] \
        || die "The exact running AppImage is not writable; no update was signalled."
      dest="$APPIMAGE"
      update_mode="appimage"
    else
      extracted_root="$FLINTTRADE_UPDATE_LINUX_EXTRACTED_ROOT"
      case "$extracted_root" in
        /*/flinttrade) ;;
        *) die "The Linux updater requires the exact absolute managed extracted root." ;;
      esac
      [ -d "$extracted_root" ] && [ ! -L "$extracted_root" ] \
        && [ -x "$extracted_root/squashfs-root/AppRun" ] \
        || die "The Linux updater target is not an ordinary extracted FlintTrade shell."
      canonical_parent="$(cd -P "$(dirname "$extracted_root")" 2>/dev/null && pwd)" \
        || die "The extracted Linux updater target parent cannot be canonicalised."
      canonical_target="$canonical_parent/flinttrade"
      [ "$canonical_target" = "$extracted_root" ] \
        || die "The extracted Linux updater target must already be canonical and free of symlink aliases."
      [ -w "$extracted_root" ] && [ -w "$canonical_parent" ] \
        || die "The exact extracted Linux shell is not writable; no update was signalled."
      update_mode="extracted"
    fi
  fi
  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would install $appimage to $dest"
    return 0
  fi

  ensure_shell_receipt_storage
  ensure_owner_local_directory "$dest_bin"
  ensure_owner_local_directory "$desktop_dir"
  chmod 0755 "$appimage"
  if [ "$update_mode" = "extracted" ]; then
    install_linux_appimage_extracted "$appimage" "$dest_bin" "$desktop_dir" "$extracted_root" "$update_mode"
    return 0
  fi
  if [ "$update_mode" = "fresh" ] && ! linux_fuse_available \
      && install_linux_appimage_extracted "$appimage" "$dest_bin" "$desktop_dir" \
        "$HOME/.local/opt/flinttrade" "$update_mode"; then
    return 0
  fi

  local staged icon_tmp icon wrapper="$dest_bin/flinttrade"
  canonical_parent="$(cd -P "$(dirname "$dest")" 2>/dev/null && pwd -P)" \
    || die "The Linux AppImage destination parent cannot be canonicalised."
  assert_existing_linux_target_owned "linux-appimage" "$dest" "$dest" "$update_mode"
  assert_no_other_linux_shell_target "$dest"
  preflight_linux_integrations "$dest"
  staged="$(mktemp "$canonical_parent/.flinttrade-appimage.XXXXXX")" \
    || die "Could not create an adjacent AppImage staging file."
  TMP_DIRS+=("$staged")
  if ! install -m 0755 "$appimage" "$staged"; then
    die "Could not stage the verified AppImage beside its exact install target."
  fi
  if ! cmp -s "$appimage" "$staged"; then
    die "The staged AppImage does not match the verified release asset."
  fi
  signal_update_handoff
  begin_install_transaction
  publish_file_transactionally "$staged" "$dest"
  icon_tmp="$(mktemp -d "${TMPDIR:-/tmp}/flinttrade-icon.XXXXXX")"
  TMP_DIRS+=("$icon_tmp")
  (cd "$icon_tmp" && "$dest" --appimage-extract 'resources/icons/app.png' >/dev/null 2>&1) || true
  icon="$icon_tmp/squashfs-root/resources/icons/app.png"
  install_linux_launcher_extras "$dest" "$dest_bin" "$icon"
  atomic_write_integration_file \
    "$desktop_dir/flinttrade.desktop" 0644 "$(linux_desktop_content "$wrapper")"
  write_shell_receipt \
    "linux-appimage" "$dest" "$dest" "$wrapper" \
    "$desktop_dir/flinttrade.desktop" "$INSTALLED_LINUX_ICON"
  commit_install_transaction
  say "Installed: $dest"
  if [ "$NO_LAUNCH" != "1" ]; then launch_linux_app "$wrapper"; fi
}

install_binary_release() {
  local os_name="$(uname -s)" package
  case "$os_name" in
    Darwin)
      download_release_asset mac universal dmg
      package="$DOWNLOADED_ASSET_PATH"
      install_macos_dmg "$package"
      ;;
    Linux)
      download_release_asset linux "$(normalised_arch)" AppImage
      package="$DOWNLOADED_ASSET_PATH"
      install_linux_appimage "$package"
      ;;
    *) die "Unsupported OS '$os_name'. On Windows, use install.ps1." ;;
  esac
  say "Done. First launch builds the verified local source checkout. Rerun this installer only for shell updates."
}

validate_source_origin() {
  [ -d "$SRC_DIR/.git" ] || return 0
  local origin
  origin="$(git -C "$SRC_DIR" remote get-url origin 2>/dev/null || true)"
  case "$origin" in
    "$REPO_URL"|"${REPO_URL%.git}") ;;
    *) die "Refusing to update $SRC_DIR because origin is not the official HTTPS FlintTrade repository." ;;
  esac
}

validate_source_build_target() {
  local managed="$HOME/.flinttrade/src" source_path="$SRC_DIR" managed_path="$HOME/.flinttrade/src"
  case "$source_path" in
    "$managed"|"$managed"/*) die "Source-build mode refuses to mutate the managed active source tree." ;;
  esac
  if [ -d "$managed" ]; then managed_path="$(cd -P "$managed" && pwd)"; fi
  if [ -d "$source_path" ]; then
    source_path="$(cd -P "$source_path" && pwd)"
  elif [ -d "$(dirname "$source_path")" ]; then
    source_path="$(cd -P "$(dirname "$source_path")" && pwd)/$(basename "$source_path")"
  fi
  case "$source_path" in
    "$managed_path"|"$managed_path"/*) die "Source-build mode refuses to mutate the managed active source tree." ;;
  esac
}

check_source_prerequisites() {
  local missing=() node_version node_major node_minor node_header compiler
  need git || missing+=("Git from https://git-scm.com")
  if need node; then
    node_version="$(node -p 'process.versions.node')"
    node_major="${node_version%%.*}"
    node_minor="${node_version#*.}"; node_minor="${node_minor%%.*}"
    if [ "$node_major" -lt 22 ] || { [ "$node_major" -eq 22 ] && [ "$node_minor" -lt 12 ]; }; then
      missing+=("Node.js >= 22.12 (found v$node_version)")
    fi
    node_header="$(node -p 'require("path").resolve(require("path").dirname(process.execPath), "..", "include", "node", "node_api.h")')"
    [ -f "$node_header" ] || missing+=("Node.js N-API headers (missing $node_header)")
  else
    missing+=("Node.js >= 22.12")
  fi
  case "$(uname -s)" in
    Darwin) compiler=/usr/bin/clang ;;
    Linux) compiler=/usr/bin/cc ;;
    *) compiler= ;;
  esac
  [ -n "$compiler" ] && [ -x "$compiler" ] || missing+=("the platform C compiler required for atomic source promotion")
  if ! need corepack && ! need npx \
      && { ! need pnpm || [ "$(pnpm --version 2>/dev/null)" != "$PINNED_PNPM_VERSION" ]; }; then
    missing+=("pnpm $PINNED_PNPM_VERSION through Corepack, npx, or a matching binary")
  fi
  if [ "${#missing[@]}" -gt 0 ]; then
    warn "Missing source-build prerequisites:"
    local hint
    for hint in "${missing[@]}"; do warn "  - $hint"; done
    die "Install the tools above, then rerun with --build-from-source."
  fi
}

build_from_source() {
  local os_name="$(uname -s)" arch version package
  case "$os_name" in Darwin|Linux) ;; *) die "Unsupported OS '$os_name'. On Windows, use install.ps1." ;; esac
  say "Source-build mode packages only the Electron shell. Checking Git, Node, pnpm and the native compiler..."
  validate_source_build_target
  check_source_prerequisites
  validate_source_origin
  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would clone or update the pinned repository at ${REF:-the newest release tag}"
    say "DRY-RUN: would install the frozen JavaScript workspace and package only @flinttrade/desktop with pnpm $PINNED_PNPM_VERSION"
    return 0
  fi

  if [ -z "$REF" ]; then
    say "Resolving newest release tag from the official repository..."
    REF="$(git ls-remote --tags --refs "$REPO_URL" 'v*' | awk -F/ '{print $NF}' \
      | grep -E "$RELEASE_TAG_PATTERN" | filter_release_tags_for_channel | resolve_latest_tag)"
    [ -n "$REF" ] || die "Could not resolve a release tag from $REPO_URL"
  fi
  if [ -d "$SRC_DIR/.git" ]; then
    say "Updating trusted source workspace at $SRC_DIR..."
    git -C "$SRC_DIR" fetch --tags "$REPO_URL"
    git -C "$SRC_DIR" checkout --quiet "$REF"
  else
    say "Cloning FlintTrade ($REF) into $SRC_DIR..."
    mkdir -p "$(dirname "$SRC_DIR")"
    git clone --branch "$REF" --depth 1 "$REPO_URL" "$SRC_DIR"
  fi

  cd "$SRC_DIR"
  say "Installing the frozen JavaScript workspace with pnpm $PINNED_PNPM_VERSION..."
  pnpm_run install --frozen-lockfile
  version="${REF#v}"
  if [ "$os_name" = "Darwin" ]; then
    say "Packaging the universal Electron DMG..."
    pnpm_run --dir packages/apps/desktop run pack:mac
    package="$SRC_DIR/packages/apps/desktop/release/electron/FlintTrade-$version-mac-universal.dmg"
    [ -f "$package" ] || die "Electron packaging completed without $package"
    install_macos_dmg "$package"
  else
    arch="$(normalised_arch)"
    say "Packaging the Electron AppImage for $arch..."
    pnpm_run --dir packages/apps/desktop run "pack:linux:$arch"
    package="$SRC_DIR/packages/apps/desktop/release/electron/FlintTrade-$version-linux-$arch.AppImage"
    [ -f "$package" ] || die "Electron packaging completed without $package"
    install_linux_appimage "$package"
  fi
}

if [ "${FLINTTRADE_RESOLVE_TAGS_ONLY:-0}" = "1" ]; then
  filter_release_tags_for_channel | resolve_latest_tag
  exit 0
fi

if [ "$BUILD_FROM_SOURCE" = "1" ]; then
  build_from_source
else
  install_binary_release
fi

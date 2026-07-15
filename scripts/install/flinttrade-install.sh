#!/usr/bin/env bash
# FlintTrade desktop installer / updater (macOS + Linux)
#
# Default mode downloads the published desktop installer for this OS/arch from
# the FlintTrade release manifest and installs it. Source builds remain
# available with --build-from-source for contributors who intentionally want the
# Rust/Node/Python/Tauri toolchain path.
#
#   curl -fsSL https://flinttrade.vercel.app/install.sh | bash
#   curl -fsSL https://flinttrade.vercel.app/install.sh | bash -s -- --build-from-source

set -euo pipefail

REPO_URL="https://github.com/navaneeshnagarajan/FlintTrade.git"
# Release metadata comes straight from the official GitHub release-download
# path: every release ships a flinttrade-desktop-manifest.json asset, and the
# rolling updater-beta / updater-stable releases always point at the newest
# release of that channel. FLINTTRADE_DESKTOP_RELEASE_API is a test/advanced
# override used verbatim as the manifest URL.
RELEASE_DOWNLOAD_BASE="https://github.com/navaneeshnagarajan/FlintTrade/releases/download"
MANIFEST_ASSET_NAME="flinttrade-desktop-manifest.json"
MANIFEST_OVERRIDE_URL="${FLINTTRADE_DESKTOP_RELEASE_API:-}"
PINNED_PNPM_VERSION="${FLINTTRADE_PNPM_VERSION:-9.15.0}"
SRC_DIR="${FLINTTRADE_SRC_DIR:-$HOME/.flinttrade/src/FlintTrade}"
REF="${FLINTTRADE_REF:-}"
CHANNEL="${FLINTTRADE_CHANNEL:-beta}"
NO_LAUNCH="${FLINTTRADE_NO_LAUNCH:-0}"
ASSUME_YES="${FLINTTRADE_YES:-0}"
BUILD_FROM_SOURCE="${FLINTTRADE_BUILD_FROM_SOURCE:-0}"
DRY_RUN="${FLINTTRADE_DRY_RUN:-0}"
LINUX_PACKAGE="${FLINTTRADE_LINUX_PACKAGE:-appimage}"
DOWNLOADED_ASSET_PATH=""
TMP_DIRS=("")
DMG_MOUNT_DIR=""

cleanup_tmp_dirs() {
  local dir
  for dir in "${TMP_DIRS[@]}"; do
    if [ -n "$dir" ]; then
      rm -rf "$dir" || true
    fi
  done
  return 0
}

# Detach a mounted DMG (macOS). Cleared after detaching so the EXIT trap does
# not try again. A no-op on Linux / when nothing is mounted.
detach_dmg_mount() {
  if [ -n "$DMG_MOUNT_DIR" ]; then
    hdiutil detach "$DMG_MOUNT_DIR" -quiet >/dev/null 2>&1 || true
    DMG_MOUNT_DIR=""
  fi
  return 0
}

# Single EXIT handler: always detach any DMG left mounted (e.g. an interrupt
# between attach and detach) before removing temp dirs.
cleanup_on_exit() {
  detach_dmg_mount
  cleanup_tmp_dirs
}
trap cleanup_on_exit EXIT

say()  { printf '\033[1;36m[flinttrade]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[flinttrade]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[flinttrade]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'USAGE'

Flags:
  --channel beta|stable     Release channel to install (default: beta)
  --ref <tag>               Install an exact release tag (for example v0.6.0-beta.1)
  --package appimage|deb|rpm Linux package preference (default: appimage)
  --build-from-source       Clone/update the release source and build locally
  --src <dir>               Source workspace for --build-from-source
  --update                  Alias for the default install/update flow
  --no-launch               Do not launch FlintTrade after installing
  --yes                     Consent to user-local helper installs in source-build mode
  --dry-run                 Print actions without downloading/installing
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --channel) CHANNEL="${2:?--channel needs beta or stable}"; shift 2 ;;
    --ref) REF="${2:?--ref needs a value}"; shift 2 ;;
    --package) LINUX_PACKAGE="${2:?--package needs appimage, deb, or rpm}"; shift 2 ;;
    --build-from-source) BUILD_FROM_SOURCE=1; shift ;;
    --src) SRC_DIR="${2:?--src needs a value}"; shift 2 ;;
    --update) shift ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown flag: $1 (see --help)" ;;
  esac
done

case "$CHANNEL" in
  beta|stable) ;;
  *) die "--channel must be beta or stable" ;;
esac

case "$LINUX_PACKAGE" in
  appimage|deb|rpm) ;;
  *) die "--package must be appimage, deb, or rpm" ;;
esac

need() { command -v "$1" >/dev/null 2>&1; }

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

run_or_echo() {
  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: $*"
  else
    "$@"
  fi
}

consent() {
  local question="$1"
  if [ "$ASSUME_YES" = "1" ]; then return 0; fi
  # A controlling terminal can exist as an unopenable device node on headless
  # or CI hosts — the -r/-w permission bits pass yet opening /dev/tty fails with
  # ENXIO — so guard every access and keep `answer` defined so `set -u` cannot
  # abort the run mid-prompt. No usable terminal means no consent.
  local answer=""
  printf '\033[1;36m[flinttrade]\033[0m %s [y/N] ' "$question" > /dev/tty 2>/dev/null || return 1
  read -r answer < /dev/tty 2>/dev/null || return 1
  [ "$answer" = "y" ] || [ "$answer" = "Y" ]
}

json_object_field() {
  local object="$1"
  local field="$2"
  printf '%s' "$object" | awk -v field="$field" '
    {
      pat="\"" field "\":\""
      start=index($0, pat)
      if (start == 0) exit 1
      rest=substr($0, start + length(pat))
      end=index(rest, "\"")
      if (end == 0) exit 1
      print substr(rest, 1, end - 1)
    }
  '
}

json_object_field_optional() {
  json_object_field "$@" 2>/dev/null || true
}

json_contains_string_key() {
  local json="$1"
  local field="$2"
  printf '%s' "$json" | tr -d '[:space:]' | grep -q "\"$field\":\""
}

lowercase() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

# When launched by the desktop shell's in-app updater, signal that the download
# has been verified and the irreversible install step is beginning, so the shell
# can quit and let the freshly installed build relaunch. A no-op for website/CLI
# installs (FLINTTRADE_UPDATE_HANDOFF is unset) and during --dry-run.
signal_update_handoff() {
  [ "$DRY_RUN" = "1" ] && return 0
  local marker="${FLINTTRADE_UPDATE_HANDOFF:-}"
  [ -n "$marker" ] || return 0
  : > "$marker" 2>/dev/null || true
  return 0
}

# Pick the newest release tag from a newline-separated list on stdin, using
# semantic-version precedence. A stable release must outrank its own prerelease
# at the same version (v1.2.3 > v1.2.3-beta.1). We map the prerelease separator
# '-' to '~', which `sort -V` (GNU filevercmp and BSD sort alike) sorts BEFORE
# the empty string, so the stable tag ends up last; the mapping is reversed on
# the winner. A newer prerelease still beats an older stable (v1.3.0-beta.1 >
# v1.2.9), preserving "newest overall".
resolve_latest_tag() {
  sed 's/-/~/' | sort -V | tail -1 | sed 's/~/-/'
}

verify_sha256() {
  local file="$1"
  local expected="$2"
  local actual
  [ -n "$expected" ] || return 0
  if need sha256sum; then
    actual="$(sha256sum "$file" | awk '{print $1}')"
  elif need shasum; then
    actual="$(shasum -a 256 "$file" | awk '{print $1}')"
  else
    die "Release manifest includes a sha256 checksum, but neither sha256sum nor shasum is available."
  fi
  if [ "$(lowercase "$actual")" != "$(lowercase "$expected")" ]; then
    die "Checksum mismatch for $(basename "$file"). Expected $expected, got $actual."
  fi
  say "Verified SHA-256 checksum."
}

select_asset_object() {
  local manifest="$1"
  local os="$2"
  local arch="$3"
  local kind="$4"
  printf '%s' "$manifest" | tr -d '[:space:]' | tr '{' '\n' | awk -v os="$os" -v arch="$arch" -v kind="$kind" '
    index($0, "\"os\":\"" os "\"") &&
    index($0, "\"arch\":\"" arch "\"") &&
    index($0, "\"kind\":\"" kind "\"") { print $0; exit }
  '
}

manifest_url() {
  # The manifest is fetched over the network and drives which asset is
  # installed, so any override must be HTTPS (no plaintext http:// that a MITM
  # could rewrite). A local file:// manifest is permitted only under the test
  # hook. Without an override, the manifest is read from the official GitHub
  # release-download path: the exact tag when --ref is given, otherwise the
  # rolling updater-<channel> release for the selected channel.
  if [ -n "$MANIFEST_OVERRIDE_URL" ]; then
    case "$MANIFEST_OVERRIDE_URL" in
      https://*) printf '%s' "$MANIFEST_OVERRIDE_URL"; return 0 ;;
      file://*)
        if [ "${FLINTTRADE_ALLOW_LOCAL_ASSET:-0}" = "1" ]; then
          printf '%s' "$MANIFEST_OVERRIDE_URL"; return 0
        fi
        die "Refusing non-HTTPS release manifest URL: $MANIFEST_OVERRIDE_URL"
        ;;
      *) die "Refusing non-HTTPS release manifest URL: $MANIFEST_OVERRIDE_URL" ;;
    esac
  fi
  if [ -n "$REF" ]; then
    printf '%s/%s/%s' "$RELEASE_DOWNLOAD_BASE" "$REF" "$MANIFEST_ASSET_NAME"
  else
    printf '%s/updater-%s/%s' "$RELEASE_DOWNLOAD_BASE" "$CHANNEL" "$MANIFEST_ASSET_NAME"
  fi
}

normalised_arch() {
  case "$(uname -m)" in
    arm64|aarch64) printf 'arm64' ;;
    x86_64|amd64) printf 'x64' ;;
    *) die "Unsupported CPU architecture: $(uname -m)" ;;
  esac
}

download_release_asset() {
  need curl || die "curl is required to download the FlintTrade installer."

  local os="$1"
  local arch="$2"
  local kind="$3"
  local url
  url="$(manifest_url)"

  say "Resolving FlintTrade desktop release ($url)..."
  local manifest
  manifest="$(curl -fsSL "$url")" || die "Could not fetch the desktop release manifest."
  if json_contains_string_key "$manifest" warning; then
    die "The release manifest endpoint returned a fallback warning; refusing to install from stale metadata."
  fi
  if json_contains_string_key "$manifest" error; then
    die "The release manifest endpoint returned an error; refusing to install."
  fi

  local object
  object="$(select_asset_object "$manifest" "$os" "$arch" "$kind")"
  [ -n "$object" ] || die "No $os/$arch/$kind installer was found in the selected release."

  local asset_url asset_name asset_sha
  asset_url="$(json_object_field "$object" url)"
  asset_name="$(json_object_field "$object" name)"
  asset_sha="$(json_object_field_optional "$object" sha256)"
  [ -n "$asset_url" ] || die "Release manifest did not include an asset URL."
  [ -n "$asset_name" ] || die "Release manifest did not include an asset name."
  # The downloaded file is executed/installed, so it MUST come from the official
  # repository's release-download path — never a host a tampered manifest chose.
  # FLINTTRADE_ALLOW_LOCAL_ASSET=1 additionally permits a local file:// URL; it
  # is a test-only hook (offline checksum-path coverage) and never relaxes to a
  # remote host, so it cannot be abused to fetch from an attacker's server.
  case "$asset_url" in
    https://github.com/navaneeshnagarajan/FlintTrade/releases/download/*) : ;;
    file://*)
      [ "${FLINTTRADE_ALLOW_LOCAL_ASSET:-0}" = "1" ] \
        || die "Refusing non-release asset URL: $asset_url"
      ;;
    *) die "Refusing asset URL outside the official release path: $asset_url" ;;
  esac

  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would download $asset_name"
    say "DRY-RUN: $asset_url"
    if [ -n "$asset_sha" ]; then
      say "DRY-RUN: would verify sha256 $asset_sha"
    fi
    DOWNLOADED_ASSET_PATH="/tmp/$asset_name"
    return 0
  fi

  local tmp_dir
  tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/flinttrade.XXXXXX")"
  TMP_DIRS+=("$tmp_dir")
  local dest="$tmp_dir/$asset_name"
  say "Downloading $asset_name..."
  curl -fL "$asset_url" -o "$dest"
  verify_sha256 "$dest" "$asset_sha"
  DOWNLOADED_ASSET_PATH="$dest"
}

install_macos_dmg() {
  local dmg="$1"
  local mount_dir="${TMPDIR:-/tmp}/flinttrade-dmg-$$"
  local dest="/Applications"
  [ -w "$dest" ] || dest="$HOME/Applications"

  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would mount $dmg and copy FlintTrade.app to $dest"
    return 0
  fi

  # Download is verified by now — tell the desktop shell (if it launched us) to
  # step aside before the irreversible replace of the running bundle.
  signal_update_handoff

  mkdir -p "$mount_dir" "$dest"
  hdiutil attach "$dmg" -nobrowse -quiet -mountpoint "$mount_dir"
  # Register the mount so the EXIT trap always detaches it, even if we are
  # interrupted (Ctrl-C / SIGTERM) between attach and detach.
  DMG_MOUNT_DIR="$mount_dir"

  local app_path
  app_path="$(find "$mount_dir" -maxdepth 2 -name 'FlintTrade.app' -type d | head -1)"
  if [ -z "$app_path" ]; then
    detach_dmg_mount
    rm -rf "$mount_dir"
    die "No FlintTrade.app found in $dmg"
  fi

  say "Installing FlintTrade.app into $dest..."
  rm -rf "$dest/FlintTrade.app"
  if ! ditto "$app_path" "$dest/FlintTrade.app"; then
    detach_dmg_mount
    rm -rf "$mount_dir"
    die "Could not copy FlintTrade.app to $dest"
  fi
  detach_dmg_mount
  rm -rf "$mount_dir"

  say "Installed: $dest/FlintTrade.app"
  if [ "$NO_LAUNCH" != "1" ]; then open "$dest/FlintTrade.app"; fi
}

install_linux_appimage() {
  local appimage="$1"
  local dest_bin="$HOME/.local/bin"
  local desktop_dir="$HOME/.local/share/applications"
  local dest="$dest_bin/flinttrade.AppImage"

  # In-app updater relaunch target. The AppImage runtime exports $APPIMAGE as the
  # absolute path of the running image; when updating in place, replace THAT file
  # (wherever the operator launched it from) rather than always dropping a second
  # copy under ~/.local/bin. Requires the running file and its directory to be
  # writable; otherwise fall back to the fixed ~/.local/bin target. Fresh
  # website/CLI installs have no $APPIMAGE and always use the fixed target.
  if [ -n "${APPIMAGE:-}" ] && [ -f "${APPIMAGE:-}" ] \
      && [ -w "${APPIMAGE:-}" ] && [ -w "$(dirname "${APPIMAGE:-}")" ]; then
    dest="$APPIMAGE"
    dest_bin="$(dirname "$dest")"
  fi

  run_or_echo mkdir -p "$dest_bin" "$desktop_dir"
  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would install $appimage to $dest"
  else
    signal_update_handoff
    # Write-new-then-rename: overwriting a running AppImage in place with a
    # truncating copy would fail with ETXTBSY, so stage the new image beside the
    # target and atomically rename over it. The old inode stays valid for the
    # still-running process; new launches pick up the replacement.
    local staged="$dest.new.$$"
    install -m 0755 "$appimage" "$staged"
    mv -f "$staged" "$dest"
    cat > "$desktop_dir/flinttrade.desktop" <<DESKTOP
[Desktop Entry]
Name=FlintTrade
Exec=$dest
Type=Application
Categories=Office;Finance;
Comment=Open-source self-hosted trading software
DESKTOP
  fi
  say "Installed: $dest"
  warn "If this distro cannot run AppImage files, install FUSE or rerun with --package deb/rpm."
  if [ "$NO_LAUNCH" != "1" ] && [ "$DRY_RUN" != "1" ]; then
    nohup "$dest" >/dev/null 2>&1 &
  fi
}

install_linux_native_package() {
  local package="$1"
  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would install $package as a .$LINUX_PACKAGE package"
    return 0
  fi
  case "$LINUX_PACKAGE" in
    deb)
      need apt || die "apt was not found. Use --package appimage or install the .deb manually: $package"
      say "Installing .deb package with apt..."
      run_or_echo sudo apt install "$package"
      ;;
    rpm)
      if need dnf; then
        say "Installing .rpm package with dnf..."
        run_or_echo sudo dnf install "$package"
      elif need rpm; then
        say "Installing .rpm package with rpm..."
        run_or_echo sudo rpm -Uvh "$package"
      else
        die "dnf/rpm was not found. Use --package appimage or install the .rpm manually: $package"
      fi
      ;;
  esac
}

install_binary_release() {
  local os_name
  os_name="$(uname -s)"
  local arch
  arch="$(normalised_arch)"

  case "$os_name" in
    Darwin)
      local dmg
      download_release_asset macos "$arch" dmg
      dmg="$DOWNLOADED_ASSET_PATH"
      install_macos_dmg "$dmg"
      ;;
    Linux)
      local kind="$LINUX_PACKAGE"
      [ "$kind" = "appimage" ] && kind="appimage"
      local package
      download_release_asset linux "$arch" "$kind"
      package="$DOWNLOADED_ASSET_PATH"
      if [ "$LINUX_PACKAGE" = "appimage" ]; then
        install_linux_appimage "$package"
      else
        install_linux_native_package "$package"
      fi
      ;;
    *)
      die "Unsupported OS '$os_name'. On Windows, use install.ps1 instead."
      ;;
  esac

  say "Done. To update later, rerun this installer or use Settings -> Updates."
}

build_from_source() {
  local os_name
  os_name="$(uname -s)"
  case "$os_name" in
    Darwin|Linux) ;;
    *) die "Unsupported OS '$os_name'. On Windows, use install.ps1 instead." ;;
  esac

  say "Source-build mode enabled. Checking build prerequisites..."
  local missing=()
  need git  || missing+=("git - install from https://git-scm.com or your package manager")
  need curl || missing+=("curl - install via your package manager")
  need make || missing+=("make - macOS: xcode-select --install; Debian/Ubuntu: sudo apt install build-essential")

  if [ "$os_name" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
    missing+=("Xcode Command Line Tools - run: xcode-select --install")
  fi
  need cargo || missing+=("Rust stable - run: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh")

  if need node; then
    local node_major
    node_major="$(node -e 'process.stdout.write(String(process.versions.node.split(".")[0]))')"
    if [ "$node_major" -lt 22 ]; then
      missing+=("Node.js >= 22 (found $(node --version))")
    fi
  else
    missing+=("Node.js >= 22")
  fi

  if [ "$os_name" = "Linux" ]; then
    if need pkg-config && ! pkg-config --exists webkit2gtk-4.1 2>/dev/null; then
      missing+=("Tauri libraries - Debian/Ubuntu: sudo apt install libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf")
    fi
  fi

  if ! need uv; then
    if consent "uv is missing. Install it now (user-local, from astral.sh)?"; then
      curl -LsSf https://astral.sh/uv/install.sh | sh
      export PATH="$HOME/.local/bin:$PATH"
      need uv || die "uv installed but is not on PATH. Restart your shell and rerun."
    else
      missing+=("uv - run: curl -LsSf https://astral.sh/uv/install.sh | sh")
    fi
  fi

  if ! need corepack && ! need npx && { ! need pnpm || [ "$(pnpm --version 2>/dev/null)" != "$PINNED_PNPM_VERSION" ]; }; then
    missing+=("pnpm $PINNED_PNPM_VERSION - install Node's npx/corepack or a matching pnpm binary")
  fi

  if [ ${#missing[@]} -gt 0 ]; then
    warn "Missing source-build prerequisites:"
    for hint in "${missing[@]}"; do warn "  - $hint"; done
    die "Install the tools above, then rerun with --build-from-source."
  fi

  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: source build would clone/update $REPO_URL at ${REF:-latest release tag}"
    say "DRY-RUN: source build would run uv sync, install PyInstaller, pnpm $PINNED_PNPM_VERSION install, and make desktop-build"
    return 0
  fi

  if [ -z "$REF" ]; then
    say "Resolving newest release tag from GitHub..."
    REF="$(git ls-remote --tags --refs "$REPO_URL" 'v*' | awk -F/ '{print $NF}' | resolve_latest_tag)"
    [ -n "$REF" ] || die "Could not resolve a release tag from $REPO_URL"
  fi

  if [ -d "$SRC_DIR/.git" ]; then
    say "Updating source workspace at $SRC_DIR..."
    git -C "$SRC_DIR" fetch --tags origin
    git -C "$SRC_DIR" checkout --quiet "$REF"
  else
    say "Cloning FlintTrade ($REF) into $SRC_DIR..."
    mkdir -p "$(dirname "$SRC_DIR")"
    git clone --branch "$REF" --depth 1 "$REPO_URL" "$SRC_DIR"
  fi

  cd "$SRC_DIR"
  say "Installing Python dependencies..."
  uv sync
  uv pip install pyinstaller
  say "Installing JS workspace dependencies with pnpm $PINNED_PNPM_VERSION..."
  pnpm_run install --frozen-lockfile
  say "Building desktop app from source..."
  make desktop-build

  local bundle_dir="packages/apps/desktop/src-tauri/target/release/bundle"
  [ -d "$bundle_dir" ] || die "Build finished but no bundle directory exists at $bundle_dir"
  if [ "$os_name" = "Darwin" ]; then
    local app_path
    app_path="$(find "$bundle_dir/macos" -maxdepth 1 -name '*.app' | head -1)"
    [ -n "$app_path" ] || die "No .app produced under $bundle_dir/macos"
    local dest="/Applications"
    [ -w "$dest" ] || dest="$HOME/Applications"
    mkdir -p "$dest"
    rm -rf "$dest/$(basename "$app_path")"
    ditto "$app_path" "$dest/$(basename "$app_path")"
    if [ "$NO_LAUNCH" != "1" ]; then open "$dest/$(basename "$app_path")"; fi
  else
    local appimage
    appimage="$(find "$bundle_dir/appimage" -maxdepth 1 -name '*.AppImage' 2>/dev/null | head -1 || true)"
    [ -n "$appimage" ] || die "No AppImage produced under $bundle_dir"
    install_linux_appimage "$appimage"
  fi
}

# Test-only hook: resolve the newest tag from a list on stdin and exit. Used by
# tests/test_desktop_install_scripts.py to pin the stable-over-prerelease tie
# break without a network round-trip. Never triggered by normal installs.
if [ "${FLINTTRADE_RESOLVE_TAGS_ONLY:-0}" = "1" ]; then
  resolve_latest_tag
  exit 0
fi

if [ "$BUILD_FROM_SOURCE" = "1" ]; then
  build_from_source
else
  install_binary_release
fi

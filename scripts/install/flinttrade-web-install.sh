#!/usr/bin/env bash
# FlintTrade one-line web-app installer (macOS + Linux)
#
# Installs the FlintTrade web app on a bare machine with no prerequisites at
# all: no uv, no Python, no Node, no pnpm, no git and no make. Every tool is
# downloaded from its pinned URL, SHA-256 verified against the repository's own
# bootstrap tool manifest, and confined to ~/.flinttrade/tools. The build itself
# is delegated to the repository's packaged bootstrap entrypoint so this
# installer never duplicates the uv/pnpm build behaviour.
#
#   curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash
#
# Uninstall:
#   curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash

set -euo pipefail

REPO_SLUG="navaneeshnagarajan/FlintTrade"
REPO_URL="https://github.com/$REPO_SLUG.git"
ARCHIVE_BASE_URL="https://codeload.github.com/$REPO_SLUG/zip"
DEFAULT_BRANCH="main"
PINNED_PNPM_VERSION="9.15.0"
BACKEND_URL="http://127.0.0.1:5100"
UNINSTALL_COMMAND="curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash"
MANAGED_ROOT="$HOME/.flinttrade"
TOOLS_ROOT="$MANAGED_ROOT/tools"
# The Electron desktop shell resolves exactly these two paths
# (packages/apps/desktop/electron/paths.ts) and guards every mutation of the
# active source with an operation lease directory created by its bootstrap
# (packages/apps/desktop/electron/bootstrap.ts).
DESKTOP_SOURCE_ROOT="$MANAGED_ROOT/src"
DESKTOP_ACTIVE_SOURCE="$DESKTOP_SOURCE_ROOT/FlintTrade"
DESKTOP_OPERATION_LEASE="$DESKTOP_SOURCE_ROOT/.flinttrade-bootstrap-operation.lock"
# FLINTTRADE_SRC_DIR belongs to flinttrade-install.sh, where it names the
# contributor source-build checkout (default ~/.flinttrade/source-build/
# FlintTrade). This installer fetches, hard-resets and can replace whatever
# directory it is given, so it owns FLINTTRADE_WEB_SRC_DIR instead and only
# falls back to the older name behind a loud warning.
SRC_DIR_SOURCE="default"
if [ -n "${FLINTTRADE_WEB_SRC_DIR:-}" ]; then
  SRC_DIR="$FLINTTRADE_WEB_SRC_DIR"
  SRC_DIR_SOURCE="FLINTTRADE_WEB_SRC_DIR"
elif [ -n "${FLINTTRADE_SRC_DIR:-}" ]; then
  SRC_DIR="$FLINTTRADE_SRC_DIR"
  SRC_DIR_SOURCE="FLINTTRADE_SRC_DIR"
else
  SRC_DIR="$DESKTOP_ACTIVE_SOURCE"
fi
SHIM_DIR="$HOME/.local/bin"
SHIM_PATH="$SHIM_DIR/flinttrade"
# Owner-private receipt for everything this installer writes outside the
# managed root. The uninstaller may only delete what an installer proved it
# created, exactly as flinttrade-install.sh proves the Electron shell.
WEB_RECEIPT_DIR="$HOME/.local/state/flinttrade-web"
WEB_RECEIPT_PATH="$WEB_RECEIPT_DIR/web-install.receipt"
MANIFEST_RELATIVE="packages/apps/desktop/resources/bootstrap/tool-manifest.json"
BOOTSTRAP_RELATIVE="packages/apps/desktop/resources/bootstrap/flinttrade-bootstrap.sh"
ALLOWED_HOSTS="codeload.github.com github.com api.github.com nodejs.org registry.npmjs.org"

REF="${FLINTTRADE_REF:-}"
YES="${FLINTTRADE_YES:-0}"
DRY_RUN="${FLINTTRADE_DRY_RUN:-0}"
NO_LAUNCH="${FLINTTRADE_NO_LAUNCH:-0}"

TARGET=""
MANIFEST_FLAT=""
RESOLVED_UV=""
RESOLVED_NODE=""
RESOLVED_COREPACK_JS=""
RESOLVED_PYTHON=""
TOOL_EXECUTABLE=""
HOST_GIT_VERSION=""
HOST_UV_VERSION=""
HOST_NODE_VERSION=""
HOST_PNPM_VERSION=""
HOST_PYTHON_VERSION=""
REUSE_UV=""
REUSE_NODE=""
REUSE_COREPACK_JS=""
TMP_DIRS=("")

say()  { printf '\033[1;36m[flinttrade]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[flinttrade]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[flinttrade]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1; }
lowercase() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

usage() {
  cat <<'USAGE'
FlintTrade one-line web-app installer (macOS + Linux)

Provisions a verified uv + Node toolchain, builds FlintTrade from a managed
source checkout, and installs a 'flinttrade' launcher. No prior tooling needed.

Flags:
  --ref <git-ref>   Branch, tag or commit to install (default: main)
  --src <dir>       Managed WEB source checkout (default: ~/.flinttrade/src/FlintTrade).
                    This is not the contributor source-build checkout that
                    flinttrade-install.sh manages at ~/.flinttrade/source-build/FlintTrade.
  --yes             Answer every confirmation with yes
  --no-launch       Do not offer to start FlintTrade after installing
  --dry-run         Report the plan without downloading, building or installing
  --help            Show this help and exit

Environment overrides:
  FLINTTRADE_REF, FLINTTRADE_WEB_SRC_DIR, FLINTTRADE_YES,
  FLINTTRADE_DRY_RUN, FLINTTRADE_NO_LAUNCH

  FLINTTRADE_SRC_DIR is a deprecated fallback for FLINTTRADE_WEB_SRC_DIR here.
  flinttrade-install.sh reads it as the contributor source-build checkout, so
  this installer warns and asks for confirmation before managing a directory
  that only that variable supplied.

Uninstall:
  curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash
USAGE
}

cleanup() {
  local dir
  for dir in "${TMP_DIRS[@]}"; do
    if [ -n "$dir" ]; then rm -rf "$dir" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF="${2:?--ref needs a value}"; shift 2 ;;
    --src) SRC_DIR="${2:?--src needs a value}"; SRC_DIR_SOURCE="--src"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown flag: $1 (see --help)" ;;
  esac
done

if [ -n "$REF" ]; then
  case "$REF" in
    *[!A-Za-z0-9._/-]*) die "--ref may only contain letters, digits, dot, underscore, slash and dash." ;;
    -*|*..*|*/) die "--ref is not a well-formed Git reference: $REF" ;;
  esac
fi
case "$SRC_DIR" in
  /*) ;;
  *) die "--src must be an absolute path: $SRC_DIR" ;;
esac

# ---------------------------------------------------------------------------
# Canonical paths
# ---------------------------------------------------------------------------

workspace_dir() {
  if [ -n "${FLINTTRADE_WORKSPACE_DIR:-}" ]; then printf '%s' "$FLINTTRADE_WORKSPACE_DIR"; return 0; fi
  if [ -n "${FLINTTRADE_HOME:-}" ]; then printf '%s' "$FLINTTRADE_HOME"; return 0; fi
  case "$(uname -s)" in
    Darwin) printf '%s' "$HOME/Library/Application Support/flinttrade" ;;
    *) printf '%s' "$HOME/.flinttrade" ;;
  esac
}

# ---------------------------------------------------------------------------
# 1. Operating system and CPU architecture detection
# ---------------------------------------------------------------------------

detect_target() {
  local os arch machine kernel
  kernel="$(uname -s)"
  machine="$(uname -m)"
  case "$kernel" in
    Darwin) os=darwin ;;
    Linux) os=linux ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      die "This is the POSIX installer. On Windows 10/11 run: irm https://flinttrade.vercel.app/web-install.ps1 | iex"
      ;;
    *)
      die "Unsupported operating system '$kernel'. FlintTrade publishes verified tools for macOS, Linux and Windows 10/11 only."
      ;;
  esac
  case "$machine" in
    arm64|aarch64) arch=arm64 ;;
    x86_64|amd64) arch=x64 ;;
    *)
      die "Unsupported CPU architecture '$machine'. The bootstrap tool manifest pins verified tools for arm64 and x64 only."
      ;;
  esac
  printf '%s-%s' "$os" "$arch"
}

# ---------------------------------------------------------------------------
# Network guards — HTTPS only, and only the hosts this installer is allowed to
# contact.
# ---------------------------------------------------------------------------

url_host() {
  local rest="$1"
  rest="${rest#*://}"
  rest="${rest%%/*}"
  rest="${rest%%\?*}"
  rest="${rest##*@}"
  rest="${rest%%:*}"
  lowercase "$rest"
}

assert_trusted_url() {
  local url="$1" host allowed matched=0
  case "$url" in
    https://*) ;;
    *) die "Refusing a non-HTTPS URL: $url" ;;
  esac
  host="$(url_host "$url")"
  for allowed in $ALLOWED_HOSTS; do
    if [ "$host" = "$allowed" ]; then matched=1; fi
  done
  if [ "$matched" != "1" ]; then
    die "Refusing to contact '$host'. This installer only ever contacts: $ALLOWED_HOSTS"
  fi
}

assert_sha256_shape() {
  local value="$1"
  if [ "${#value}" -ne 64 ]; then die "The bootstrap tool manifest holds a malformed SHA-256 digest."; fi
  case "$value" in
    *[!0-9a-f]*) die "The bootstrap tool manifest holds a malformed SHA-256 digest." ;;
  esac
}

assert_confined_relative_path() {
  local value="$1"
  case "$value" in
    /*|*..*|"") die "The bootstrap tool manifest holds an unconfined executable path: $value" ;;
  esac
}

download_to() {
  local url="$1" dest="$2"
  assert_trusted_url "$url"
  if need curl; then
    curl -fsSL --proto '=https' --tlsv1.2 "$url" -o "$dest" || die "Download failed: $url"
  elif need wget; then
    wget -q --https-only -O "$dest" "$url" || die "Download failed: $url"
  else
    die "Neither curl nor wget is available; install one of them and re-run."
  fi
}

sha256_of() {
  local file="$1"
  if need sha256sum; then
    sha256sum "$file" | awk '{print $1}'
  elif need shasum; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    die "Neither sha256sum nor shasum is available; refusing an unverifiable download."
  fi
}

verify_sha256() {
  local file="$1" expected="$2" actual
  actual="$(lowercase "$(sha256_of "$file")")"
  if [ "$actual" != "$(lowercase "$expected")" ]; then
    rm -f "$file"
    die "SHA-256 mismatch for $(basename "$file"): expected $expected, got $actual. The download was deleted."
  fi
}

extract_zip() {
  local archive="$1" dest="$2"
  if need unzip; then unzip -q "$archive" -d "$dest" || die "Could not extract $archive."; return 0; fi
  if need bsdtar; then bsdtar -xf "$archive" -C "$dest" || die "Could not extract $archive."; return 0; fi
  if need python3; then python3 -m zipfile -e "$archive" "$dest" || die "Could not extract $archive."; return 0; fi
  die "No zip extractor is available (tried unzip, bsdtar and python3)."
}

extract_archive() {
  local archive="$1" kind="$2" dest="$3"
  case "$kind" in
    tar.gz)
      need tar || die "tar is required to extract $archive."
      tar -xzf "$archive" -C "$dest" || die "Could not extract $archive."
      ;;
    zip) extract_zip "$archive" "$dest" ;;
    *) die "The bootstrap tool manifest requested an unrecognised archive kind: $kind" ;;
  esac
}

confirm() {
  local prompt="$1" answer=""
  if [ "$YES" = "1" ]; then return 0; fi
  if [ ! -r /dev/tty ]; then return 0; fi
  printf '\033[1;36m[flinttrade]\033[0m %s [Y/n] ' "$prompt" > /dev/tty
  IFS= read -r answer < /dev/tty || answer=""
  case "$(lowercase "$answer")" in
    ""|y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Owner-private web-install receipt.
#
# The uninstaller may only delete what an installer proved it wrote. This
# mirrors flinttrade-install.sh's shell receipt: an owner-only 0700 directory,
# an owner-only 0600 one-field-per-line file, and a SHA-256 of the launcher so
# the uninstaller can refuse to touch anything it did not create.
# ---------------------------------------------------------------------------

canonical_web_path() {
  local target="$1" parent
  if [ -d "$target" ]; then
    (cd -P "$target" 2>/dev/null && pwd -P)
    return
  fi
  parent="$(cd -P "$(dirname "$target")" 2>/dev/null && pwd -P)" || return 1
  printf '%s/%s' "${parent%/}" "$(basename "$target")"
}

receipt_safe_value() {
  case "$1" in
    *$'\n'*|*$'\r'*) die "Web-install receipt values must be single-line paths." ;;
  esac
}

ensure_web_receipt_storage() {
  local current="${HOME%/}" component candidate name
  for component in .local state flinttrade-web; do
    current="$current/$component"
    [ ! -L "$current" ] || die "Refusing web-install receipt storage through a symbolic-link path component: $current"
    if [ -e "$current" ]; then
      [ -d "$current" ] && [ -O "$current" ] \
        || die "Refusing web-install receipt storage through a non-owner-local path component: $current"
    fi
  done
  mkdir -p "$WEB_RECEIPT_DIR" || die "Could not create the private web-install receipt directory."
  [ -d "$WEB_RECEIPT_DIR" ] && [ ! -L "$WEB_RECEIPT_DIR" ] && [ -O "$WEB_RECEIPT_DIR" ] \
    || die "The web-install receipt directory is not an owner-local ordinary directory."
  chmod 0700 "$WEB_RECEIPT_DIR" || die "Could not make the web-install receipt directory private."
  for candidate in "$WEB_RECEIPT_DIR"/* "$WEB_RECEIPT_DIR"/.[!.]* "$WEB_RECEIPT_DIR"/..?*; do
    [ -e "$candidate" ] || [ -L "$candidate" ] || continue
    name="$(basename "$candidate")"
    case "$name" in
      web-install.receipt|.web-install.receipt.*) ;;
      *) die "Refusing to mix the web-install receipt with unrecognised state: $candidate" ;;
    esac
  done
}

write_web_install_receipt() {
  local canonical_shim canonical_source canonical_tools shim_hash receipt_tmp platform value
  ensure_web_receipt_storage
  [ -f "$SHIM_PATH" ] && [ ! -L "$SHIM_PATH" ] \
    || die "The installed launcher is not an ordinary web-install receipt candidate."
  canonical_shim="$(canonical_web_path "$SHIM_PATH")" \
    || die "Could not canonicalise the launcher for its web-install receipt."
  canonical_source="$(canonical_web_path "$SRC_DIR")" \
    || die "Could not canonicalise the managed source checkout for its web-install receipt."
  canonical_tools="$(canonical_web_path "$TOOLS_ROOT")" || canonical_tools="$TOOLS_ROOT"
  shim_hash="$(lowercase "$(sha256_of "$canonical_shim")")"
  platform="$(uname -s)"
  for value in "$platform" "$canonical_shim" "$shim_hash" "$canonical_source" "$canonical_tools"; do
    receipt_safe_value "$value"
  done
  receipt_tmp="$(mktemp "$WEB_RECEIPT_DIR/.web-install.receipt.XXXXXX")" \
    || die "Could not stage the web-install receipt."
  TMP_DIRS+=("$receipt_tmp")
  chmod 0600 "$receipt_tmp" || die "Could not make the staged web-install receipt private."
  {
    printf '%s\n' \
      'format=flinttrade-web-install-v1' \
      "platform=$platform" \
      "shim=$canonical_shim" \
      "shim_sha256=$shim_hash" \
      "shortcut=" \
      "source=$canonical_source" \
      "tools=$canonical_tools"
  } > "$receipt_tmp" || die "Could not write the web-install receipt."
  mv "$receipt_tmp" "$WEB_RECEIPT_PATH" \
    || die "Could not publish the web-install receipt at $WEB_RECEIPT_PATH."
  say "Recorded the web-install receipt at $WEB_RECEIPT_PATH."
}

# ---------------------------------------------------------------------------
# Guards for the source tree this installer shares with the desktop shell.
# ---------------------------------------------------------------------------

warn_source_dir_provenance() {
  [ "$SRC_DIR_SOURCE" = "FLINTTRADE_SRC_DIR" ] || return 0
  warn "FLINTTRADE_SRC_DIR is set, so this installer would manage $SRC_DIR as its web source checkout."
  warn "flinttrade-install.sh reads that same variable as the CONTRIBUTOR source-build checkout"
  warn "(default $MANAGED_ROOT/source-build/FlintTrade). This installer fetches, hard-resets and can"
  warn "replace the directory it is given — including a multi-gigabyte built checkout."
  warn "Set FLINTTRADE_WEB_SRC_DIR, or pass --src, to choose the web source checkout explicitly."
  [ "$DRY_RUN" = "1" ] && return 0
  if ! confirm "Continue with $SRC_DIR as the managed web source checkout?"; then
    die "Cancelled at the source-checkout confirmation; nothing was changed."
  fi
}

assert_desktop_not_operating() {
  case "${SRC_DIR%/}" in
    "$DESKTOP_ACTIVE_SOURCE"|"$DESKTOP_ACTIVE_SOURCE"/*) ;;
    *) return 0 ;;
  esac
  [ -e "$DESKTOP_OPERATION_LEASE" ] || [ -L "$DESKTOP_OPERATION_LEASE" ] || return 0
  warn "FlintTrade Desktop holds its bootstrap source-operation lease at $DESKTOP_OPERATION_LEASE."
  warn "That lease guards every mutation of $SRC_DIR, which the desktop shell treats as its active source."
  if [ "$DRY_RUN" = "1" ]; then
    warn "DRY-RUN: a real run would refuse to touch that checkout until the desktop shell has quit."
    return 0
  fi
  die "Quit FlintTrade Desktop and re-run; this installer never takes the desktop's lease itself."
}

# ---------------------------------------------------------------------------
# Minimal JSON reader. Emits "<dotted path><TAB><scalar>" for every scalar in
# the document so the pinned versions, URLs and digests are read from the
# manifest itself rather than duplicated here.
# ---------------------------------------------------------------------------

json_scalars() {
  awk '
    function unescape(s,   out, i, c, n) {
      out = ""
      n = length(s)
      for (i = 1; i <= n; i++) {
        c = substr(s, i, 1)
        if (c != "\\") { out = out c; continue }
        i++
        c = substr(s, i, 1)
        if (c == "n") { out = out "\n" }
        else if (c == "t") { out = out "\t" }
        else if (c == "r") { out = out "\r" }
        else if (c == "b") { out = out "\b" }
        else if (c == "f") { out = out "\f" }
        else if (c == "u") { out = out "?"; i += 4 }
        else { out = out c }
      }
      return out
    }
    { doc = doc $0 "\n" }
    END {
      n = length(doc)
      i = 1
      depth = 0
      pending = ""
      while (i <= n) {
        c = substr(doc, i, 1)
        if (c == " " || c == "\t" || c == "\n" || c == "\r" || c == ":") { i++; continue }
        if (c == ",") {
          if (kind[depth] == "arr") {
            slot[depth] = slot[depth] + 1
            pending = base[depth] "." slot[depth]
          } else {
            expectkey[depth] = 1
          }
          i++
          continue
        }
        if (c == "{" || c == "[") {
          depth++
          base[depth] = pending
          if (c == "{") {
            kind[depth] = "obj"
            expectkey[depth] = 1
          } else {
            kind[depth] = "arr"
            slot[depth] = 0
            pending = base[depth] ".0"
          }
          i++
          continue
        }
        if (c == "}" || c == "]") {
          depth--
          if (depth >= 0) { expectkey[depth] = 1 }
          i++
          continue
        }
        if (c == "\"") {
          i++
          raw = ""
          while (i <= n) {
            c = substr(doc, i, 1)
            if (c == "\\") { raw = raw substr(doc, i, 2); i += 2; continue }
            if (c == "\"") { i++; break }
            raw = raw c
            i++
          }
          if (kind[depth] == "obj" && expectkey[depth] == 1) {
            expectkey[depth] = 0
            value = unescape(raw)
            if (base[depth] == "") { pending = value } else { pending = base[depth] "." value }
          } else {
            printf "%s\t%s\n", pending, unescape(raw)
          }
          continue
        }
        token = ""
        while (i <= n) {
          c = substr(doc, i, 1)
          if (c == "," || c == "}" || c == "]" || c == " " || c == "\t" || c == "\n" || c == "\r") { break }
          token = token c
          i++
        }
        if (token != "") { printf "%s\t%s\n", pending, token }
      }
    }
  '
}

manifest_value() {
  local path="$1" value
  value="$(printf '%s\n' "$MANIFEST_FLAT" | awk -F '\t' -v want="$path" '
    $1 == want { print $2; found = 1; exit }
    END { if (found != 1) { exit 1 } }
  ')" || die "The bootstrap tool manifest has no '$path' entry for this machine."
  if [ -z "$value" ]; then die "The bootstrap tool manifest has an empty '$path' entry."; fi
  printf '%s' "$value"
}

# ---------------------------------------------------------------------------
# 2. Preflight — what is already on this machine?
# ---------------------------------------------------------------------------

probe_first_line() {
  local output
  output="$("$@" 2>/dev/null | head -n 1)" || true
  printf '%s' "$output"
}

preflight_report() {
  if need git; then HOST_GIT_VERSION="$(probe_first_line git --version)"; fi
  if need uv; then HOST_UV_VERSION="$(probe_first_line uv --version)"; fi
  if need node; then HOST_NODE_VERSION="$(probe_first_line node --version)"; fi
  if need pnpm; then HOST_PNPM_VERSION="$(probe_first_line pnpm --version)"; fi
  if need python3; then
    HOST_PYTHON_VERSION="$(probe_first_line python3 --version)"
  elif need python; then
    HOST_PYTHON_VERSION="$(probe_first_line python --version)"
  fi
  say "Preflight — tools already present on this machine:"
  say "  git    : ${HOST_GIT_VERSION:-not found}"
  say "  uv     : ${HOST_UV_VERSION:-not found}"
  say "  node   : ${HOST_NODE_VERSION:-not found}"
  say "  pnpm   : ${HOST_PNPM_VERSION:-not found}"
  say "  python : ${HOST_PYTHON_VERSION:-not found}"
  say "A host tool is reused only when it matches the pinned version exactly; anything else is provisioned privately."
}

resolve_corepack_js_for_node() {
  local node_bin="$1" root
  root="$(cd -P "$(dirname "$node_bin")/.." 2>/dev/null && pwd -P)" || return 1
  printf '%s/lib/node_modules/corepack/dist/corepack.js' "$root"
}

# Decide which host tools may be reused, given the pins read from the manifest.
resolve_host_reuse() {
  local pinned_uv="$1" pinned_node="$2" candidate corepack_js reported
  REUSE_UV=""
  REUSE_NODE=""
  REUSE_COREPACK_JS=""
  if [ -n "$HOST_UV_VERSION" ]; then
    reported="$(printf '%s' "$HOST_UV_VERSION" | awk '{print $2}')"
    if [ "$reported" = "$pinned_uv" ]; then
      candidate="$(command -v uv)"
      REUSE_UV="$candidate"
    fi
  fi
  if [ -n "$HOST_NODE_VERSION" ]; then
    reported="${HOST_NODE_VERSION#v}"
    if [ "$reported" = "$pinned_node" ]; then
      candidate="$(command -v node)"
      corepack_js="$(resolve_corepack_js_for_node "$candidate" || true)"
      if [ -n "$corepack_js" ] && [ -f "$corepack_js" ]; then
        REUSE_NODE="$candidate"
        REUSE_COREPACK_JS="$corepack_js"
      else
        warn "The host Node $reported matches the pin but carries no Corepack JavaScript; provisioning the verified Node instead."
      fi
    fi
  fi
}

# ---------------------------------------------------------------------------
# 3. Source acquisition
# ---------------------------------------------------------------------------

dir_is_empty() {
  local entry
  for entry in "$1"/* "$1"/.[!.]* "$1"/..?*; do
    if [ -e "$entry" ] || [ -L "$entry" ]; then return 1; fi
  done
  return 0
}

assert_source_dir_safe() {
  if [ ! -e "$SRC_DIR" ]; then return 0; fi
  if [ -L "$SRC_DIR" ]; then die "Refusing a symbolic-link managed source path: $SRC_DIR"; fi
  if [ ! -d "$SRC_DIR" ]; then die "Refusing a non-directory managed source path: $SRC_DIR"; fi
  if dir_is_empty "$SRC_DIR"; then return 0; fi
  if [ -f "$SRC_DIR/package.json" ] && [ -f "$SRC_DIR/pyproject.toml" ]; then return 0; fi
  die "Refusing to overwrite $SRC_DIR because it is not an empty directory or a FlintTrade checkout."
}

validate_source_origin() {
  local origin
  if [ ! -d "$SRC_DIR/.git" ]; then return 0; fi
  origin="$(git -C "$SRC_DIR" remote get-url origin 2>/dev/null || true)"
  case "$origin" in
    "$REPO_URL"|"${REPO_URL%.git}"|"") ;;
    *) die "Refusing to update $SRC_DIR because its origin is not the official HTTPS FlintTrade repository." ;;
  esac
}

archive_url_for_ref() {
  local ref="$1"
  if [ -z "$ref" ] || [ "$ref" = "$DEFAULT_BRANCH" ]; then
    printf '%s/refs/heads/%s' "$ARCHIVE_BASE_URL" "$DEFAULT_BRANCH"
    return 0
  fi
  case "$ref" in
    v[0-9]*) printf '%s/refs/tags/%s' "$ARCHIVE_BASE_URL" "$ref" ;;
    *) printf '%s/refs/heads/%s' "$ARCHIVE_BASE_URL" "$ref" ;;
  esac
}

acquire_source_with_git() {
  local ref="$1"
  validate_source_origin
  if [ -d "$SRC_DIR/.git" ]; then
    say "Refreshing the managed source checkout at $SRC_DIR (git fetch + reset)..."
    git -C "$SRC_DIR" fetch --prune --tags "$REPO_URL" "$ref" \
      || die "Could not fetch '$ref' from $REPO_URL."
    git -C "$SRC_DIR" reset --hard FETCH_HEAD \
      || die "Could not reset the managed source checkout to '$ref'."
  else
    say "Cloning FlintTrade ($ref) into $SRC_DIR..."
    mkdir -p "$(dirname "$SRC_DIR")"
    rm -rf "$SRC_DIR"
    git clone --depth 1 --branch "$ref" "$REPO_URL" "$SRC_DIR" \
      || die "Could not clone $REPO_URL at '$ref'."
  fi
}

acquire_source_with_archive() {
  local ref="$1" url staging archive extracted
  url="$(archive_url_for_ref "$ref")"
  assert_trusted_url "$url"
  say "git is not installed; downloading the source archive instead ($url)..."
  staging="$(mktemp -d "${TMPDIR:-/tmp}/flinttrade-source.XXXXXX")" \
    || die "Could not create a source staging directory."
  TMP_DIRS+=("$staging")
  archive="$staging/source.zip"
  download_to "$url" "$archive"
  mkdir -p "$staging/unpacked"
  extract_zip "$archive" "$staging/unpacked"
  extracted="$(find "$staging/unpacked" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [ -z "$extracted" ]; then die "The downloaded source archive did not contain a checkout directory."; fi
  if [ ! -f "$extracted/pyproject.toml" ] || [ ! -f "$extracted/package.json" ]; then
    die "The downloaded source archive is not a FlintTrade checkout."
  fi
  say "Replacing $SRC_DIR with the downloaded checkout (a git-less refresh rebuilds dependencies)."
  mkdir -p "$(dirname "$SRC_DIR")"
  rm -rf "$SRC_DIR"
  mv "$extracted" "$SRC_DIR" || die "Could not publish the downloaded checkout at $SRC_DIR."
}

acquire_source() {
  local ref="${REF:-$DEFAULT_BRANCH}"
  warn_source_dir_provenance
  assert_desktop_not_operating
  assert_source_dir_safe
  if [ "$DRY_RUN" = "1" ]; then
    if need git; then
      say "DRY-RUN: would clone or fetch+reset $REPO_URL at '$ref' into $SRC_DIR"
    else
      say "DRY-RUN: would download $(archive_url_for_ref "$ref") and extract it into $SRC_DIR"
    fi
    return 0
  fi
  if need git; then
    acquire_source_with_git "$ref"
  else
    acquire_source_with_archive "$ref"
  fi
  if [ ! -f "$SRC_DIR/$MANIFEST_RELATIVE" ]; then
    die "The checkout at $SRC_DIR has no $MANIFEST_RELATIVE; it is not a supported FlintTrade revision."
  fi
  if [ ! -f "$SRC_DIR/$BOOTSTRAP_RELATIVE" ]; then
    die "The checkout at $SRC_DIR has no $BOOTSTRAP_RELATIVE; it is not a supported FlintTrade revision."
  fi
}

# ---------------------------------------------------------------------------
# 5. Verified tool provisioning, laid out exactly like the desktop bootstrap:
#    <tools-root>/<tool>/<version>/<target>
# ---------------------------------------------------------------------------

desktop_marker_executable_sha256() {
  local marker="$1"
  json_scalars < "$marker" | awk -F '\t' '$1 == "executableSha256" { print $2; exit }'
}

install_tool() {
  local tool="$1"
  local version url sha archive_kind executable install_root marker desktop_marker legacy_desktop_marker
  local proven_marker archive staging archive_name recorded actual
  version="$(manifest_value "$tool.version")"
  url="$(manifest_value "$tool.assets.$TARGET.url")"
  sha="$(lowercase "$(manifest_value "$tool.assets.$TARGET.sha256")")"
  archive_kind="$(manifest_value "$tool.assets.$TARGET.archive")"
  executable="$(manifest_value "$tool.assets.$TARGET.executable")"
  assert_trusted_url "$url"
  assert_sha256_shape "$sha"
  assert_confined_relative_path "$executable"

  install_root="$TOOLS_ROOT/$tool/$version/$TARGET"
  marker="$install_root.flinttrade-web-verified"
  # The Electron bootstrap writes its verification marker INSIDE the install
  # root (packages/apps/desktop/electron/bootstrap.ts: verifiedMarker =
  # path.join(installRoot, TOOL_VERIFICATION_MARKER)). The sibling form is only
  # its legacyVerifiedMarker and nothing writes it any more, so read the real
  # one first and keep the legacy path as a fallback.
  desktop_marker="$install_root/.flinttrade-tool-verified.json"
  legacy_desktop_marker="$install_root.flinttrade-tool-verified.json"
  TOOL_EXECUTABLE="$install_root/$executable"

  if [ -f "$marker" ] && [ -x "$TOOL_EXECUTABLE" ]; then
    recorded="$(cat "$marker" 2>/dev/null || true)"
    if [ "$recorded" = "$sha" ]; then
      say "Reusing the verified $tool $version already provisioned at $install_root."
      return 0
    fi
  fi

  proven_marker=""
  if [ -f "$desktop_marker" ] && [ ! -L "$desktop_marker" ]; then
    proven_marker="$desktop_marker"
  elif [ -f "$legacy_desktop_marker" ] && [ ! -L "$legacy_desktop_marker" ]; then
    proven_marker="$legacy_desktop_marker"
  fi
  if [ -n "$proven_marker" ]; then
    if [ ! -x "$TOOL_EXECUTABLE" ]; then
      die "The desktop-provisioned $tool state at $install_root carries a verification marker but no usable executable. It was preserved; run the uninstaller or remove it yourself, then re-run."
    fi
    recorded="$(lowercase "$(desktop_marker_executable_sha256 "$proven_marker")")"
    actual="$(lowercase "$(sha256_of "$TOOL_EXECUTABLE")")"
    if [ -n "$recorded" ] && [ "$recorded" = "$actual" ]; then
      say "Reusing the desktop-provisioned $tool $version at $install_root."
      return 0
    fi
    die "Existing $tool state at $install_root failed verification and was preserved. Remove it or run the uninstaller, then re-run."
  fi

  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would download $url"
    say "DRY-RUN: would verify sha256 $sha, then extract into $install_root"
    return 0
  fi

  archive_name="$(basename "${url%%\?*}")"
  mkdir -p "$TOOLS_ROOT/.downloads" "$TOOLS_ROOT/$tool/$version"
  archive="$TOOLS_ROOT/.downloads/$archive_name"
  rm -f "$archive"
  say "Downloading $tool $version..."
  download_to "$url" "$archive"
  verify_sha256 "$archive" "$sha"
  say "Verified the SHA-256 digest pinned by the bootstrap tool manifest."

  staging="$(mktemp -d "$TOOLS_ROOT/$tool/$version/.$TARGET.extracting.XXXXXX")" \
    || die "Could not create a staging directory for $tool $version."
  TMP_DIRS+=("$staging")
  extract_archive "$archive" "$archive_kind" "$staging"
  if [ ! -f "$staging/$executable" ]; then
    die "The verified $tool archive did not contain its expected executable ($executable)."
  fi
  chmod +x "$staging/$executable" 2>/dev/null || true
  if [ -e "$desktop_marker" ] || [ -L "$desktop_marker" ] \
      || [ -e "$legacy_desktop_marker" ] || [ -L "$legacy_desktop_marker" ]; then
    die "A desktop tool-verification marker appeared at $install_root while this installer was extracting $tool $version; refusing to delete a verified tool root."
  fi
  rm -f "$marker"
  rm -rf "$install_root"
  mv "$staging" "$install_root" || die "Could not publish $tool $version at $install_root."
  printf '%s\n' "$sha" > "$marker"
  rm -f "$archive"
  if [ ! -x "$TOOL_EXECUTABLE" ]; then
    die "The provisioned $tool $version is not executable at $TOOL_EXECUTABLE."
  fi
}

# ---------------------------------------------------------------------------
# 6. Corepack JavaScript, resolved from the provisioned Node exactly the way
#    the Electron bootstrap resolves it.
# ---------------------------------------------------------------------------

corepack_js_for_provisioned_node() {
  local node_executable="$1" root
  root="$(dirname "$(dirname "$node_executable")")"
  printf '%s/lib/node_modules/corepack/dist/corepack.js' "$root"
}

# ---------------------------------------------------------------------------
# 8. Launcher shim
# ---------------------------------------------------------------------------

install_launcher_shim() {
  local python="$1" staged
  mkdir -p "$SHIM_DIR" || die "Could not create $SHIM_DIR."
  if [ -L "$SHIM_PATH" ]; then die "Refusing to replace a symbolic-link launcher at $SHIM_PATH."; fi
  staged="$(mktemp "$SHIM_DIR/.flinttrade-shim.XXXXXX")" || die "Could not stage the launcher shim."
  TMP_DIRS+=("$staged")
  cat > "$staged" <<EOF
#!/bin/sh
# FlintTrade launcher shim — generated by flinttrade-web-install.sh. Do not edit.
# Re-run the web installer to regenerate it after moving the managed checkout.
set -e
cd "$SRC_DIR"
exec "$python" scripts/ft.py "\$@"
EOF
  chmod 0755 "$staged"
  mv "$staged" "$SHIM_PATH" || die "Could not install the launcher at $SHIM_PATH."
  case ":${PATH:-}:" in
    *":$SHIM_DIR:"*) ;;
    *) warn "$SHIM_DIR is not on PATH; add it, or run the launcher as $SHIM_PATH." ;;
  esac
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
  local pinned_uv pinned_node pinned_pnpm uv_url node_url bootstrap venv_python
  say "FlintTrade web-app installer — no prior tooling required."
  if [ "$DRY_RUN" = "1" ]; then say "Dry run: nothing will be downloaded, built or installed."; fi

  TARGET="$(detect_target)"
  say "Detected bootstrap target: $TARGET"

  preflight_report

  acquire_source

  if [ "$DRY_RUN" = "1" ] && [ ! -f "$SRC_DIR/$MANIFEST_RELATIVE" ]; then
    say "DRY-RUN: would read the pinned tool versions and digests from $MANIFEST_RELATIVE in the checkout."
    say "DRY-RUN: would delegate the build to $BOOTSTRAP_RELATIVE, then install the launcher at $SHIM_PATH."
    report_paths
    return 0
  fi

  MANIFEST_FLAT="$(json_scalars < "$SRC_DIR/$MANIFEST_RELATIVE")"
  if [ -z "$MANIFEST_FLAT" ]; then die "Could not read $MANIFEST_RELATIVE from the checkout."; fi
  pinned_uv="$(manifest_value "uv.version")"
  pinned_node="$(manifest_value "node.version")"
  pinned_pnpm="$(manifest_value "pnpm.version")"
  if [ "$pinned_pnpm" != "$PINNED_PNPM_VERSION" ]; then
    die "The checkout pins pnpm $pinned_pnpm; this installer only supports the $PINNED_PNPM_VERSION bootstrap entrypoint."
  fi
  uv_url="$(manifest_value "uv.assets.$TARGET.url")"
  node_url="$(manifest_value "node.assets.$TARGET.url")"

  resolve_host_reuse "$pinned_uv" "$pinned_node"

  say "Pinned toolchain for $TARGET: uv $pinned_uv, Node $pinned_node, pnpm $pinned_pnpm."
  if [ -n "$REUSE_UV" ]; then
    say "  uv   : reusing the exactly-matching host uv at $REUSE_UV"
  else
    say "  uv   : will download $uv_url"
  fi
  if [ -n "$REUSE_NODE" ]; then
    say "  node : reusing the exactly-matching host Node at $REUSE_NODE"
  else
    say "  node : will download $node_url"
  fi
  say "  pnpm : provided by Corepack from the verified Node install (no separate download)"
  say "  python 3.12 : installed by uv into $TOOLS_ROOT/python"
  if ! confirm "Proceed with the downloads above?"; then
    die "Cancelled at the download confirmation; nothing was changed."
  fi

  if [ -n "$REUSE_UV" ]; then
    RESOLVED_UV="$REUSE_UV"
  else
    install_tool uv
    RESOLVED_UV="$TOOL_EXECUTABLE"
  fi
  if [ -n "$REUSE_NODE" ]; then
    RESOLVED_NODE="$REUSE_NODE"
    RESOLVED_COREPACK_JS="$REUSE_COREPACK_JS"
  else
    install_tool node
    RESOLVED_NODE="$TOOL_EXECUTABLE"
    RESOLVED_COREPACK_JS="$(corepack_js_for_provisioned_node "$RESOLVED_NODE")"
  fi

  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would run $BOOTSTRAP_RELATIVE with the six verified bootstrap arguments."
    say "DRY-RUN: would install the launcher at $SHIM_PATH."
    report_paths
    return 0
  fi

  if [ ! -f "$RESOLVED_COREPACK_JS" ]; then
    die "The verified Node install carries no Corepack JavaScript at $RESOLVED_COREPACK_JS."
  fi

  bootstrap="$SRC_DIR/$BOOTSTRAP_RELATIVE"
  say "Building FlintTrade with the repository's own bootstrap entrypoint. This takes a few minutes on first run."
  sh "$bootstrap" \
    "$SRC_DIR" \
    "$RESOLVED_UV" \
    "$RESOLVED_NODE" \
    "$RESOLVED_COREPACK_JS" \
    "$TOOLS_ROOT" \
    "$pinned_pnpm" \
    || die "The FlintTrade bootstrap build failed; nothing was installed."

  venv_python="$SRC_DIR/.venv/bin/python"
  if [ ! -x "$venv_python" ]; then
    die "The bootstrap completed without a managed interpreter at $venv_python."
  fi
  RESOLVED_PYTHON="$venv_python"
  install_launcher_shim "$RESOLVED_PYTHON"
  say "Installed the launcher at $SHIM_PATH."
  write_web_install_receipt

  report_paths
  offer_to_start
}

report_paths() {
  say "----------------------------------------------------------------"
  say "Workspace and data : $(workspace_dir)"
  say "Verified tools     : $TOOLS_ROOT"
  say "Managed source     : $SRC_DIR"
  say "Launcher           : $SHIM_PATH  (also: flinttrade <subcommand>)"
  say "Install receipt    : $WEB_RECEIPT_PATH  (the uninstaller removes only what this proves)"
  say "Runner             : python scripts/ft.py <start|stop|restart|status|dev|setup|test|lint|clean|version|help|desktop-test|desktop-build|desktop-package|desktop-dev>"
  say "Open FlintTrade at : $BACKEND_URL"
  say "Uninstall          : $UNINSTALL_COMMAND"
  say "                     (add --purge to delete the workspace, tools and source too)"
  say "----------------------------------------------------------------"
}

offer_to_start() {
  if [ "$NO_LAUNCH" = "1" ]; then
    say "Not starting FlintTrade (--no-launch). Start it later with: flinttrade start"
    return 0
  fi
  if ! confirm "Start FlintTrade now?"; then
    say "Not started. Start it later with: flinttrade start"
    return 0
  fi
  say "Starting FlintTrade — open $BACKEND_URL in your browser. Press Ctrl-C to stop."
  "$SHIM_PATH" start
}

main "$@"

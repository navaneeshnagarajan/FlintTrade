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
PINNED_PNPM_VERSION="10.34.5"
BACKEND_URL="http://127.0.0.1:5100"
UNINSTALL_COMMAND="curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash"
MANAGED_ROOT="$HOME/.flinttrade"
TOOLS_ROOT="$MANAGED_ROOT/tools"
# The Electron desktop shell resolves exactly these two paths
# (packages/apps/desktop/electron/paths.ts) and guards every mutation of the
# active source with an operation-lease DIRECTORY created by its bootstrap
# (packages/apps/desktop/electron/bootstrap.ts, acquireOperationLease in
# bootstrap-io.ts).
#
# That lease is deliberately NOT a mutual-exclusion primitive an outside process
# can hold: on acquisition the desktop treats any lease it finds as recoverable
# stale evidence, waits only for the process records INSIDE it, then quarantines
# and deletes it. A lease carrying nothing but an owner.json is therefore stolen
# immediately, and the only records the desktop respects are POSIX
# process-group / Windows supervisor files bound to a containment token minted
# by the Electron singleton. A shell installer piped through `curl | bash` is
# not even a process-group leader, so it cannot write one honestly.
#
# So this installer never shares the desktop's active source tree. It keeps its
# own checkout under $WEB_SOURCE_ROOT and refuses a --src that would aim it at
# the desktop's, which is what makes both installers safe in either order.
DESKTOP_SOURCE_ROOT="$MANAGED_ROOT/src"
DESKTOP_ACTIVE_SOURCE="$DESKTOP_SOURCE_ROOT/FlintTrade"
DESKTOP_OPERATION_LEASE="$DESKTOP_SOURCE_ROOT/.flinttrade-bootstrap-operation.lock"
WEB_SOURCE_ROOT="$MANAGED_ROOT/web-src"
WEB_ACTIVE_SOURCE="$WEB_SOURCE_ROOT/FlintTrade"
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
  SRC_DIR="$WEB_ACTIVE_SOURCE"
fi
# The Electron desktop installer owns ~/.local/bin/flinttrade (see
# preflight_linux_integrations in flinttrade-install.sh, which refuses to
# replace that file unless its own shell receipt proves the current contents).
# Squatting it made a web install silently repoint the desktop entry and break
# every later desktop update, so the web launcher has its own name and the
# desktop's is never touched.
SHIM_DIR="$HOME/.local/bin"
SHIM_PATH="$SHIM_DIR/flinttrade-web"
# Where earlier revisions of this installer put the launcher. Kept only so a
# re-run can retire a shim its own receipt still proves it wrote.
LEGACY_SHIM_PATH="$SHIM_DIR/flinttrade"
# Owner-private receipt for everything this installer writes outside the
# managed root. The uninstaller may only delete what an installer proved it
# created, exactly as flinttrade-install.sh proves the Electron shell.
WEB_RECEIPT_DIR="$HOME/.local/state/flinttrade-web"
WEB_RECEIPT_PATH="$WEB_RECEIPT_DIR/web-install.receipt"
# The Electron desktop installer's own receipt (flinttrade-install.sh). It is
# read here only as evidence that the desktop shell is installed on this
# machine; this installer never writes, moves or removes it.
DESKTOP_SHELL_RECEIPT_PATH="$HOME/.local/state/flinttrade/shell-install.receipt"
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
# Set when repository markers — which every contributor clone carries — are the
# only identity proof for $SRC_DIR. They authorise an in-place 'git fetch +
# reset' and never the recursive replacement a git-less refresh performs.
SOURCE_UPDATE_ONLY=0
# Set to the destination when this run moved a legacy web checkout out of the
# desktop shell's source root; the receipt still names the old path until it is
# rewritten at the end of the run.
MIGRATED_WEB_SOURCE=""
# Why the web-install receipt storage may not be trusted, set by
# web_receipt_storage_trusted.
WEB_RECEIPT_STORAGE_PROBLEM=""

say()  { printf '\033[1;36m[flinttrade]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[flinttrade]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[flinttrade]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1; }
lowercase() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

usage() {
  cat <<'USAGE'
FlintTrade one-line web-app installer (macOS + Linux)

Provisions a verified uv + Node toolchain, builds FlintTrade from a managed
source checkout, and installs a 'flinttrade-web' launcher. No prior tooling
needed. The FlintTrade Desktop shell is a separate install with its own
launcher, source checkout and uninstall receipt; neither one touches the
other's files, so the two can be installed in either order.

Flags:
  --ref <git-ref>   Branch, tag or commit to install (default: main)
  --src <dir>       Managed WEB source checkout (default: ~/.flinttrade/web-src/FlintTrade).
                    This is neither the contributor source-build checkout that
                    flinttrade-install.sh manages at ~/.flinttrade/source-build/FlintTrade
                    nor the desktop shell's active source at
                    ~/.flinttrade/src/FlintTrade, which is refused outright.
                    An existing directory is REPLACED only when this installer's
                    own receipt names it. A clean FlintTrade Git checkout it
                    cannot claim is updated in place instead (git fetch + reset);
                    anything else is refused, so a typo cannot destroy unrelated
                    source.
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
  if [ ! -r /dev/tty ]; then
    die "Non-interactive session: cannot ask '$prompt'. Re-run with --yes (or FLINTTRADE_YES=1) to confirm every step."
  fi
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

# Canonicalise a path whose parents need not exist yet, the way
# canonical_workspace_path in scripts/reset-flinttrade-state.sh does before
# anything destructive touches the result: 'cd -P' resolves every symbolic link
# and '.'/'..' in the deepest part that does exist, and the components below it
# — which cannot be symbolic links, because they do not exist — are then
# normalised lexically. Never fails: an unresolvable path canonicalises to its
# own normalised spelling so the comparisons below still have two values.
canonical_overlap_path() {
  local target="$1" head="" tail="" rest component resolved
  case "$target" in
    /*) ;;
    *) target="$(pwd -P)/$target" ;;
  esac
  head="$target"
  while [ ! -d "$head" ] && [ "$head" != "/" ] && [ -n "$head" ]; do
    tail="$(basename "$head")${tail:+/$tail}"
    head="$(dirname "$head")"
  done
  resolved="$(cd -P "$head" 2>/dev/null && pwd -P)" || resolved=""
  [ -n "$resolved" ] || resolved="$head"
  rest="$tail"
  while [ -n "$rest" ]; do
    component="${rest%%/*}"
    if [ "$component" = "$rest" ]; then rest=""; else rest="${rest#*/}"; fi
    case "$component" in
      ""|".") ;;
      "..") resolved="$(dirname "$resolved")" ;;
      *) resolved="${resolved%/}/$component" ;;
    esac
  done
  case "$resolved" in
    /) printf '/' ;;
    *) printf '%s' "${resolved%/}" ;;
  esac
}

private_mode() {
  /usr/bin/stat -c '%a' "$1" 2>/dev/null || /usr/bin/stat -f '%Lp' "$1" 2>/dev/null
}

receipt_safe_value() {
  case "$1" in
    *$'\n'*|*$'\r'*) die "Web-install receipt values must be single-line paths." ;;
  esac
}

# Every component of the receipt directory must be an owner-local, non-symlink
# directory. Both the writer below and every trusted READ of the receipt go
# through this one check, so the installer can never accept a receipt it would
# have refused to write.
web_receipt_storage_trusted() {
  local current="${HOME%/}" component
  WEB_RECEIPT_STORAGE_PROBLEM=""
  for component in .local state flinttrade-web; do
    current="$current/$component"
    if [ -L "$current" ]; then
      WEB_RECEIPT_STORAGE_PROBLEM="a symbolic-link path component: $current"
      return 1
    fi
    if [ -e "$current" ] && { [ ! -d "$current" ] || [ ! -O "$current" ]; }; then
      WEB_RECEIPT_STORAGE_PROBLEM="a non-owner-local path component: $current"
      return 1
    fi
  done
  return 0
}

# One field from the web-install receipt, and only when the receipt proves
# itself exactly as flinttrade-uninstall.sh's read_web_receipt requires: an
# owner-local 0700 directory reached through owner-local non-symlink
# components, an owner-local 0600 ordinary file, and the v1 format line. The
# receipt authorises destructive replacement, so a second, weaker reader would
# simply be the way round the strict one.
web_receipt_field() {
  local want="$1" line index=0 value=""
  web_receipt_storage_trusted || return 1
  [ -d "$WEB_RECEIPT_DIR" ] && [ ! -L "$WEB_RECEIPT_DIR" ] && [ -O "$WEB_RECEIPT_DIR" ] || return 1
  [ "$(private_mode "$WEB_RECEIPT_DIR")" = "700" ] || return 1
  [ -f "$WEB_RECEIPT_PATH" ] && [ ! -L "$WEB_RECEIPT_PATH" ] && [ -O "$WEB_RECEIPT_PATH" ] || return 1
  [ "$(private_mode "$WEB_RECEIPT_PATH")" = "600" ] || return 1
  while IFS= read -r line; do
    index=$((index + 1))
    if [ "$index" = "1" ]; then
      [ "$line" = "format=flinttrade-web-install-v1" ] || return 1
      continue
    fi
    case "$line" in "$want="*) value="${line#"$want="}" ;; esac
  done < "$WEB_RECEIPT_PATH"
  [ -n "$value" ] || return 1
  printf '%s' "$value"
}

ensure_web_receipt_storage() {
  local candidate name
  web_receipt_storage_trusted \
    || die "Refusing web-install receipt storage through $WEB_RECEIPT_STORAGE_PROBLEM"
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

# The desktop's active source may never be this installer's source, at any
# point in the run.
#
# Probing the lease once and then proceeding was not a guard at all: the fetch,
# the hard reset and the multi-minute dependency build all run afterwards, and
# FlintTrade Desktop launched at any moment in that window acquires its own
# lease and mutates the very same checkout. Nor can this installer hold the
# lease for the whole build — see the DESKTOP_OPERATION_LEASE note at the top of
# this file for why a lease written by a shell script is one the desktop
# quarantines rather than respects. The only safe answer is separate trees.
# Both sides are canonicalised first. A lexical comparison of the raw --src
# string was no guard at all: '/home/u/./.flinttrade/src/FlintTrade', a trailing
# slash, '/home/u/x/../.flinttrade/src/FlintTrade' and any symlinked parent all
# spell the desktop's own tree while matching none of the globs below, so the
# installer went on to fetch, hard-reset and build inside it.
assert_desktop_source_not_shared() {
  local candidate desktop_root shared=0
  candidate="$(canonical_overlap_path "$SRC_DIR")"
  desktop_root="$(canonical_overlap_path "$DESKTOP_SOURCE_ROOT")"
  if [ "$candidate" = "$desktop_root" ]; then shared=1; fi
  # Inside the desktop tree, and — just as fatal — containing it: the git-less
  # refresh path removes SRC_DIR recursively, which would take the desktop
  # checkout with it.
  case "$candidate" in
    "$desktop_root"/*) shared=1 ;;
  esac
  case "$desktop_root" in
    "$candidate"/*) shared=1 ;;
  esac
  [ "$shared" = "1" ] || return 0
  warn "$SRC_DIR overlaps the FlintTrade Desktop shell's active source tree at $DESKTOP_ACTIVE_SOURCE."
  warn "The desktop guards every mutation of that tree with the bootstrap operation lease at"
  warn "$DESKTOP_OPERATION_LEASE, and only its own singleton can hold one: a lease written by this"
  warn "installer would be treated as stale evidence and deleted, so a desktop launched during the"
  warn "fetch or the multi-minute build would corrupt the checkout underneath it."
  die "Choose a source checkout outside $DESKTOP_SOURCE_ROOT (the default is $WEB_ACTIVE_SOURCE)."
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

file_contains() {
  local file="$1" needle="$2"
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  grep -Fq "$needle" "$file" 2>/dev/null
}

# The installer's own receipt is the ONLY proof that this installer created a
# directory: it was written by a previous run and names the exact directory that
# run managed. It is read through the strict web_receipt_field validation, so an
# unprivate or foreign-owned receipt can never authorise a deletion.
web_receipt_names_source() {
  local target="${1%/}" recorded
  recorded="$(web_receipt_field source)" || return 1
  [ "$target" = "${recorded%/}" ] && return 0
  [ "$(canonical_overlap_path "$target")" = "$(canonical_overlap_path "$recorded")" ]
}

# Repository identity, not project shape and NOT ownership. flint.toml is this
# repository's own project manifest and names the repository it belongs to; the
# workspace member sets name FlintTrade's own packages. Revisions that predate
# flint.toml are still recognised through the second pair.
#
# All of those files are checked into the repository, so every contributor clone
# on earth satisfies this — including one holding a week of uncommitted work.
# That is why the markers authorise only the in-place update in
# assert_source_dir_safe and never a recursive replacement.
flinttrade_source_markers_present() {
  local target="${1%/}"
  if file_contains "$target/flint.toml" "$REPO_SLUG"; then return 0; fi
  if file_contains "$target/pyproject.toml" "flinttrade-core" \
      && file_contains "$target/pnpm-workspace.yaml" "packages/apps/terminal"; then
    return 0
  fi
  return 1
}

# A git-less refresh runs 'rm -rf "$SRC_DIR"' before publishing the downloaded
# checkout, so this guard decides whether unrelated source is destroyed. Two
# separate questions decide it, and conflating them is what put a contributor's
# working clone at risk:
#
#   * is this directory FlintTrade's code?  Repository markers answer that, and
#     every clone of this repository carries them;
#   * did THIS installer create this directory?  Only its own receipt answers
#     that, and only that answer authorises a recursive replacement.
#
# So a receipt-proved directory may be replaced; a merely marker-proved one may
# only be updated in place with 'git fetch' + 'git reset --hard', and not even
# that while it holds uncommitted work. An empty or absent directory needs no
# proof — there is nothing there to destroy — and an unproven one is refused
# rather than emptied.
assert_source_dir_safe() {
  local dirty
  if [ ! -e "$SRC_DIR" ]; then return 0; fi
  if [ -L "$SRC_DIR" ]; then die "Refusing a symbolic-link managed source path: $SRC_DIR"; fi
  if [ ! -d "$SRC_DIR" ]; then die "Refusing a non-directory managed source path: $SRC_DIR"; fi
  if dir_is_empty "$SRC_DIR"; then return 0; fi
  if web_receipt_names_source "$SRC_DIR"; then return 0; fi
  # A tree this run has just moved out of the desktop source root was proved by
  # that same receipt a moment ago; the receipt keeps naming the old path until
  # it is rewritten at the end of the run.
  if [ -n "$MIGRATED_WEB_SOURCE" ] && [ "${SRC_DIR%/}" = "${MIGRATED_WEB_SOURCE%/}" ]; then return 0; fi
  if flinttrade_source_markers_present "$SRC_DIR"; then
    if ! need git; then
      warn "Refusing to replace $SRC_DIR — its FlintTrade markers prove the CODE is this"
      warn "repository's, not that this installer created the directory, and only a web-install"
      warn "receipt naming this exact path proves that."
      die "git is not installed here, so this checkout could only be replaced wholesale. Install git so it can be updated in place, or pass --src (or set FLINTTRADE_WEB_SRC_DIR) to a directory this installer manages."
    fi
    if [ ! -d "$SRC_DIR/.git" ]; then
      warn "Refusing to replace $SRC_DIR — its FlintTrade markers prove the CODE is this"
      warn "repository's, not that this installer created the directory, and only a web-install"
      warn "receipt naming this exact path proves that."
      die "It is not a Git checkout either, so it could only be replaced wholesale. Remove it yourself if you really meant that path, or pass --src (or set FLINTTRADE_WEB_SRC_DIR) to a directory this installer manages."
    fi
    if ! dirty="$(git -C "$SRC_DIR" status --porcelain 2>/dev/null)"; then
      warn "Refusing to update $SRC_DIR — 'git status' could not report whether it holds"
      warn "uncommitted work, and this installer runs 'git reset --hard' on it."
      die "Check that checkout by hand, or pass --src (or set FLINTTRADE_WEB_SRC_DIR) to a directory this installer manages."
    fi
    if [ -n "$dirty" ]; then
      warn "Refusing to update $SRC_DIR — it is a FlintTrade checkout with uncommitted changes,"
      warn "and no web-install receipt names it, so this installer cannot claim it created it."
      warn "The update runs 'git fetch' + 'git reset --hard', which would discard that work."
      die "Commit, stash or remove those changes, or pass --src (or set FLINTTRADE_WEB_SRC_DIR) to a directory this installer manages."
    fi
    SOURCE_UPDATE_ONLY=1
    say "No web-install receipt names $SRC_DIR, so it will be updated in place (git fetch + reset)"
    say "rather than replaced; its FlintTrade markers prove the code, not this installer's ownership."
    return 0
  fi
  warn "Refusing to replace $SRC_DIR — nothing there proves it is a FlintTrade checkout."
  warn "This installer deletes and republishes the directory it is given, so it replaces only a"
  warn "directory a web-install receipt of its own names at this exact path. A clean Git checkout"
  warn "carrying FlintTrade's identity — a flint.toml naming $REPO_SLUG, or FlintTrade's own"
  warn "workspace members in pyproject.toml and pnpm-workspace.yaml — is updated in place instead."
  die "Remove $SRC_DIR yourself if you really meant that path, or pass --src (or set FLINTTRADE_WEB_SRC_DIR) to the intended checkout."
}

# Evidence that the Electron desktop shell is installed on this machine. Its
# own receipt is the authoritative one; the application bundle, the Linux
# .desktop entry and the AppImage root are kept as fallbacks for a shell
# installed before receipts existed. ~/.local/bin/flinttrade is deliberately NOT
# in the list: that is exactly the path an earlier revision of THIS installer
# wrote its launcher to, so it proves nothing either way.
desktop_shell_appears_installed() {
  local candidate
  for candidate in \
    "$DESKTOP_SHELL_RECEIPT_PATH" \
    "/Applications/FlintTrade.app" \
    "$HOME/Applications/FlintTrade.app" \
    "$HOME/.local/opt/flinttrade" \
    "$HOME/.local/share/applications/flinttrade.desktop"; do
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then return 0; fi
  done
  return 1
}

# ---------------------------------------------------------------------------
# Upgrade path for machines installed by the revision that shared the desktop's
# source root.
#
# That revision defaulted the web source to $DESKTOP_ACTIVE_SOURCE, so a machine
# it installed still has a web-built checkout sitting in the tree the Electron
# desktop shell claims — the very overlap assert_desktop_source_not_shared now
# refuses outright. Retiring only the legacy launcher healed half of that and
# left the desktop and this installer fighting over one directory, which is the
# same class of failure the separate-trees rule exists to prevent.
#
# So move that checkout to the new web source root when the receipt proves this
# installer created it and nothing else can be claiming it, and otherwise leave
# it exactly where it is and say what has to happen and why. A tree that cannot
# be proved is never deleted, and never deleted at all: it is only ever moved.
# ---------------------------------------------------------------------------
migrate_legacy_web_source_checkout() {
  local recorded canonical_recorded desktop_root parent
  recorded="$(web_receipt_field source)" || return 0
  canonical_recorded="$(canonical_overlap_path "$recorded")"
  desktop_root="$(canonical_overlap_path "$DESKTOP_SOURCE_ROOT")"
  case "$canonical_recorded" in
    "$desktop_root"|"$desktop_root"/*) ;;
    *) return 0 ;;
  esac
  [ "${canonical_recorded}" != "$(canonical_overlap_path "$SRC_DIR")" ] || return 0
  [ -d "$recorded" ] && [ ! -L "$recorded" ] || return 0
  warn "This machine was installed by an earlier revision that built the web app inside the"
  warn "FlintTrade Desktop shell's own source root: $recorded"
  warn "The desktop claims that tree and guards it with a lease no script can hold, so leaving a"
  warn "web checkout there makes the two installs mutate one directory — and can leave the"
  warn "desktop shell unable to bootstrap at all."
  # Every refusal below is evaluated before the dry-run report, so --dry-run
  # never promises a move this installer would not make.
  if [ -e "$DESKTOP_OPERATION_LEASE" ] || [ -L "$DESKTOP_OPERATION_LEASE" ]; then
    warn "Leaving $recorded — the desktop bootstrap operation lease at $DESKTOP_OPERATION_LEASE"
    warn "says FlintTrade Desktop is working in that tree right now. Quit FlintTrade Desktop and"
    warn "re-run this installer to complete the move."
    return 0
  fi
  if desktop_shell_appears_installed; then
    warn "Leaving $recorded — the FlintTrade Desktop shell is installed on this machine, so that"
    warn "checkout may be the desktop's own rather than one this installer created, and this"
    warn "installer never moves a tree it cannot prove it owns alone."
    warn "Decide which checkout to keep, then either delete $recorded (the desktop rebuilds its"
    warn "own on next launch) or move it to $SRC_DIR yourself, and re-run this installer."
    return 0
  fi
  if [ -e "$SRC_DIR" ] || [ -L "$SRC_DIR" ]; then
    if [ ! -d "$SRC_DIR" ] || [ -L "$SRC_DIR" ] || ! dir_is_empty "$SRC_DIR"; then
      warn "Leaving $recorded — the new web source root $SRC_DIR already holds something, and this"
      warn "installer will not move one checkout on top of another."
      warn "Delete or rename whichever of the two you do not want, then re-run this installer."
      return 0
    fi
  fi
  if [ "$DRY_RUN" = "1" ]; then
    say "DRY-RUN: would move $recorded to $SRC_DIR (this installer's receipt names it)."
    return 0
  fi
  if [ -d "$SRC_DIR" ]; then rmdir "$SRC_DIR" 2>/dev/null || true; fi
  parent="$(dirname "$SRC_DIR")"
  mkdir -p "$parent" || die "Could not create $parent for the migrated web checkout."
  if mv "$recorded" "$SRC_DIR" 2>/dev/null; then
    MIGRATED_WEB_SOURCE="$SRC_DIR"
    say "Moved the earlier web checkout out of the desktop's source root: $recorded -> $SRC_DIR"
    rmdir "$(dirname "$recorded")" 2>/dev/null || true
  else
    warn "Could not move $recorded to $SRC_DIR."
    warn "Move it yourself — or delete it, once you no longer need what it holds — so the desktop"
    warn "shell owns $DESKTOP_SOURCE_ROOT alone, then re-run this installer."
  fi
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

# A branch or tag archive cannot be hash-pinned, but it can be commit-pinned:
# resolve the ref to its commit SHA first, then download that exact commit's
# archive, so the installed bytes cannot drift between resolution and download
# and the install is reproducible from the reported SHA.
resolve_ref_commit_sha() {
  local ref="$1" api_url response sha
  api_url="https://api.github.com/repos/$REPO_SLUG/commits/$ref"
  assert_trusted_url "$api_url"
  response="$(mktemp "${TMPDIR:-/tmp}/flinttrade-ref.XXXXXX")" \
    || die "Could not stage the commit-resolution response."
  TMP_DIRS+=("$response")
  download_to "$api_url" "$response"
  sha="$(lowercase "$(json_scalars < "$response" | awk -F '\t' '$1 == "sha" { print $2; exit }')")"
  rm -f "$response"
  if [ "${#sha}" -ne 40 ]; then
    die "api.github.com returned no well-formed commit SHA for '$ref'."
  fi
  case "$sha" in
    *[!0-9a-f]*) die "api.github.com returned no well-formed commit SHA for '$ref'." ;;
  esac
  printf '%s' "$sha"
}

# --ref is documented as "branch, tag or commit", and the archive fallback ends
# by telling the operator to re-run with --ref <sha>. 'git clone --branch' can
# honour only the first two of those: its argument is resolved against the
# remote's branches and tags, never against an arbitrary revision, so a commit
# SHA failed on every fresh machine and made that advice unfollowable.
#
# 'git init' + 'git fetch <ref>' + 'git checkout FETCH_HEAD' accepts all three
# forms through one code path — a branch name, a tag name and a raw commit SHA
# are all valid fetch refspecs, and GitHub serves arbitrary revisions
# (uploadpack.allowAnySHA1InWant). It is also exactly what the refresh branch
# above already does, so a fresh install and an update now resolve --ref
# identically instead of disagreeing about which forms exist.
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
    if [ "$SOURCE_UPDATE_ONLY" = "1" ]; then
      die "Refusing to replace $SRC_DIR: only an in-place update is authorised for a checkout no web-install receipt names."
    fi
    say "Fetching FlintTrade ($ref) into $SRC_DIR..."
    mkdir -p "$(dirname "$SRC_DIR")"
    rm -rf "$SRC_DIR"
    mkdir -p "$SRC_DIR"
    git -C "$SRC_DIR" init --quiet \
      || die "Could not initialise a Git checkout at $SRC_DIR."
    # Recorded so every later run's validate_source_origin has an origin to
    # prove; a clone used to set this, and dropping it would silently retire
    # the "is this really the official repository?" guard.
    git -C "$SRC_DIR" remote add origin "$REPO_URL" \
      || die "Could not record the FlintTrade origin in $SRC_DIR."
    git -C "$SRC_DIR" fetch --depth 1 origin "$ref" \
      || die "Could not fetch '$ref' from $REPO_URL."
    git -C "$SRC_DIR" checkout --detach --force FETCH_HEAD \
      || die "Could not check out '$ref' in $SRC_DIR."
  fi
}

acquire_source_with_archive() {
  local ref="$1" sha url staging archive extracted
  if [ "$SOURCE_UPDATE_ONLY" = "1" ]; then
    die "Refusing to replace $SRC_DIR: only an in-place update is authorised for a checkout no web-install receipt names."
  fi
  say "git is not installed; resolving '$ref' to an exact commit so the archive install is reproducible..."
  sha="$(resolve_ref_commit_sha "$ref")"
  url="$ARCHIVE_BASE_URL/$sha"
  assert_trusted_url "$url"
  say "Downloading the source archive for commit $sha ($url)..."
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
  say "Installed source commit: $sha (re-run with --ref $sha to reproduce this exact install)."
}

acquire_source() {
  local ref="${REF:-$DEFAULT_BRANCH}"
  warn_source_dir_provenance
  assert_desktop_source_not_shared
  # Before the identity guard, so the migrated checkout is judged where it now
  # lives rather than refused for sitting in the desktop's tree.
  migrate_legacy_web_source_checkout
  assert_source_dir_safe
  if [ "$DRY_RUN" = "1" ]; then
    if need git; then
      say "DRY-RUN: would fetch $REPO_URL at '$ref' (branch, tag or commit) into $SRC_DIR and check it out"
    else
      say "DRY-RUN: would resolve '$ref' to a commit SHA via api.github.com, then download that commit's archive from $ARCHIVE_BASE_URL/<sha> and extract it into $SRC_DIR"
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

# Earlier revisions installed the web launcher as ~/.local/bin/flinttrade — the
# exact file the Electron desktop installer owns. Retire that shim on a re-run,
# but only when this installer's own receipt still proves both the path and the
# byte-for-byte contents: if a desktop install has since republished its own
# wrapper there, the digest no longer matches and the file is left untouched.
retire_legacy_launcher_shim() {
  local recorded="" recorded_hash="" actual
  [ "$SHIM_PATH" != "$LEGACY_SHIM_PATH" ] || return 0
  [ -f "$LEGACY_SHIM_PATH" ] && [ ! -L "$LEGACY_SHIM_PATH" ] || return 0
  recorded="$(web_receipt_field shim)" || return 0
  recorded_hash="$(web_receipt_field shim_sha256)" || return 0
  [ "$recorded" = "$LEGACY_SHIM_PATH" ] || return 0
  [ "${#recorded_hash}" -eq 64 ] || return 0
  actual="$(sha256_of "$LEGACY_SHIM_PATH" 2>/dev/null || true)"
  if [ -z "$actual" ] || [ "$(lowercase "$actual")" != "$(lowercase "$recorded_hash")" ]; then
    warn "Leaving $LEGACY_SHIM_PATH — it is no longer the launcher this installer recorded."
    return 0
  fi
  if rm -f "$LEGACY_SHIM_PATH"; then
    say "Retired the earlier web launcher at $LEGACY_SHIM_PATH (it is now $SHIM_PATH)."
  else
    warn "Could not remove the earlier web launcher at $LEGACY_SHIM_PATH; remove it by hand."
  fi
}

install_launcher_shim() {
  local python="$1" staged
  mkdir -p "$SHIM_DIR" || die "Could not create $SHIM_DIR."
  if [ -L "$SHIM_PATH" ]; then die "Refusing to replace a symbolic-link launcher at $SHIM_PATH."; fi
  if [ -e "$SHIM_PATH" ] && [ ! -f "$SHIM_PATH" ]; then
    die "Refusing to replace a non-ordinary launcher path: $SHIM_PATH"
  fi
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

  # A source checkout that overlaps the desktop shell's is a configuration
  # error, not a runtime condition, so it is refused before anything is probed,
  # reported or downloaded — including under --dry-run, where reporting a plan
  # that could never run safely would be a lie.
  assert_desktop_source_not_shared

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
  # A dry run mutates nothing, so it never needs the download confirmation —
  # this keeps piped `... | bash -s -- --dry-run` usable without --yes.
  if [ "$DRY_RUN" != "1" ]; then
    if ! confirm "Proceed with the downloads above?"; then
      die "Cancelled at the download confirmation; nothing was changed."
    fi
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
  retire_legacy_launcher_shim
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
  say "Managed source     : $SRC_DIR  (the desktop shell keeps its own at $DESKTOP_ACTIVE_SOURCE)"
  say "Launcher           : $SHIM_PATH  (command alias after adding its directory to PATH: flinttrade-web <subcommand>)"
  say "Install receipt    : $WEB_RECEIPT_PATH  (the uninstaller removes only what this proves)"
  say "Runner             : python scripts/ft.py <start|stop|restart|status|dev|setup|test|lint|clean|version|help|desktop-test|desktop-build|desktop-package|desktop-dev>"
  say "Open FlintTrade at : $BACKEND_URL"
  say "Uninstall          : $UNINSTALL_COMMAND"
  say "                     (add --purge to delete the workspace, tools and source too)"
  say "----------------------------------------------------------------"
}

offer_to_start() {
  if [ "$NO_LAUNCH" = "1" ]; then
    say "Not starting FlintTrade (--no-launch). Start it later with: \"$SHIM_PATH\" start"
    return 0
  fi
  if ! confirm "Start FlintTrade now?"; then
    say "Not started. Start it later with: \"$SHIM_PATH\" start"
    return 0
  fi
  say "Starting FlintTrade — open $BACKEND_URL in your browser. Press Ctrl-C to stop."
  "$SHIM_PATH" start
}

main "$@"

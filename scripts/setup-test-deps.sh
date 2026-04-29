#!/usr/bin/env bash
# Clone (or update) the external test-dependencies into .local/external/.
#
# These three projects are NOT shipped with FlintTrade — they are
# independent services that FlintTrade integrates with at runtime. This
# script is a convenience for contributors who want to run the
# integration test paths locally; production users install OpenAlgo /
# OpenClaw / AlgoMirror via their own preferred method (their docs).
#
# By default each repo is cloned at the commit pinned in
# docs/COMPATIBILITY.md (the FlintTrade-tested version). Pass --latest
# to clone HEAD of main instead — useful when you intend to bump the
# pin.
#
# Usage:
#   bash scripts/setup-test-deps.sh           # clone at pinned commits
#   bash scripts/setup-test-deps.sh --latest  # clone at HEAD of main
#   bash scripts/setup-test-deps.sh --update  # git pull existing clones
#
# Idempotent — re-running on existing clones leaves them untouched
# unless --update is passed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

EXTERNAL_DIR=".local/external"
mkdir -p "$EXTERNAL_DIR"

# ---------------------------------------------------------------------------
# Pinned commits — keep in sync with docs/COMPATIBILITY.md
#
# AlgoMirror is intentionally NOT in this list. Its mirroring patterns are
# fully absorbed into packages/ditto/ (PositionMirror, TrailingSLManager,
# MarginCalculator, RiskManager) and run in-process. There is nothing to
# clone for testing.
# ---------------------------------------------------------------------------
declare -A PINS=(
    [openalgo]="08c2a55313f66dc54e01d4881f657676ed9e6c72"
    [openclaw]="8c4ecf42dfcf8f0265081e2801d221a70dc96886"
)
declare -A REPOS=(
    [openalgo]="https://github.com/marketcalls/openalgo.git"
    [openclaw]="https://github.com/openclaw/openclaw.git"
)

MODE="pinned"
for arg in "$@"; do
    case "$arg" in
        --latest) MODE="latest" ;;
        --update) MODE="update" ;;
        -h|--help)
            sed -n '2,21p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown flag: $arg" >&2
            exit 2
            ;;
    esac
done

clone_pinned() {
    local name="$1"
    local url="$2"
    local pin="$3"
    local dst="$EXTERNAL_DIR/$name"
    if [ -d "$dst/.git" ]; then
        echo "  $name: already cloned at $dst (use --update to refresh)"
        return 0
    fi
    echo "  $name: cloning $url into $dst"
    git clone --quiet "$url" "$dst"
    if [ "$MODE" = "pinned" ]; then
        echo "  $name: checking out pinned commit $pin"
        (cd "$dst" && git checkout --quiet "$pin")
    fi
}

update_existing() {
    local name="$1"
    local dst="$EXTERNAL_DIR/$name"
    if [ ! -d "$dst/.git" ]; then
        echo "  $name: not cloned yet -- run without --update first" >&2
        return 1
    fi
    echo "  $name: pulling latest"
    (cd "$dst" && git fetch --quiet origin && git pull --quiet --ff-only)
}

case "$MODE" in
    pinned|latest)
        echo "==> Setup-test-deps: $MODE mode"
        for name in openalgo openclaw; do
            clone_pinned "$name" "${REPOS[$name]}" "${PINS[$name]}"
        done
        ;;
    update)
        echo "==> Setup-test-deps: --update mode"
        for name in openalgo openclaw; do
            update_existing "$name"
        done
        ;;
esac

echo ""
echo "Done. Test deps are at:"
for name in openalgo openclaw; do
    dst="$EXTERNAL_DIR/$name"
    if [ -d "$dst/.git" ]; then
        echo "  $dst ($(cd "$dst" && git rev-parse --short HEAD))"
    fi
done
echo ""
echo "Pinned versions documented in docs/COMPATIBILITY.md."

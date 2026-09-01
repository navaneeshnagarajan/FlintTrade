#!/usr/bin/env bash
# Clone (or update) the external test-dependency into .local/external/.
#
# OpenAlgo is NOT shipped with FlintTrade — it is an independent service
# that FlintTrade optionally integrates with at runtime. This script is a
# convenience for contributors who want to run the OpenAlgo integration
# test paths locally; production users install OpenAlgo via their own
# preferred method (its docs).
#
# By default the repo is cloned at the commit pinned in
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
# fully absorbed into packages/services/ditto/ (PositionMirror, TrailingSLManager,
# MarginCalculator, RiskManager) and run in-process. There is nothing to
# clone for testing.
# ---------------------------------------------------------------------------
# Associative arrays (declare -A) require bash 4+, but macOS ships bash 3.2,
# so the pin/repo tables are resolved by a case function instead.
# OpenAlgo v2.0.2.2 — verified 2026-08-29. Includes the v2.0.2.2 REST
# contracts used by FlintTrade plus upstream eventlet-boundary stability and
# broker-log credential redaction hardening.
dep_repo() {
    case "$1" in
        openalgo) echo "https://github.com/marketcalls/openalgo.git" ;;
        *) return 1 ;;
    esac
}
dep_pin() {
    case "$1" in
        openalgo) echo "ef1f6b9c2165607ae4c01edb9a3e189e26596d4d" ;;
        *) return 1 ;;
    esac
}

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
        for name in openalgo; do
            clone_pinned "$name" "$(dep_repo "$name")" "$(dep_pin "$name")"
        done
        ;;
    update)
        echo "==> Setup-test-deps: --update mode"
        for name in openalgo; do
            update_existing "$name"
        done
        ;;
esac

echo ""
echo "Done. Test deps are at:"
for name in openalgo; do
    dst="$EXTERNAL_DIR/$name"
    if [ -d "$dst/.git" ]; then
        echo "  $dst ($(cd "$dst" && git rev-parse --short HEAD))"
    fi
done
echo ""
echo "Pinned versions documented in docs/COMPATIBILITY.md."

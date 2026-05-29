#!/usr/bin/env bash
# Reset FlintTrade user state for a fresh-install test.
#
# Does NOT touch OpenAlgo state (.local/external/openalgo/db/). Only wipes
# ~/.flinttrade/ (auth.db, credentials.db, activity, security,
# traffic/error logs, jwt_secret, master_password, workspace.json,
# contracts cache, rag store).
#
# Archives everything first to .local/archive/flinttrade-state-<ts>/
# per the project's never-delete rule. Nothing is lost, just moved.
#
# Usage:
#   scripts/reset-flinttrade-state.sh           # archive + wipe + (user restarts backend)
#   scripts/reset-flinttrade-state.sh --restart # also kill + restart backend

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Resolve ~/.flinttrade cross-platform (macOS / Linux / MSYS / MINGW).
STATE_DIR="${HOME}/.flinttrade"
PYTHON_BIN="${PYTHON:-python}"
FLINTTRADE_PYTHONPATH="$REPO_ROOT/packages/core/core/src"

RESTART=false
for arg in "$@"; do
    case "$arg" in
        --restart) RESTART=true ;;
    esac
done

# ---------------------------------------------------------------------------
# 1. Kill FlintTrade backend (port 5100) if running. Leave OpenAlgo (5000) alone.
# ---------------------------------------------------------------------------
BACKEND_PID=""
if command -v lsof >/dev/null 2>&1; then
    BACKEND_PID="$(lsof -tiTCP:5100 -sTCP:LISTEN 2>/dev/null | head -1)"
elif netstat -ano 2>/dev/null | grep -qE "127\.0\.0\.1:5100\s+.*LISTENING"; then
    BACKEND_PID="$(netstat -ano | grep LISTENING | grep -E '127\.0\.0\.1:5100\s' | awk '{print $NF}' | head -1)"
fi

if [ -n "${BACKEND_PID:-}" ]; then
    echo "→ Killing FlintTrade backend (PID $BACKEND_PID); OpenAlgo untouched"
    taskkill //F //PID "$BACKEND_PID" >/dev/null 2>&1 || kill "$BACKEND_PID" 2>/dev/null || kill -9 "$BACKEND_PID" 2>/dev/null || true
    sleep 2
fi

# ---------------------------------------------------------------------------
# 2. Archive current state.
# ---------------------------------------------------------------------------
TS="$(date +%Y%m%d-%H%M%S)"
ARCHIVE_DIR=".local/archive/flinttrade-state-${TS}"
mkdir -p "$ARCHIVE_DIR"

if [ -d "$STATE_DIR" ] && [ "$(ls -A "$STATE_DIR" 2>/dev/null)" ]; then
    cp -r "$STATE_DIR"/. "$ARCHIVE_DIR/" 2>/dev/null || true
    SIZE="$(du -sh "$ARCHIVE_DIR" 2>/dev/null | cut -f1)"
    echo "→ Archived FlintTrade state to $ARCHIVE_DIR (${SIZE})"
else
    echo "→ No existing state to archive"
fi

# ---------------------------------------------------------------------------
# 3. Wipe ~/.flinttrade/ but keep the empty dir so the backend writes cleanly.
# ---------------------------------------------------------------------------
rm -rf "$STATE_DIR"
mkdir -p "$STATE_DIR"
echo "→ Wiped ~/.flinttrade/"

# ---------------------------------------------------------------------------
# 4. Verify OpenAlgo state is intact.
# ---------------------------------------------------------------------------
if [ -f ".local/external/openalgo/db/openalgo.db" ]; then
    echo "→ OpenAlgo state intact: .local/external/openalgo/db/openalgo.db ($(du -h .local/external/openalgo/db/openalgo.db | cut -f1))"
else
    echo "→ Note: .local/external/openalgo/db/openalgo.db missing — OpenAlgo will first-run on next start (or you have no local-dev OpenAlgo clone; that's fine if you run OpenAlgo from another location)"
fi

# ---------------------------------------------------------------------------
# 5. Optionally restart the backend.
# ---------------------------------------------------------------------------
if [ "$RESTART" = true ]; then
    mkdir -p .local/dev-logs
    echo "→ Restarting FlintTrade backend in background…"
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
        PYTHONPATH="$FLINTTRADE_PYTHONPATH:${PYTHONPATH:-}" \
        nohup "$PYTHON_BIN" -m flinttrade_core.app > .local/dev-logs/backend.log 2>&1 &
    disown

    # Wait up to 20 s for port 5100.
    for _ in $(seq 1 20); do
        if netstat -ano 2>/dev/null | grep -qE "127\.0\.0\.1:5100\s+.*LISTENING"; then
            echo "→ Backend up on http://127.0.0.1:5100"
            exit 0
        fi
        sleep 1
    done
    echo "! Backend did not bind 5100 in 20 s — check .local/dev-logs/backend.log" >&2
    exit 1
fi

echo ""
echo "Done. Next: start the backend manually, or re-run with --restart."

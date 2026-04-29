#!/usr/bin/env bash
# Start OpenAlgo as a background process.
#
# OpenAlgo is an EXTERNAL service — it is not bundled with FlintTrade. This
# script expects a local-dev clone at .local/external/openalgo/ (created by
# scripts/setup-test-deps.sh). For production, run OpenAlgo from wherever
# you installed it and override OPENALGO_DIR via the environment.
set -euo pipefail

FLINTTRADE_DIR="${FLINTTRADE_DIR:-$(cd "$(dirname "$0")/../../.." && pwd)}"
OPENALGO_DIR="${OPENALGO_DIR:-$FLINTTRADE_DIR/.local/external/openalgo}"
PID_FILE="${TMPDIR:-/tmp}/flinttrade-openalgo.pid"

# Source .env
[ -f "$FLINTTRADE_DIR/.env" ] && { set -a; source "$FLINTTRADE_DIR/.env"; set +a; }
OPENALGO_PORT="${OPENALGO_PORT:-5000}"

# Check if already running
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "OpenAlgo already running (PID $(cat "$PID_FILE"))"
    exit 0
fi

# Check OpenAlgo directory
if [ ! -f "$OPENALGO_DIR/app.py" ]; then
    echo "ERROR: OpenAlgo not found at $OPENALGO_DIR"
    echo ""
    echo "OpenAlgo is an external dependency — FlintTrade does not bundle it."
    echo "To get a local-dev copy for testing, run:"
    echo "    bash scripts/setup-test-deps.sh"
    echo ""
    echo "Or, if you've installed OpenAlgo elsewhere, point this script at it:"
    echo "    OPENALGO_DIR=/path/to/openalgo bash infra/scripts/openalgo/start-openalgo.sh"
    exit 1
fi

# Source OpenAlgo's own .env if present
# OpenAlgo reads its own .env via Python dotenv — do not source in bash

# Bootstrap OpenAlgo .env from .sample.env on first run
if [ ! -f "$OPENALGO_DIR/.env" ] && [ -f "$OPENALGO_DIR/.sample.env" ]; then
    echo "Bootstrapping OpenAlgo .env from .sample.env ..."
    cp "$OPENALGO_DIR/.sample.env" "$OPENALGO_DIR/.env"
fi

# Auto-fix the REDIRECT_URL template placeholder that blocks startup on fresh installs.
# OpenAlgo refuses to start with <broker> in REDIRECT_URL — replace with a safe sandbox default.
if [ -f "$OPENALGO_DIR/.env" ] && grep -q '<broker>/callback' "$OPENALGO_DIR/.env"; then
    echo "Replacing <broker> placeholder in OpenAlgo REDIRECT_URL with dhan_sandbox ..."
    sed -i.bak 's|<broker>/callback|dhan_sandbox/callback|g' "$OPENALGO_DIR/.env" && rm -f "$OPENALGO_DIR/.env.bak"
fi

cd "$OPENALGO_DIR"

# Force UTF-8 so OpenAlgo's banner/emoji prints don't crash on Windows cp1252.
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

echo "Starting OpenAlgo on port $OPENALGO_PORT..."

# Try gunicorn with eventlet first, fall back to plain python
if command -v gunicorn >/dev/null 2>&1; then
    gunicorn --worker-class eventlet -w 1 --bind "0.0.0.0:$OPENALGO_PORT" \
        --access-logfile - --error-logfile - \
        --daemon --pid "$PID_FILE" app:app
else
    echo "gunicorn not found, starting with python directly"
    nohup python3 app.py > "${TMPDIR:-/tmp}/flinttrade-openalgo.log" 2>&1 &
    echo $! > "$PID_FILE"
fi

# Wait and verify
sleep 3
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "✓ OpenAlgo running on port $OPENALGO_PORT (PID $(cat "$PID_FILE"))"
    # Try ping
    if curl -sf "http://127.0.0.1:$OPENALGO_PORT/api/v1/ping" >/dev/null 2>&1; then
        echo "✓ OpenAlgo API responding"
    else
        echo "⚠ OpenAlgo started but API not responding yet (may still be loading)"
    fi
else
    echo "✗ OpenAlgo failed to start"
    [ -f "${TMPDIR:-/tmp}/flinttrade-openalgo.log" ] && tail -10 "${TMPDIR:-/tmp}/flinttrade-openalgo.log"
    exit 1
fi

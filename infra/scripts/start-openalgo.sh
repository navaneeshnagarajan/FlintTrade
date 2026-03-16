#!/usr/bin/env bash
# Start OpenAlgo as a background process
set -euo pipefail

FLINTTRADE_DIR="${FLINTTRADE_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
OPENALGO_DIR="$FLINTTRADE_DIR/infra/openalgo"
PID_FILE="/tmp/flinttrade-openalgo.pid"

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
    echo "ERROR: $OPENALGO_DIR/app.py not found"
    echo "Run: git submodule update --init"
    exit 1
fi

# Source OpenAlgo's own .env if present
[ -f "$OPENALGO_DIR/.env" ] && { set -a; source "$OPENALGO_DIR/.env"; set +a; }

cd "$OPENALGO_DIR"

echo "Starting OpenAlgo on port $OPENALGO_PORT..."

# Try gunicorn with eventlet first, fall back to plain python
if command -v gunicorn >/dev/null 2>&1; then
    gunicorn --worker-class eventlet -w 1 --bind "0.0.0.0:$OPENALGO_PORT" \
        --access-logfile - --error-logfile - \
        --daemon --pid "$PID_FILE" app:app
else
    echo "gunicorn not found, starting with python directly"
    nohup python3 app.py > /tmp/flinttrade-openalgo.log 2>&1 &
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
    [ -f /tmp/flinttrade-openalgo.log ] && tail -10 /tmp/flinttrade-openalgo.log
    exit 1
fi

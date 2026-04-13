#!/usr/bin/env bash
# Stop OpenAlgo gracefully
set -euo pipefail

PID_FILE="${TMPDIR:-/tmp}/flinttrade-openalgo.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "OpenAlgo is not running (no PID file)"
    exit 0
fi

PID=$(cat "$PID_FILE")

if ! kill -0 "$PID" 2>/dev/null; then
    echo "OpenAlgo process $PID is not running (stale PID file)"
    rm -f "$PID_FILE"
    exit 0
fi

echo "Stopping OpenAlgo (PID $PID)..."

# Graceful shutdown
kill "$PID" 2>/dev/null || true
for i in $(seq 1 5); do
    if ! kill -0 "$PID" 2>/dev/null; then
        break
    fi
    sleep 1
done

# Force kill if still alive
if kill -0 "$PID" 2>/dev/null; then
    echo "Force killing OpenAlgo..."
    kill -9 "$PID" 2>/dev/null || true
fi

rm -f "$PID_FILE"
echo "✓ OpenAlgo stopped"

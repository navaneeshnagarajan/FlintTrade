#!/usr/bin/env bash
# Show FlintTrade service status
set -u

FLINTTRADE_DIR="${FLINTTRADE_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
PID_FILE="${TMPDIR:-/tmp}/flinttrade-openalgo.pid"

# Source .env
[ -f "$FLINTTRADE_DIR/.env" ] && { set -a; source "$FLINTTRADE_DIR/.env"; set +a; }
OPENALGO_PORT="${OPENALGO_PORT:-5000}"
FLINTTRADE_BACKEND_PORT="${FLINTTRADE_BACKEND_PORT:-5100}"
DATA_DIR="${DATA_DIR:-$FLINTTRADE_DIR/data}"
AUDIT_LOG_DIR="${AUDIT_LOG_DIR:-$DATA_DIR/audit}"

echo "=== FlintTrade Status ==="
echo ""

echo "FlintTrade backend:"
if curl -sf "http://127.0.0.1:$FLINTTRADE_BACKEND_PORT/api/v1/ping" >/dev/null 2>&1; then
    echo "  API: responding on port $FLINTTRADE_BACKEND_PORT"
else
    echo "  API: not responding on port $FLINTTRADE_BACKEND_PORT"
fi

echo ""
echo "OpenAlgo integration (optional):"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "  Process: running (PID $(cat "$PID_FILE"))"
else
    echo "  Process: stopped"
fi

# OpenAlgo API
if curl -sf "http://127.0.0.1:$OPENALGO_PORT/api/v1/ping" >/dev/null 2>&1; then
    BROKER=$(curl -sf "http://127.0.0.1:$OPENALGO_PORT/api/v1/ping" -H "Content-Type: application/json" -d "{\"apikey\":\"${OPENALGO_API_KEY:-}\"}" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('broker','unknown'))" 2>/dev/null || echo "unknown")
    echo "  API: responding on port $OPENALGO_PORT (broker: $BROKER)"
else
    echo "  API: not responding on port $OPENALGO_PORT"
fi

# Port usage
echo ""
echo "Ports:"
for port in $FLINTTRADE_BACKEND_PORT $OPENALGO_PORT 5173 3000; do
    if command -v ss >/dev/null 2>&1; then
        PROC=$(ss -tlnp "sport = :$port" 2>/dev/null | grep -o 'users:(.*' | head -1)
    elif command -v lsof >/dev/null 2>&1; then
        PROC=$(lsof -i ":$port" -sTCP:LISTEN 2>/dev/null | tail -1 | awk '{print $1}')
    else
        PROC=""
    fi
    if [ -n "$PROC" ]; then
        echo "  :$port — in use ($PROC)"
    else
        echo "  :$port — free"
    fi
done

# Data directories
echo ""
echo "Data:"
for dir in "$DATA_DIR" "$AUDIT_LOG_DIR"; do
    if [ -d "$dir" ]; then
        SIZE=$(du -sh "$dir" 2>/dev/null | cut -f1)
        echo "  $dir — $SIZE"
    else
        echo "  $dir — does not exist"
    fi
done

echo ""
echo "Version: $(cat "$FLINTTRADE_DIR/VERSION" 2>/dev/null || echo 'unknown')"

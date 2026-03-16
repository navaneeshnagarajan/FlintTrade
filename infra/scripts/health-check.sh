#!/usr/bin/env bash
# FlintTrade health check — exits 0 if healthy, 1 if any check fails
# Suitable for cron, monitoring, or systemd health checks
set -euo pipefail

FLINTTRADE_DIR="${FLINTTRADE_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
HEALTHY=true

# Source .env
[ -f "$FLINTTRADE_DIR/.env" ] && { set -a; source "$FLINTTRADE_DIR/.env"; set +a; }
OPENALGO_PORT="${OPENALGO_PORT:-5000}"
DATA_DIR="${DATA_DIR:-$FLINTTRADE_DIR/data}"
AUDIT_LOG_DIR="${AUDIT_LOG_DIR:-$DATA_DIR/audit}"

ok()   { echo "✓ $1"; }
fail() { echo "✗ $1"; HEALTHY=false; }
warn() { echo "⚠ $1"; }

echo "=== FlintTrade Health Check ==="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 1. OpenAlgo API
if curl -sf "http://127.0.0.1:$OPENALGO_PORT/api/v1/ping" >/dev/null 2>&1; then
    ok "OpenAlgo API responding on port $OPENALGO_PORT"
else
    fail "OpenAlgo API not responding on port $OPENALGO_PORT"
fi

# 2. Disk space
if command -v df >/dev/null 2>&1; then
    FREE_KB=$(df "$FLINTTRADE_DIR" 2>/dev/null | tail -1 | awk '{print $4}')
    if [ -n "$FREE_KB" ] && [ "$FREE_KB" -lt 10485760 ] 2>/dev/null; then
        warn "Low disk space: $(( FREE_KB / 1024 / 1024 ))GB free (< 10GB)"
    else
        ok "Disk space OK"
    fi
fi

# 3. Data directory
if [ -d "$DATA_DIR" ] && [ -w "$DATA_DIR" ]; then
    ok "Data directory writable: $DATA_DIR"
else
    fail "Data directory missing or not writable: $DATA_DIR"
fi

# 4. Audit directory
if [ -d "$AUDIT_LOG_DIR" ] && [ -w "$AUDIT_LOG_DIR" ]; then
    ok "Audit directory writable: $AUDIT_LOG_DIR"
else
    fail "Audit directory missing or not writable: $AUDIT_LOG_DIR"
fi

# 5. .env configured
if [ -f "$FLINTTRADE_DIR/.env" ]; then
    if grep -q "^OPENALGO_API_KEY=.\+" "$FLINTTRADE_DIR/.env" 2>/dev/null; then
        ok ".env has OPENALGO_API_KEY configured"
    else
        warn ".env exists but OPENALGO_API_KEY is blank"
    fi
else
    fail ".env not found"
fi

echo ""

if [ "$HEALTHY" = true ]; then
    echo "Status: HEALTHY"
    exit 0
else
    echo "Status: UNHEALTHY"
    exit 1
fi

#!/bin/bash
# Quick health check for production Custom PC
set -euo pipefail

echo "=== FlintTrade Health Check ==="
echo "Time: $(date '+%Y-%m-%d %H:%M IST')"
echo ""

# FlintTrade service
echo "FlintTrade service:"
sudo systemctl is-active flinttrade && echo "  RUNNING" || echo "  STOPPED"

# OpenAlgo service
echo "OpenAlgo service:"
sudo systemctl is-active openalgo && echo "  RUNNING" || echo "  STOPPED"

# OpenAlgo ping
echo "OpenAlgo API:"
source /home/navaneesh/FlintTrade/.env 2>/dev/null || true
OPENALGO_HOST=${OPENALGO_HOST:-"http://127.0.0.1:5000"}
curl -sf "$OPENALGO_HOST/api/v1/ping" \
  -H "Content-Type: application/json" \
  -d '{"apikey":"'"$OPENALGO_API_KEY"'"}' \
  --max-time 3 | python3 -c "import sys,json; d=json.load(sys.stdin); print('  ' + d.get('status','?'))" \
  || echo "  UNREACHABLE"

# Audit log
echo "Audit log:"
AUDIT_DIR=${AUDIT_LOG_DIR:-"/data/flinttrade/audit"}
if [ -d "$AUDIT_DIR" ]; then
    COUNT=$(find "$AUDIT_DIR" -name "*.jsonl" | wc -l)
    echo "  $COUNT audit files in $AUDIT_DIR"
else
    echo "  MISSING: $AUDIT_DIR"
fi

# Disk space on 5TB HDD
echo "5TB HDD:"
df -h /data 2>/dev/null | tail -1 | awk '{print "  Used: "$3" / "$2" ("$5")"}' || echo "  /data not mounted"

echo ""
echo "=== Done ==="

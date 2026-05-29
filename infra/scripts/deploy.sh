#!/bin/bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../../.env" 2>/dev/null || true
echo "=== FlintTrade Deploy $(date '+%Y-%m-%d %H:%M IST') ==="
cd ~/FlintTrade && git checkout main && git pull
sudo systemctl restart flinttrade
echo "✅ Deployed"

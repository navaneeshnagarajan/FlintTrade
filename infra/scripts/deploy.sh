#!/bin/bash
# FlintTrade Production Deployment Script — canonical deploy entry point.
# Merged union of the old deploy.sh (checkout main + .env sourcing) and
# deploy-production.sh (market-hours guard, hash-verified install, systemd
# install-if-absent, post-restart verification).
# DO NOT run during market hours (9:15 AM - 3:30 PM IST).
set -euo pipefail

# Optional env-driven overrides (e.g. FLINTTRADE_DIR) from the repo-root .env.
source "$(dirname "${BASH_SOURCE[0]}")/../../.env" 2>/dev/null || true

REPO_DIR="${FLINTTRADE_DIR:-$HOME/FlintTrade}"
SERVICE_NAME="flinttrade"

echo "=== FlintTrade Production Deploy ==="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S IST')"
echo ""

# 1. Safety check — abort if the market is open.
#    10# forces base-10 so zero-padded hours (08, 09) are not read as octal.
HOUR=$(date +%H)
MIN=$(date +%M)
TIME_NOW=$((10#$HOUR * 60 + 10#$MIN))
MARKET_OPEN=$((9 * 60 + 15))
MARKET_CLOSE=$((15 * 60 + 30))
if [ "$TIME_NOW" -ge "$MARKET_OPEN" ] && [ "$TIME_NOW" -le "$MARKET_CLOSE" ]; then
    echo "ERROR: Deploy blocked — market is open (9:15 AM - 3:30 PM IST)"
    echo "Wait until after 3:30 PM IST"
    exit 1
fi

# 2. Pull latest — the explicit checkout guarantees main is deployed even if
#    the working copy was left on another branch.
cd "$REPO_DIR"
echo "Pulling latest from main..."
git checkout main
git pull origin main

# 3. Install Python deps — SC-07: hash-verified install only
echo "Installing Python dependencies..."
pip install --break-system-packages --require-hashes -r requirements.lock -q

# 4. Install systemd service if not present
if [ ! -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
    echo "Installing systemd service..."
    sudo cp "infra/systemd/${SERVICE_NAME}.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
fi

# 5. Restart service (literal service name — pinned by tests/test_restructure_goals.py)
echo "Restarting FlintTrade service..."
sudo systemctl restart flinttrade
sleep 3

# 6. Verify startup (|| true so an inactive service reaches the failure branch
#    instead of tripping set -e inside the command substitution)
STATUS=$(sudo systemctl is-active "$SERVICE_NAME" || true)
if [ "$STATUS" = "active" ]; then
    echo "SUCCESS: FlintTrade is running"
    sudo systemctl status "$SERVICE_NAME" --no-pager -l | head -10
else
    echo "ERROR: FlintTrade failed to start"
    sudo journalctl -u "$SERVICE_NAME" --no-pager -n 20
    exit 1
fi

echo ""
echo "=== Deploy complete ==="
echo "Logs: journalctl -u flinttrade -f"
echo "Stop: sudo systemctl stop flinttrade"

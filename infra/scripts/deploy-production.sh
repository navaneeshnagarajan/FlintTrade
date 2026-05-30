#!/bin/bash
# FlintTrade Production Deployment Script
# DO NOT run during market hours (9:15 AM - 3:30 PM IST)
set -euo pipefail

REPO_DIR="${FLINTTRADE_DIR:-$HOME/FlintTrade}"
SERVICE_NAME="flinttrade"
PYTHON="/usr/bin/python3"

echo "=== FlintTrade Production Deploy ==="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S IST')"
echo ""

# 1. Safety check — abort if market is open
HOUR=$(date +%H)
MIN=$(date +%M)
TIME_NOW=$((HOUR * 60 + MIN))
MARKET_OPEN=$((9 * 60 + 15))
MARKET_CLOSE=$((15 * 60 + 30))
if [ $TIME_NOW -ge $MARKET_OPEN ] && [ $TIME_NOW -le $MARKET_CLOSE ]; then
    echo "ERROR: Deploy blocked — market is open (9:15 AM - 3:30 PM IST)"
    echo "Wait until after 3:30 PM IST"
    exit 1
fi

# 2. Pull latest
cd $REPO_DIR
echo "Pulling latest from main..."
git pull origin main

# 3. Install Python deps — SC-07: hash-verified install only
echo "Installing Python dependencies..."
pip install --break-system-packages --require-hashes -r requirements.lock -q

# 4. Install systemd service if not present
if [ ! -f /etc/systemd/system/flinttrade.service ]; then
    echo "Installing systemd service..."
    sudo cp infra/systemd/flinttrade.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable flinttrade
fi

# 5. Restart service
echo "Restarting FlintTrade service..."
sudo systemctl restart flinttrade
sleep 3

# 6. Verify startup
STATUS=$(sudo systemctl is-active flinttrade)
if [ "$STATUS" = "active" ]; then
    echo "SUCCESS: FlintTrade is running"
    sudo systemctl status flinttrade --no-pager -l | head -10
else
    echo "ERROR: FlintTrade failed to start"
    sudo journalctl -u flinttrade --no-pager -n 20
    exit 1
fi

echo ""
echo "=== Deploy complete ==="
echo "Logs: journalctl -u flinttrade -f"
echo "Stop: sudo systemctl stop flinttrade"

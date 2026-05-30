#!/bin/bash
# FlintTrade First-Time Setup (Ubuntu 24.04)
# Run once only
set -euo pipefail

INSTALL_DIR="${FLINTTRADE_DIR:-$HOME/FlintTrade}"
REPO_URL="${FLINTTRADE_REPO:-https://github.com/navaneeshnagarajan/FlintTrade.git}"
CURRENT_USER=$(whoami)

echo "=== FlintTrade First-Time Setup ==="

# Python deps
echo "Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y python3-pip python3-venv git curl nodejs -q

# Clone repo if not present
if [ ! -d "$INSTALL_DIR" ]; then
    echo "Cloning FlintTrade..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Python dependencies — SC-07: hash-verified install only
echo "Installing Python dependencies..."
pip install --break-system-packages --require-hashes -r requirements.lock

# Create .env if not present
if [ ! -f .env ]; then
    echo "Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "IMPORTANT: Edit .env with your credentials before starting:"
    echo "  nano $INSTALL_DIR/.env"
    echo ""
fi

# Create audit log directory
echo "Creating audit log directory..."
sudo mkdir -p /data/flinttrade/audit
sudo chown "$CURRENT_USER:$CURRENT_USER" /data/flinttrade
sudo chown "$CURRENT_USER:$CURRENT_USER" /data/flinttrade/audit

# Install systemd service
echo "Installing systemd service..."
sudo cp infra/systemd/flinttrade.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable flinttrade

echo ""
echo "=== Setup complete ==="
echo "Next: Edit .env then run: sudo systemctl start flinttrade"

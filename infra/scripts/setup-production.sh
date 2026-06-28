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

# Create a minimal server fallback env file if not present. OpenAlgo and broker
# settings should be completed in the app Setup/Settings UI.
if [ ! -f .env ]; then
    echo "Creating minimal server fallback .env..."
    {
        echo "# FlintTrade server fallback environment."
        echo "# Use Setup/Settings for OpenAlgo and broker configuration."
    } > .env
    chmod 600 .env
    echo ""
    echo "Runtime configuration is completed from the app UI after startup."
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
echo "Next: sudo systemctl start flinttrade, then complete Setup in the app UI"

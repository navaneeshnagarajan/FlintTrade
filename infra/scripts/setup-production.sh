#!/bin/bash
# FlintTrade First-Time Setup — Custom PC (Ubuntu 24.04)
# Run once only
set -euo pipefail

echo "=== FlintTrade First-Time Setup ==="

# Python deps
echo "Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y python3-pip python3-venv git curl nodejs -q

# Clone repo if not present
if [ ! -d "/home/navaneesh/FlintTrade" ]; then
    echo "Cloning FlintTrade..."
    git clone https://github.com/navaneeshnagarajan/FlintTrade.git /home/navaneesh/FlintTrade
fi

cd /home/navaneesh/FlintTrade

# Python dependencies
echo "Installing Python dependencies..."
pip install --break-system-packages -r requirements.txt

# Create .env if not present
if [ ! -f .env ]; then
    echo "Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "IMPORTANT: Edit .env with your credentials before starting:"
    echo "  nano /home/navaneesh/FlintTrade/.env"
    echo ""
fi

# Create audit log directory on 5TB HDD
echo "Creating audit log directory..."
sudo mkdir -p /data/flinttrade/audit
sudo chown navaneesh:navaneesh /data/flinttrade
sudo chown navaneesh:navaneesh /data/flinttrade/audit

# Install systemd service
echo "Installing systemd service..."
sudo cp infra/systemd/flinttrade.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable flinttrade

echo ""
echo "=== Setup complete ==="
echo "Next: Edit .env then run: sudo systemctl start flinttrade"

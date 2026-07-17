#!/bin/bash
# FlintTrade First-Time Setup (Ubuntu 24.04)
# Run once only. Provisions the host (system packages, Node 22, data and log
# directories) and installs FlintTrade as a systemd service.
# Absorbed infra/scripts/setup-ubuntu.sh (host-provisioning steps) — this is
# the single production installer; infra/scripts/setup.sh remains the dev setup.
set -euo pipefail

INSTALL_DIR="${FLINTTRADE_DIR:-$HOME/FlintTrade}"
REPO_URL="${FLINTTRADE_REPO:-https://github.com/navaneeshnagarajan/FlintTrade.git}"
CURRENT_USER=$(whoami)

echo "=== FlintTrade First-Time Setup ==="

# System packages — includes the reverse-proxy and hardening packages (nginx,
# fail2ban, ufw) that infra/nginx/ and the security docs assume are present.
echo "Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y python3 python3-pip python3-venv git curl jq nginx fail2ban ufw -q

# Node.js 22 via NodeSource — the repo requires Node >= 22 and the distro
# nodejs package is older.
if ! command -v node >/dev/null 2>&1; then
    echo "Installing Node.js 22 (NodeSource)..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs -q
fi

# Clone repo if not present
if [ ! -d "$INSTALL_DIR" ]; then
    echo "Cloning FlintTrade..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Python dependencies — SC-07: hash-verified install only
echo "Installing Python dependencies..."
pip install --break-system-packages --require-hashes -r requirements.lock

# Optional toolchain steps — pick up the broker-SDK pins (e.g. the Kotak Neo
# git SDK via uv sync) and the node workspace deps when the tooling is
# available. The hash-verified requirements.lock install above stays the
# baseline on a plain Ubuntu host.
if command -v uv >/dev/null 2>&1; then
    echo "Syncing uv workspace (broker-SDK pins)..."
    uv sync --frozen --all-packages
fi
if command -v pnpm >/dev/null 2>&1; then
    echo "Installing node workspace dependencies..."
    pnpm install --frozen-lockfile
fi

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

# Create the full data and log directory tree
echo "Creating data and log directories..."
sudo mkdir -p /data/flinttrade/{historical,ticks,audit,backups} /var/log/flinttrade
sudo chown -R "$CURRENT_USER:$CURRENT_USER" /data/flinttrade /var/log/flinttrade

# Install systemd service
echo "Installing systemd service..."
sudo cp infra/systemd/flinttrade.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable flinttrade

echo ""
echo "=== Setup complete ==="
echo "Next: sudo systemctl start flinttrade, then complete Setup in the app UI"

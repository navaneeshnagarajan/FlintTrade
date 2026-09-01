#!/bin/bash
# FlintTrade First-Time Setup (Ubuntu 24.04)
# Run once only. Provisions the host (system packages, Node 22, data and log
# directories) and installs FlintTrade as a systemd service.
# Absorbed infra/scripts/setup-ubuntu.sh (host-provisioning steps) — this is
# the single production installer; infra/scripts/setup.sh remains the dev setup.
#
# Default prefix is hardcoded /opt/flinttrade so it matches
# infra/systemd/flinttrade.service (WorkingDirectory, ExecStart,
# FLINTTRADE_HOME, FLINTTRADE_WORKSPACE_DIR, ReadWritePaths).
# FLINTTRADE_DIR is not supported — the unit cannot be relocated without
# rewriting it, and ProtectHome=true refuses a home-directory tree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=production-contract.sh
source "$SCRIPT_DIR/production-contract.sh"

flinttrade_assert_no_dir_override
INSTALL_DIR="$(flinttrade_production_prefix)"
flinttrade_assert_safe_install_dir "$INSTALL_DIR"
REPO_URL="${FLINTTRADE_REPO:-https://github.com/navaneeshnagarajan/FlintTrade.git}"
VENV_DIR="$INSTALL_DIR/.venv"
# The shipped unit runs as www-data; nginx (installed below) provides that user.
SERVICE_USER="www-data"

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

# Clone repo if not present. /opt is not user-writable; sudo matches
# infra/install/install-native.sh.
if [ ! -d "$INSTALL_DIR" ]; then
    echo "Cloning FlintTrade into $INSTALL_DIR..."
    sudo git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Python virtualenv — flinttrade.service ExecStart's $INSTALL_DIR/.venv/bin/python.
# Apt-installing python3-venv is not enough; the unit path must exist.
# Ubuntu 24.04 only: refuse Bookworm/Pi system Python 3.11 before creating .venv.
echo "Checking Python >= 3.12..."
flinttrade_assert_python_floor python3

echo "Creating Python virtual environment at $VENV_DIR..."
if [ ! -d "$VENV_DIR" ]; then
    sudo python3 -m venv "$VENV_DIR"
fi

# Python dependencies — SC-07: hash-verified install only, into the unit venv
# (not the system interpreter).
echo "Installing Python dependencies into $VENV_DIR..."
sudo "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel -q
sudo "$VENV_DIR/bin/pip" install --require-hashes -r "$INSTALL_DIR/requirements.lock"

# Optional toolchain steps — pick up the broker-SDK pins (e.g. the Kotak Neo
# git SDK via uv sync) and the node workspace deps when the tooling is
# available. The hash-verified requirements.lock install above stays the
# baseline on a plain Ubuntu host.
if command -v uv >/dev/null 2>&1; then
    echo "Syncing uv workspace (broker-SDK pins)..."
    (cd "$INSTALL_DIR" && sudo uv sync --frozen --all-packages --no-dev)
fi
if command -v pnpm >/dev/null 2>&1; then
    echo "Installing node workspace dependencies..."
    (cd "$INSTALL_DIR" && sudo pnpm install --frozen-lockfile)
fi

# Create a minimal server fallback env file if not present. OpenAlgo and broker
# settings should be completed in the app Setup/Settings UI.
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "Creating minimal server fallback .env..."
    sudo tee "$INSTALL_DIR/.env" >/dev/null <<'EOF'
# FlintTrade server fallback environment.
# Use Setup/Settings for OpenAlgo and broker configuration.
EOF
    sudo chmod 600 "$INSTALL_DIR/.env"
    echo ""
    echo "Runtime configuration is completed from the app UI after startup."
    echo ""
fi

# Create the full data and log directory tree. The unit's ReadWritePaths are
# $INSTALL_DIR/data and $INSTALL_DIR/.flinttrade; also keep the historical
# /data and /var/log trees for backup/ops scripts.
echo "Creating data and log directories..."
sudo mkdir -p \
    "$INSTALL_DIR/data" \
    "$INSTALL_DIR/.flinttrade" \
    /data/flinttrade/{historical,ticks,audit,backups} \
    /var/log/flinttrade

# The unit runs as www-data. Keep the git checkout and .venv root-owned so
# deploy.sh can update them; chown only the runtime workspace/data/log paths.
echo "Setting $SERVICE_USER ownership on runtime data directories..."
sudo chown -R "$SERVICE_USER:$SERVICE_USER" \
    "$INSTALL_DIR/data" \
    "$INSTALL_DIR/.flinttrade" \
    /data/flinttrade \
    /var/log/flinttrade

# Install systemd service
echo "Installing systemd service..."
sudo cp "$INSTALL_DIR/infra/systemd/flinttrade.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable flinttrade

echo ""
echo "=== Setup complete ==="
echo "Installed at $INSTALL_DIR (unit user: $SERVICE_USER)"
echo "Next: sudo systemctl start flinttrade, then complete Setup in the app UI"

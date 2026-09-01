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
FLINTTRADE_PRODUCTION_CONTRACT="$SCRIPT_DIR/production-contract.sh"
export FLINTTRADE_PRODUCTION_CONTRACT

flinttrade_assert_no_dir_override
INSTALL_DIR="$(flinttrade_production_prefix)"
flinttrade_assert_safe_install_dir "$INSTALL_DIR"
REPO_URL="${FLINTTRADE_REPO:-https://github.com/navaneeshnagarajan/FlintTrade.git}"
VENV_DIR="$INSTALL_DIR/.venv"
PYTHON_BIN="/usr/bin/python3"
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
flinttrade_assert_python_floor "$PYTHON_BIN"

echo "Creating Python virtual environment at $VENV_DIR..."
if [ ! -d "$VENV_DIR" ]; then
    sudo "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# Python dependencies — SC-07: hash-verified install only, into the unit venv
# (not the system interpreter).
echo "Installing Python dependencies into $VENV_DIR..."
sudo "$VENV_DIR/bin/pip" install --require-hashes -r "$INSTALL_DIR/requirements.lock"

# Optional broker-SDK pins when uv is already on PATH. Terminal install+build
# is required — the backend serves Setup only when dist/index.html exists.
if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
    echo "Syncing uv workspace (broker-SDK pins)..."
    (cd "$INSTALL_DIR" && sudo "$UV_BIN" sync --frozen --all-packages --no-dev)
fi
echo "Installing node workspace and building the terminal..."
flinttrade_build_terminal "$INSTALL_DIR"

# Create a minimal server fallback env file if not present. OpenAlgo and broker
# settings should be completed in the app Setup/Settings UI.
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "Creating minimal server fallback .env..."
    sudo tee "$INSTALL_DIR/.env" >/dev/null <<'EOF'
# FlintTrade server fallback environment.
# Use Setup/Settings for OpenAlgo and broker configuration.
EOF
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

# Apply the shared checkout contract after every file that setup writes
# (venv, lock install, optional uv/pnpm, .env, data dirs). Host /data and
# /var/log trees are outside the checkout.
echo "Applying checkout ownership and modes..."
flinttrade_apply_checkout_modes "$INSTALL_DIR" "$SERVICE_USER"
sudo chown -R "$SERVICE_USER:$SERVICE_USER" \
    /data/flinttrade \
    /var/log/flinttrade

echo "Provisioning workspace master password for $SERVICE_USER..."
flinttrade_provision_workspace "$INSTALL_DIR" "$SERVICE_USER" "$VENV_DIR/bin/python"

# Install systemd service
echo "Installing systemd service..."
sudo cp "$INSTALL_DIR/infra/systemd/flinttrade.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable flinttrade

echo ""
echo "=== Setup complete ==="
echo "Installed at $INSTALL_DIR (unit user: $SERVICE_USER)"
echo "Next: sudo systemctl start flinttrade, then complete Setup in the app UI"

#!/usr/bin/env bash
# FlintTrade bare-metal installer for Ubuntu/Debian
#
# Installs Python 3.12, Node.js, Nginx, builds the application,
# and configures systemd services.
# Idempotent — safe to run multiple times.
#
# Usage:
#   sudo ./install-native.sh
#   sudo DOMAIN=trade.example.com ./install-native.sh

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────
INSTALL_DIR="${INSTALL_DIR:-/opt/flinttrade}"
REPO_URL="https://github.com/navaneeshnagarajan/FlintTrade.git"
BRANCH="main"
DOMAIN="${DOMAIN:-}"
FLINTTRADE_USER="${FLINTTRADE_USER:-flinttrade}"
NODE_MAJOR=22

# Colours
GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
CYAN='\033[36m'
RESET='\033[0m'

log()  { echo -e "${CYAN}[FlintTrade]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARNING]${RESET} $*"; }
err()  { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()  { err "$*"; exit 1; }
ok()   { echo -e "${GREEN}[OK]${RESET} $*"; }

# ── Preflight ──────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    die "This script must be run as root. Use: sudo $0"
fi

# Detect distro
if [ ! -f /etc/os-release ]; then
    die "Cannot detect OS. This installer supports Ubuntu/Debian only."
fi
. /etc/os-release
case "$ID" in
    ubuntu|debian) ok "Detected $PRETTY_NAME" ;;
    *) die "Unsupported OS: $ID. This installer supports Ubuntu/Debian only." ;;
esac

# ── Step 1: Install system dependencies ────────────────────────────────
log "Installing system dependencies..."

apt-get update -qq

# Python 3.12
if ! command -v python3.12 >/dev/null 2>&1; then
    log "Installing Python 3.12..."
    apt-get install -y -qq software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
    apt-get update -qq
    apt-get install -y -qq python3.12 python3.12-venv python3.12-dev
fi
ok "Python 3.12: $(python3.12 --version)"

# Node.js
if ! command -v node >/dev/null 2>&1; then
    log "Installing Node.js $NODE_MAJOR..."
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    apt-get install -y -qq nodejs
fi
ok "Node.js: $(node --version)"

# System packages
apt-get install -y -qq \
    nginx \
    certbot python3-certbot-nginx \
    git curl wget \
    build-essential \
    restic

ok "System dependencies installed"

# ── Step 2: Create application directory and user ──────────────────────
log "Setting up application directory..."

# Create service user if it does not exist
if ! id "$FLINTTRADE_USER" >/dev/null 2>&1; then
    useradd --system --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" "$FLINTTRADE_USER"
    ok "Created system user: $FLINTTRADE_USER"
fi

# Create install directory
mkdir -p "$INSTALL_DIR"

# Clone or update repository
if [ -d "$INSTALL_DIR/.git" ]; then
    log "Existing installation found. Updating..."
    cd "$INSTALL_DIR"
    git pull --recurse-submodules origin "$BRANCH"
else
    log "Cloning FlintTrade..."
    git clone --recursive -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
ok "Repository ready at $INSTALL_DIR"

# ── Step 3: Set up Python virtual environment ──────────────────────────
log "Setting up Python virtual environment..."

VENV_DIR="$INSTALL_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    python3.12 -m venv "$VENV_DIR"
fi

# Activate and install dependencies
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel -q
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

ok "Python dependencies installed"

# ── Step 4: Build React terminal ───────────────────────────────────────
log "Building React terminal..."

cd "$INSTALL_DIR/packages/terminal"
npm install --production=false
npm run build

ok "Terminal built"

# ── Step 5: Configure environment ──────────────────────────────────────
cd "$INSTALL_DIR"

if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    log "Created .env from .env.example"
fi

# Create user data directory
FLINTTRADE_HOME="/home/$FLINTTRADE_USER"
if [ "$FLINTTRADE_USER" = "flinttrade" ]; then
    FLINTTRADE_HOME="$INSTALL_DIR"
fi
FLINTTRADE_DATA="$FLINTTRADE_HOME/.flinttrade"
mkdir -p "$FLINTTRADE_DATA"

# Generate JWT secret if not present
if [ ! -f "$FLINTTRADE_DATA/jwt_secret" ]; then
    head -c 48 /dev/urandom | base64 | tr -d '/+=' | head -c 48 > "$FLINTTRADE_DATA/jwt_secret"
    chmod 600 "$FLINTTRADE_DATA/jwt_secret"
    ok "JWT secret generated"
fi

# Generate Glitchtip secrets if not already set in .env
if ! grep -q "^GLITCHTIP_SECRET_KEY=" "$INSTALL_DIR/.env" 2>/dev/null; then
    GLITCHTIP_SECRET_KEY=$(head -c 50 /dev/urandom | base64 | tr -d '/+=' | head -c 50)
    echo "GLITCHTIP_SECRET_KEY=$GLITCHTIP_SECRET_KEY" >> "$INSTALL_DIR/.env"
    ok "Glitchtip secret key generated"
fi
if ! grep -q "^GLITCHTIP_DB_PASSWORD=" "$INSTALL_DIR/.env" 2>/dev/null; then
    GLITCHTIP_DB_PASSWORD=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 32)
    echo "GLITCHTIP_DB_PASSWORD=$GLITCHTIP_DB_PASSWORD" >> "$INSTALL_DIR/.env"
    ok "Glitchtip DB password generated"
fi

# Set ownership
chown -R "$FLINTTRADE_USER:$FLINTTRADE_USER" "$INSTALL_DIR"
chown -R "$FLINTTRADE_USER:$FLINTTRADE_USER" "$FLINTTRADE_DATA"

# ── Step 6: Configure Nginx ───────────────────────────────────────────
log "Configuring Nginx..."

SERVER_NAME="${DOMAIN:-_}"

tee /etc/nginx/sites-available/flinttrade >/dev/null <<NGINX_EOF
server {
    listen 80;
    server_name $SERVER_NAME;

    # Serve built React terminal
    root $INSTALL_DIR/packages/terminal/dist;
    index index.html;

    # React SPA — fallback to index.html for client-side routing
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # OpenAlgo API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:5000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # FlintTrade backend API proxy
    location /ft-api/ {
        proxy_pass http://127.0.0.1:5100/ft-api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # WebSocket proxy
    location /ws {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 86400;
    }

    # Security headers
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
    gzip_min_length 1000;
}
NGINX_EOF

ln -sf /etc/nginx/sites-available/flinttrade /etc/nginx/sites-enabled/flinttrade
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

ok "Nginx configured"

# ── Step 7: Install systemd units ─────────────────────────────────────
log "Installing systemd services..."

# OpenAlgo service
tee /etc/systemd/system/flinttrade-openalgo.service >/dev/null <<UNIT_EOF
[Unit]
Description=FlintTrade OpenAlgo Gateway
After=network.target

[Service]
Type=simple
User=$FLINTTRADE_USER
Group=$FLINTTRADE_USER
WorkingDirectory=$INSTALL_DIR/infra/openalgo
ExecStart=$VENV_DIR/bin/python app.py
Restart=on-failure
RestartSec=5
EnvironmentFile=$INSTALL_DIR/.env

# Security hardening — match standalone systemd units
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR/infra/openalgo/db
PrivateTmp=true

[Install]
WantedBy=flinttrade.target
UNIT_EOF

# FlintTrade backend service
tee /etc/systemd/system/flinttrade-backend.service >/dev/null <<UNIT_EOF
[Unit]
Description=FlintTrade Backend
After=network.target flinttrade-openalgo.service

[Service]
Type=simple
User=$FLINTTRADE_USER
Group=$FLINTTRADE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python -m packages.core.src.app
Restart=on-failure
RestartSec=5
EnvironmentFile=$INSTALL_DIR/.env

# Security hardening — match standalone systemd units
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR/data $FLINTTRADE_DATA
PrivateTmp=true

[Install]
WantedBy=flinttrade.target
UNIT_EOF

# Target unit (groups all FlintTrade services)
tee /etc/systemd/system/flinttrade.target >/dev/null <<UNIT_EOF
[Unit]
Description=FlintTrade Application
Requires=flinttrade-openalgo.service flinttrade-backend.service
After=flinttrade-openalgo.service flinttrade-backend.service

[Install]
WantedBy=multi-user.target
UNIT_EOF

systemctl daemon-reload
systemctl enable flinttrade.target
systemctl enable flinttrade-openalgo.service
systemctl enable flinttrade-backend.service
systemctl start flinttrade.target

ok "Systemd services enabled and started"

# ── Step 8: Set up SSL with Certbot ───────────────────────────────────
if [ -n "$DOMAIN" ]; then
    log "Obtaining SSL certificate for $DOMAIN..."
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || \
        warn "Certbot failed. Retry manually: sudo certbot --nginx -d $DOMAIN"
    ok "SSL configured"
else
    warn "No domain provided (set DOMAIN=example.com). Skipping SSL."
fi

# ── Step 9: Set up daily backup cron ──────────────────────────────────
log "Setting up daily backup..."

# Create backup password if it does not exist
if [ ! -f "$FLINTTRADE_DATA/backup-password" ]; then
    head -c 32 /dev/urandom | base64 > "$FLINTTRADE_DATA/backup-password"
    chmod 600 "$FLINTTRADE_DATA/backup-password"
    chown "$FLINTTRADE_USER:$FLINTTRADE_USER" "$FLINTTRADE_DATA/backup-password"
    ok "Backup password generated"
    warn "IMPORTANT: Back up ~/.flinttrade/backup-password separately. Without it, backups cannot be restored."
fi

# Add cron job for the service user
CRON_CMD="0 2 * * * RESTIC_PASSWORD_FILE=$FLINTTRADE_DATA/backup-password $INSTALL_DIR/infra/backup/backup.sh >> /var/log/flinttrade-backup.log 2>&1"
(crontab -u "$FLINTTRADE_USER" -l 2>/dev/null | grep -v "flinttrade/infra/backup/backup.sh" || true; echo "$CRON_CMD") | crontab -u "$FLINTTRADE_USER" -

ok "Daily backup cron set for 02:00 UTC"

# ── Step 10: Success message ──────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo -e "${GREEN}  FlintTrade installed successfully!${RESET}"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  Application URLs:"
if [ -n "$DOMAIN" ]; then
    echo "    Terminal:   https://$DOMAIN"
    echo "    OpenAlgo:   https://$DOMAIN/api/"
    echo "    WebSocket:  wss://$DOMAIN/ws"
else
    echo "    Terminal:   http://$(hostname -I | awk '{print $1}'):80"
    echo "    OpenAlgo:   http://localhost:5000"
    echo "    WebSocket:  ws://localhost:8765"
fi
echo ""
echo "  Service management:"
echo "    sudo systemctl status flinttrade.target"
echo "    sudo systemctl restart flinttrade.target"
echo "    sudo journalctl -u flinttrade-openalgo -f"
echo "    sudo journalctl -u flinttrade-backend -f"
echo ""
echo "  Configuration:"
echo "    .env:       $INSTALL_DIR/.env"
echo "    User data:  $FLINTTRADE_DATA/"
echo "    Nginx:      /etc/nginx/sites-available/flinttrade"
echo "    Logs:       journalctl -u flinttrade-*"
echo ""
echo "  Next steps:"
echo "    1. Set OPENALGO_API_KEY in $INSTALL_DIR/.env"
echo "    2. Configure broker credentials in OpenAlgo"
echo "    3. sudo systemctl restart flinttrade.target"
echo "    4. Visit the terminal URL to begin setup"
echo ""

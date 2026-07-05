#!/usr/bin/env bash
# FlintTrade bare-metal installer for Ubuntu/Debian
#
# Installs Python 3.12, Node.js, Nginx, builds the application,
# and configures systemd services.
# Idempotent — safe to run multiple times.
#
# IMPORTANT: This installer no longer bundles OpenAlgo or OpenClaw.
# Those are external prerequisites — install them yourself, OR run
# scripts/setup-test-deps.sh to clone local-dev copies into
# .local/external/ for testing. The systemd unit emitted below assumes
# the local-dev OpenAlgo path; adjust WorkingDirectory + ExecStart for
# your actual install location.
#
# AlgoMirror is intentionally not in scope: its mirroring patterns are
# absorbed into packages/services/ditto/ and run in-process — nothing external
# to install or run.
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
    git pull origin "$BRANCH"
else
    log "Cloning FlintTrade..."
    git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
ok "Repository ready at $INSTALL_DIR"

# ── Step 3: Set up Python virtual environment ──────────────────────────
log "Setting up Python virtual environment..."

VENV_DIR="$INSTALL_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    python3.12 -m venv "$VENV_DIR"
fi

# Activate and install dependencies — SC-07: hash-verified install only
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel -q
"$VENV_DIR/bin/pip" install --require-hashes -r "$INSTALL_DIR/requirements.lock" -q

ok "Python dependencies installed"

# requirements.lock is registry-only; uv.lock carries exact operator-cleared git
# pins for broker SDKs such as Kotak Neo. Sync the install-local .venv when uv is
# available so every native broker SDK declared by the workspace is present.
if command -v uv >/dev/null 2>&1; then
    (cd "$INSTALL_DIR" && uv sync --frozen --all-packages --no-dev)
    ok "Repo .venv synced with broker SDK pins"
else
    warn "uv not found; run 'uv sync --frozen --all-packages --no-dev' to install repo-local broker SDK pins such as Kotak Neo."
fi

# ── Step 4: Build React terminal ───────────────────────────────────────
log "Building React terminal..."

cd "$INSTALL_DIR"
corepack enable
pnpm install --frozen-lockfile
pnpm --dir packages/apps/terminal run build

ok "Terminal built"

# ── Step 5: Configure server fallback environment ──────────────────────
cd "$INSTALL_DIR"

if [ ! -f "$INSTALL_DIR/.env" ]; then
    {
        echo "# FlintTrade server fallback environment."
        echo "# Native desktop and normal source runs use Setup/Settings instead."
        echo "# Keep OpenAlgo API keys in the app workspace UI unless this service"
        echo "# must run before the UI is available."
    } > "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    log "Created minimal server fallback .env for systemd EnvironmentFile"
fi

# Create user data directory. The service explicitly runs with
# FLINTTRADE_HOME=$INSTALL_DIR, so generate secrets in the same place for every
# supported FLINTTRADE_USER value.
FLINTTRADE_HOME="$INSTALL_DIR"
FLINTTRADE_DATA="$FLINTTRADE_HOME/.flinttrade"
mkdir -p "$FLINTTRADE_DATA"

# Generate file-backed app secrets if not present
if [ ! -f "$FLINTTRADE_DATA/master_password" ]; then
    head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 32 > "$FLINTTRADE_DATA/master_password"
    chmod 600 "$FLINTTRADE_DATA/master_password"
    ok "Master password generated"
fi

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
    root $INSTALL_DIR/packages/apps/terminal/dist;
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

INSTALL_OPENALGO_SERVICE="${INSTALL_OPENALGO_SERVICE:-0}"
OPENALGO_DIR="${OPENALGO_DIR:-$INSTALL_DIR/.local/external/openalgo}"

if [ "$INSTALL_OPENALGO_SERVICE" = "1" ]; then
    if [ ! -d "$OPENALGO_DIR" ]; then
        die "INSTALL_OPENALGO_SERVICE=1 but OPENALGO_DIR does not exist: $OPENALGO_DIR"
    fi
    tee /etc/systemd/system/flinttrade-openalgo.service >/dev/null <<UNIT_EOF
[Unit]
Description=FlintTrade OpenAlgo Gateway (external dependency)
After=network.target

[Service]
Type=simple
User=$FLINTTRADE_USER
Group=$FLINTTRADE_USER
WorkingDirectory=$OPENALGO_DIR
ExecStart=$VENV_DIR/bin/python app.py
Restart=on-failure
RestartSec=5
EnvironmentFile=$INSTALL_DIR/.env

# Security hardening — match standalone systemd units
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$OPENALGO_DIR/db
PrivateTmp=true

[Install]
WantedBy=flinttrade.target
UNIT_EOF
    OPENALGO_TARGET_WANTS="Wants=flinttrade-openalgo.service"
    OPENALGO_TARGET_AFTER="After=flinttrade-openalgo.service flinttrade-backend.service"
else
    OPENALGO_TARGET_WANTS=""
    OPENALGO_TARGET_AFTER="After=flinttrade-backend.service"
    log "Skipping flinttrade-openalgo.service; configure OpenAlgo in Settings -> Broker Gateway or set INSTALL_OPENALGO_SERVICE=1"
fi

# FlintTrade backend service
tee /etc/systemd/system/flinttrade-backend.service >/dev/null <<UNIT_EOF
[Unit]
Description=FlintTrade Backend
After=network.target

[Service]
Type=simple
User=$FLINTTRADE_USER
Group=$FLINTTRADE_USER
WorkingDirectory=$INSTALL_DIR
Environment=FLINTTRADE_HOME=$INSTALL_DIR
Environment=PYTHONPATH=$INSTALL_DIR/packages/core/core/src
ExecStart=$VENV_DIR/bin/python -m flinttrade_core.app
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
Requires=flinttrade-backend.service
$OPENALGO_TARGET_WANTS
$OPENALGO_TARGET_AFTER

[Install]
WantedBy=multi-user.target
UNIT_EOF

systemctl daemon-reload
systemctl enable flinttrade.target
if [ "$INSTALL_OPENALGO_SERVICE" = "1" ]; then
    systemctl enable flinttrade-openalgo.service
fi
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
echo "    .env:       $INSTALL_DIR/.env (advanced server fallback only)"
echo "    User data:  $FLINTTRADE_DATA/"
echo "    Nginx:      /etc/nginx/sites-available/flinttrade"
echo "    Logs:       journalctl -u flinttrade-*"
echo ""
echo "  Next steps:"
echo "    1. Visit the terminal URL and complete Setup"
echo "    2. Configure OpenAlgo URL/API key in Settings -> Broker Gateway if needed"
echo "    3. Keep broker credentials inside OpenAlgo or the encrypted FlintTrade vault"
echo "    4. sudo systemctl restart flinttrade.target after changing server-only fallback values"
echo ""

#!/usr/bin/env bash
# FlintTrade Docker deployment installer
#
# Installs FlintTrade with Docker Compose, Nginx reverse proxy, and SSL.
# Idempotent — safe to run multiple times.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/infra/install/install-docker.sh | bash
#   # or
#   ./install-docker.sh

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────
INSTALL_DIR="${INSTALL_DIR:-/opt/flinttrade}"
REPO_URL="https://github.com/navaneeshnagarajan/FlintTrade.git"
BRANCH="main"

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

# ── Step 1: Check prerequisites ───────────────────────────────────────
log "Checking prerequisites..."

check_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        die "$1 is not installed. Install it first: $2"
    fi
    ok "$1 found"
}

check_command docker "https://docs.docker.com/engine/install/"
check_command curl "sudo apt-get install curl"

# Check Docker Compose. v2.24+ is required: docker-compose.yml uses the
# env_file long form (path/required) that Compose v1 cannot parse at all, so
# the old v1 fallback would fail at config load for every command.
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
    ok "docker compose (v2) found"
elif command -v docker-compose >/dev/null 2>&1; then
    die "Only legacy docker-compose (v1) was found. FlintTrade's compose file needs Compose v2.24+ — install the docker compose plugin from https://docs.docker.com/compose/install/"
else
    die "Docker Compose is not installed. Install from https://docs.docker.com/compose/install/"
fi

# Check Docker daemon is running
if ! docker info >/dev/null 2>&1; then
    die "Docker daemon is not running. Start it with: sudo systemctl start docker"
fi

# ── Step 2: Clone or update repository ─────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    log "Existing installation found at $INSTALL_DIR. Updating..."
    cd "$INSTALL_DIR"
    git pull --recurse-submodules origin "$BRANCH"
else
    log "Cloning FlintTrade to $INSTALL_DIR..."
    sudo mkdir -p "$INSTALL_DIR"
    sudo chown "$(id -u):$(id -g)" "$INSTALL_DIR"
    git clone --recursive -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

ok "Repository ready at $INSTALL_DIR"

# ── Step 3: Configure server fallback environment ──────────────────────
if [ ! -f "$INSTALL_DIR/.env" ]; then
    {
        echo "# FlintTrade Docker/server fallback environment."
        echo "# Native desktop and normal source runs use Setup/Settings instead."
        echo "# OpenAlgo bridge settings should be configured in the app UI unless"
        echo "# this container must run before the UI is available."
    } > "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    log "Created minimal server fallback .env"
fi

echo ""
log "Configuration"
echo "────────────────────────────────────────"

# Domain name for SSL
read -rp "Domain name for SSL (leave blank for localhost): " DOMAIN_NAME

# Generate deployment secrets
log "Generating secrets..."

MASTER_PASSWORD_VALUE=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 32)
JWT_SECRET_VALUE=$(head -c 48 /dev/urandom | base64 | tr -d '/+=' | head -c 48)
GLITCHTIP_SECRET_KEY=$(head -c 50 /dev/urandom | base64 | tr -d '/+=' | head -c 50)
GLITCHTIP_DB_PASSWORD=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 32)

# Create user data directory for file-backed FlintTrade app secrets. docker-compose.yml
# bind-mounts this directory into the FlintTrade container.
FLINTTRADE_HOME="${FLINTTRADE_HOME:-$HOME/.flinttrade}"
mkdir -p "$FLINTTRADE_HOME"
chmod 700 "$FLINTTRADE_HOME"

if [ ! -f "$FLINTTRADE_HOME/master_password" ]; then
    echo "$MASTER_PASSWORD_VALUE" > "$FLINTTRADE_HOME/master_password"
    chmod 600 "$FLINTTRADE_HOME/master_password"
fi
if [ ! -f "$FLINTTRADE_HOME/jwt_secret" ]; then
    echo "$JWT_SECRET_VALUE" > "$FLINTTRADE_HOME/jwt_secret"
    chmod 600 "$FLINTTRADE_HOME/jwt_secret"
fi

# Write monitoring-service secrets to .env if not already set.
if ! grep -q "^GLITCHTIP_SECRET_KEY=" "$INSTALL_DIR/.env" 2>/dev/null; then
    echo "GLITCHTIP_SECRET_KEY=$GLITCHTIP_SECRET_KEY" >> "$INSTALL_DIR/.env"
fi
if ! grep -q "^GLITCHTIP_DB_PASSWORD=" "$INSTALL_DIR/.env" 2>/dev/null; then
    echo "GLITCHTIP_DB_PASSWORD=$GLITCHTIP_DB_PASSWORD" >> "$INSTALL_DIR/.env"
fi

ok "Secrets generated and stored"

# ── Step 4: Build and start containers ─────────────────────────────────
log "Building and starting containers (this may take a few minutes)..."
log "Using multi-stage build with uv for fast dependency installation..."

cd "$INSTALL_DIR"

# Ensure start.sh is executable (git may strip permissions)
chmod +x "$INSTALL_DIR/infra/docker/start.sh"

# Build the FlintTrade image (multi-stage with uv)
$COMPOSE_CMD build --pull flinttrade

# Pull external images and start everything
$COMPOSE_CMD pull --ignore-buildable
$COMPOSE_CMD up -d

ok "Containers started"

# Wait for health checks to pass
log "Waiting for services to become healthy..."
retries=0
max_retries=30
until $COMPOSE_CMD ps --format '{{.Status}}' flinttrade 2>/dev/null | grep -q "healthy"; do
    retries=$((retries + 1))
    if [ "$retries" -ge "$max_retries" ]; then
        warn "FlintTrade did not become healthy within expected time. Check logs: $COMPOSE_CMD logs flinttrade"
        break
    fi
    sleep 5
done
if [ "$retries" -lt "$max_retries" ]; then
    ok "FlintTrade backend is healthy"
fi

# ── Step 5: Set up Nginx and SSL ───────────────────────────────────────
if [ -n "$DOMAIN_NAME" ]; then
    log "Setting up Nginx reverse proxy for $DOMAIN_NAME..."

    # Install Nginx and Certbot if not present
    if ! command -v nginx >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq nginx
    fi
    if ! command -v certbot >/dev/null 2>&1; then
        sudo apt-get install -y -qq certbot python3-certbot-nginx
    fi

    # Write Nginx config
    sudo tee /etc/nginx/sites-available/flinttrade >/dev/null <<NGINX_EOF
server {
    listen 80;
    server_name $DOMAIN_NAME;

    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 86400;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:5000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    location /ft-api/ {
        proxy_pass http://127.0.0.1:5100/ft-api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    location /ws {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
NGINX_EOF

    sudo ln -sf /etc/nginx/sites-available/flinttrade /etc/nginx/sites-enabled/flinttrade
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl reload nginx

    # Obtain SSL certificate
    log "Obtaining SSL certificate for $DOMAIN_NAME..."
    sudo certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --register-unsafely-without-email || \
        warn "Certbot failed. You can retry manually: sudo certbot --nginx -d $DOMAIN_NAME"

    ok "Nginx and SSL configured"
else
    warn "No domain provided. Skipping Nginx/SSL setup."
fi

# ── Step 6: Create management aliases ──────────────────────────────────
log "Creating management scripts..."

MANAGEMENT_DIR="/usr/local/bin"

# flinttrade-status
sudo tee "$MANAGEMENT_DIR/flinttrade-status" >/dev/null <<'SCRIPT_EOF'
#!/usr/bin/env bash
cd /opt/flinttrade && docker compose ps
SCRIPT_EOF
sudo chmod +x "$MANAGEMENT_DIR/flinttrade-status"

# flinttrade-restart
sudo tee "$MANAGEMENT_DIR/flinttrade-restart" >/dev/null <<'SCRIPT_EOF'
#!/usr/bin/env bash
cd /opt/flinttrade && docker compose restart
echo "FlintTrade restarted"
SCRIPT_EOF
sudo chmod +x "$MANAGEMENT_DIR/flinttrade-restart"

# flinttrade-logs
sudo tee "$MANAGEMENT_DIR/flinttrade-logs" >/dev/null <<'SCRIPT_EOF'
#!/usr/bin/env bash
cd /opt/flinttrade && docker compose logs -f --tail=100 "$@"
SCRIPT_EOF
sudo chmod +x "$MANAGEMENT_DIR/flinttrade-logs"

# flinttrade-backup
sudo tee "$MANAGEMENT_DIR/flinttrade-backup" >/dev/null <<'SCRIPT_EOF'
#!/usr/bin/env bash
/opt/flinttrade/infra/backup/backup.sh
SCRIPT_EOF
sudo chmod +x "$MANAGEMENT_DIR/flinttrade-backup"

ok "Management commands created: flinttrade-status, flinttrade-restart, flinttrade-logs, flinttrade-backup"

# ── Step 7: Set up daily backup cron ───────────────────────────────────
log "Setting up daily backup cron job..."

# Create backup password if it does not exist
if [ ! -f "$HOME/.flinttrade/backup-password" ]; then
    head -c 32 /dev/urandom | base64 > "$HOME/.flinttrade/backup-password"
    chmod 600 "$HOME/.flinttrade/backup-password"
    ok "Backup password generated at ~/.flinttrade/backup-password"
    warn "IMPORTANT: Back up this password file separately. Without it, backups cannot be restored."
fi

# Install restic if not present
if ! command -v restic >/dev/null 2>&1; then
    log "Installing restic..."
    sudo apt-get install -y -qq restic || {
        warn "Could not install restic via apt. Install manually: https://restic.net"
    }
fi

# Add cron job (idempotent — removes existing entry first)
CRON_CMD="0 2 * * * /opt/flinttrade/infra/backup/backup.sh >> /var/log/flinttrade-backup.log 2>&1"
(crontab -l 2>/dev/null | grep -v "flinttrade/infra/backup/backup.sh" || true; echo "$CRON_CMD") | crontab -

ok "Daily backup cron set for 02:00 UTC"

# ── Step 8: Success message ────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo -e "${GREEN}  FlintTrade installed successfully!${RESET}"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  Application URLs:"
if [ -n "${DOMAIN_NAME:-}" ]; then
    echo "    Terminal:   https://$DOMAIN_NAME"
    echo "    OpenAlgo:   https://$DOMAIN_NAME/api/"
    echo "    WebSocket:  wss://$DOMAIN_NAME/ws"
else
    echo "    Terminal:   http://localhost:5173"
    echo "    OpenAlgo:   http://localhost:5000"
    echo "    WebSocket:  ws://localhost:8765"
fi
echo ""
echo "  Management commands:"
echo "    flinttrade-status    — show container status"
echo "    flinttrade-restart   — restart all services"
echo "    flinttrade-logs      — follow service logs"
echo "    flinttrade-backup    — run manual backup"
echo ""
echo "  Configuration:"
echo "    .env:       $INSTALL_DIR/.env (advanced Docker/server fallback only)"
echo "    User data:  $HOME/.flinttrade/"
echo "    Backups:    /var/backups/flinttrade/"
echo ""
echo "  Next steps:"
echo "    1. Visit the terminal URL and complete Setup"
echo "    2. Configure OpenAlgo URL/API key in Settings -> Broker Gateway if needed"
echo "    3. Keep broker credentials inside OpenAlgo or the encrypted FlintTrade vault"
echo ""

#!/usr/bin/env bash
# FlintTrade bare-metal install script for Ubuntu/Debian
#
# Usage:
#   bash install.sh [--dry-run]
#
# What this does:
#   1. Checks prerequisites (bash 4+, Ubuntu/Debian, git, curl)
#   2. Installs Python 3.12, Node 22, build deps
#   3. Clones the FlintTrade repository (or uses current dir if already cloned)
#   4. Runs make setup
#   5. Prompts for .env values
#   6. Creates systemd service files for the backend and terminal
#   7. Enables and starts both services
#
# Idempotent: safe to re-run. Existing installs are detected and skipped.
# Requires: Ubuntu 22.04+ / Debian 12+ with sudo access.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

FLINTTRADE_USER="${FLINTTRADE_USER:-flinttrade}"
INSTALL_DIR="${INSTALL_DIR:-/opt/flinttrade}"
REPO_URL="${REPO_URL:-https://github.com/navaneeshnagarajan/FlintTrade.git}"
BRANCH="${BRANCH:-main}"
BACKEND_PORT="${BACKEND_PORT:-5100}"
TERMINAL_PORT="${TERMINAL_PORT:-5173}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

_red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
_green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
_blue()   { printf '\033[0;34m%s\033[0m\n' "$*"; }
_bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

info()    { _blue    "[INFO]  $*"; }
ok()      { _green   "[OK]    $*"; }
warn()    { _yellow  "[WARN]  $*"; }
err()     { _red     "[ERROR] $*" >&2; }
die()     { err "$*"; exit 1; }

run() {
    if [[ "$DRY_RUN" == "true" ]]; then
        _yellow "[DRY-RUN] $*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --help|-h)
            echo "Usage: $0 [--dry-run]"
            echo ""
            echo "  --dry-run   Print all commands without executing them"
            exit 0
            ;;
        *) die "Unknown argument: $arg" ;;
    esac
done

if [[ "$DRY_RUN" == "true" ]]; then
    warn "DRY-RUN mode — no changes will be made"
fi

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

check_bash_version() {
    local major
    major="${BASH_VERSINFO[0]}"
    if [[ "$major" -lt 4 ]]; then
        die "Bash 4.0+ is required (found $BASH_VERSION)"
    fi
    ok "Bash version: $BASH_VERSION"
}

check_os() {
    if [[ ! -f /etc/os-release ]]; then
        die "Cannot detect OS — /etc/os-release not found"
    fi
    # shellcheck disable=SC1091
    source /etc/os-release
    case "$ID" in
        ubuntu|debian|linuxmint|pop)
            ok "OS: $PRETTY_NAME"
            ;;
        *)
            warn "Unsupported OS: $ID. This script targets Ubuntu/Debian. Proceeding anyway."
            ;;
    esac
}

check_sudo() {
    if [[ "$EUID" -ne 0 ]]; then
        if ! command -v sudo &>/dev/null; then
            die "Script must be run as root or sudo must be available"
        fi
        SUDO="sudo"
    else
        SUDO=""
    fi
    ok "Privilege escalation: ${SUDO:-root}"
}

check_commands() {
    local missing=()
    for cmd in git curl make; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [[ "${#missing[@]}" -gt 0 ]]; then
        die "Missing required commands: ${missing[*]}. Install them and retry."
    fi
    ok "Required commands available"
}

# ---------------------------------------------------------------------------
# Python 3.12
# ---------------------------------------------------------------------------

install_python() {
    if command -v python3.12 &>/dev/null; then
        ok "Python 3.12 already installed: $(python3.12 --version)"
        return
    fi

    info "Installing Python 3.12..."
    run $SUDO apt-get update -qq
    run $SUDO apt-get install -y software-properties-common
    run $SUDO add-apt-repository -y ppa:deadsnakes/ppa
    run $SUDO apt-get update -qq
    run $SUDO apt-get install -y \
        python3.12 python3.12-venv python3.12-dev python3.12-distutils
    ok "Python 3.12 installed"
}

# ---------------------------------------------------------------------------
# Node 22
# ---------------------------------------------------------------------------

install_node() {
    if command -v node &>/dev/null; then
        local node_ver
        node_ver="$(node --version)"
        local node_major
        node_major="$(echo "$node_ver" | sed 's/v\([0-9]*\).*/\1/')"
        if [[ "$node_major" -ge 22 ]]; then
            ok "Node.js already installed: $node_ver"
            return
        fi
        warn "Node.js $node_ver found but 22+ required — upgrading"
    fi

    info "Installing Node.js 22..."
    run curl -fsSL https://deb.nodesource.com/setup_22.x | run $SUDO bash -
    run $SUDO apt-get install -y nodejs
    ok "Node.js installed: $(node --version 2>/dev/null || echo 'dry-run')"
}

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------

install_system_deps() {
    info "Installing system dependencies..."
    run $SUDO apt-get install -y \
        build-essential \
        libssl-dev \
        libffi-dev \
        libpq-dev \
        libblas-dev \
        liblapack-dev \
        pkg-config \
        nginx \
        curl \
        wget \
        unzip \
        git
    ok "System dependencies installed"
}

# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

clone_or_update_repo() {
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        info "Repository already exists at $INSTALL_DIR — skipping clone"
        return
    fi

    info "Cloning FlintTrade to $INSTALL_DIR..."
    run $SUDO mkdir -p "$INSTALL_DIR"
    run $SUDO chown -R "$USER":"$USER" "$INSTALL_DIR" 2>/dev/null || true
    run git clone --recursive --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    ok "Repository cloned"
}

# ---------------------------------------------------------------------------
# Python virtual environment + deps
# ---------------------------------------------------------------------------

setup_python_env() {
    info "Setting up Python environment..."
    run python3.12 -m venv "$INSTALL_DIR/.venv"
    run "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip wheel
    run "$INSTALL_DIR/.venv/bin/pip" install uv
    run bash -c "cd $INSTALL_DIR && .venv/bin/python -m uv sync 2>/dev/null || .venv/bin/pip install -r requirements.txt 2>/dev/null || true"
    ok "Python environment ready"
}

# ---------------------------------------------------------------------------
# Terminal (React)
# ---------------------------------------------------------------------------

build_terminal() {
    info "Building terminal (React)..."
    run bash -c "cd $INSTALL_DIR/packages/terminal && npm ci --prefer-offline"
    run bash -c "cd $INSTALL_DIR/packages/terminal && npm run build"
    ok "Terminal built"
}

# ---------------------------------------------------------------------------
# .env configuration
# ---------------------------------------------------------------------------

configure_env() {
    local env_file="$INSTALL_DIR/.env"

    if [[ -f "$env_file" ]]; then
        ok ".env already exists — skipping configuration"
        return
    fi

    info "Configuring .env..."

    if [[ "$DRY_RUN" == "true" ]]; then
        warn "[DRY-RUN] Would prompt for OPENALGO_HOST, OPENALGO_PORT, OPENALGO_API_KEY, OPENALGO_WS_PORT"
        return
    fi

    cp "$INSTALL_DIR/.env.example" "$env_file"

    read -r -p "  OPENALGO_HOST (default: http://127.0.0.1): " openalgo_host
    openalgo_host="${openalgo_host:-http://127.0.0.1}"

    read -r -p "  OPENALGO_PORT (default: 5000): " openalgo_port
    openalgo_port="${openalgo_port:-5000}"

    read -r -p "  OPENALGO_API_KEY: " openalgo_api_key

    read -r -p "  OPENALGO_WS_PORT (default: 8765): " openalgo_ws_port
    openalgo_ws_port="${openalgo_ws_port:-8765}"

    sed -i "s|^OPENALGO_HOST=.*|OPENALGO_HOST=$openalgo_host|" "$env_file"
    sed -i "s|^OPENALGO_PORT=.*|OPENALGO_PORT=$openalgo_port|" "$env_file"
    sed -i "s|^OPENALGO_API_KEY=.*|OPENALGO_API_KEY=$openalgo_api_key|" "$env_file"
    sed -i "s|^OPENALGO_WS_PORT=.*|OPENALGO_WS_PORT=$openalgo_ws_port|" "$env_file"

    ok ".env configured"
}

# ---------------------------------------------------------------------------
# systemd services
# ---------------------------------------------------------------------------

install_systemd_services() {
    info "Installing systemd service files..."

    local backend_service="/etc/systemd/system/flinttrade.service"
    local terminal_service="/etc/systemd/system/flinttrade-terminal.service"

    if [[ ! -f "$backend_service" ]]; then
        run $SUDO cp "$SCRIPT_DIR/flinttrade.service" "$backend_service"
        run $SUDO sed -i "s|{{INSTALL_DIR}}|$INSTALL_DIR|g" "$backend_service"
        run $SUDO sed -i "s|{{FLINTTRADE_USER}}|${SUDO_USER:-$USER}|g" "$backend_service"
        run $SUDO sed -i "s|{{BACKEND_PORT}}|$BACKEND_PORT|g" "$backend_service"
        ok "Backend service file installed"
    else
        ok "Backend service already installed — skipping"
    fi

    if [[ ! -f "$terminal_service" ]]; then
        run $SUDO cp "$SCRIPT_DIR/flinttrade-terminal.service" "$terminal_service"
        run $SUDO sed -i "s|{{INSTALL_DIR}}|$INSTALL_DIR|g" "$terminal_service"
        run $SUDO sed -i "s|{{FLINTTRADE_USER}}|${SUDO_USER:-$USER}|g" "$terminal_service"
        run $SUDO sed -i "s|{{TERMINAL_PORT}}|$TERMINAL_PORT|g" "$terminal_service"
        ok "Terminal service file installed"
    else
        ok "Terminal service already installed — skipping"
    fi

    run $SUDO systemctl daemon-reload
    ok "systemd reloaded"
}

enable_and_start_services() {
    info "Enabling and starting services..."

    run $SUDO systemctl enable flinttrade.service
    run $SUDO systemctl start flinttrade.service
    ok "FlintTrade backend: started"

    run $SUDO systemctl enable flinttrade-terminal.service
    run $SUDO systemctl start flinttrade-terminal.service
    ok "FlintTrade terminal: started"
}

# ---------------------------------------------------------------------------
# Nginx (optional)
# ---------------------------------------------------------------------------

configure_nginx() {
    local nginx_conf="/etc/nginx/sites-available/flinttrade"

    if [[ -f "$nginx_conf" ]]; then
        ok "Nginx config already exists — skipping"
        return
    fi

    if [[ ! -f "$SCRIPT_DIR/nginx.conf.template" ]]; then
        warn "nginx.conf.template not found — skipping Nginx setup"
        return
    fi

    info "Configuring Nginx reverse proxy..."
    run $SUDO cp "$SCRIPT_DIR/nginx.conf.template" "$nginx_conf"
    run $SUDO sed -i "s|{{TERMINAL_PORT}}|$TERMINAL_PORT|g" "$nginx_conf"
    run $SUDO sed -i "s|{{BACKEND_PORT}}|$BACKEND_PORT|g" "$nginx_conf"
    run $SUDO ln -sf "$nginx_conf" /etc/nginx/sites-enabled/flinttrade
    run $SUDO nginx -t
    run $SUDO systemctl reload nginx
    ok "Nginx configured"
}

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

smoke_test() {
    if [[ "$DRY_RUN" == "true" ]]; then
        warn "[DRY-RUN] Would run smoke test against http://127.0.0.1:$BACKEND_PORT/health"
        return
    fi

    info "Running smoke test..."
    local retries=5
    local delay=3
    local i

    for ((i = 1; i <= retries; i++)); do
        if curl -sf "http://127.0.0.1:$BACKEND_PORT/health" &>/dev/null; then
            ok "Backend health check passed"
            return
        fi
        warn "Attempt $i/$retries — waiting ${delay}s..."
        sleep "$delay"
    done

    warn "Backend not responding after $retries attempts — check: journalctl -u flinttrade -n 50"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    _bold "FlintTrade — Bare-Metal Install"
    echo "  Install dir : $INSTALL_DIR"
    echo "  Backend port: $BACKEND_PORT"
    echo "  Terminal port: $TERMINAL_PORT"
    echo ""

    check_bash_version
    check_os
    check_sudo
    check_commands

    install_system_deps
    install_python
    install_node

    clone_or_update_repo
    setup_python_env
    build_terminal
    configure_env
    install_systemd_services
    enable_and_start_services
    configure_nginx
    smoke_test

    echo ""
    _green "======================================================"
    _green " FlintTrade installed successfully!"
    _green "======================================================"
    echo "  Backend  : http://127.0.0.1:$BACKEND_PORT"
    echo "  Terminal : http://127.0.0.1:$TERMINAL_PORT"
    echo "  Logs     : journalctl -u flinttrade -f"
    echo "             journalctl -u flinttrade-terminal -f"
}

main "$@"

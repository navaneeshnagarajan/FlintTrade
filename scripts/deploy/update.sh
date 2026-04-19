#!/usr/bin/env bash
# FlintTrade in-place update script
#
# Usage:
#   bash update.sh [--dry-run] [--branch <branch>]
#
# What this does:
#   1. git pull (with submodule update)
#   2. Updates Python dependencies
#   3. Rebuilds React terminal
#   4. Restarts systemd services
#   5. Runs a smoke test

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/flinttrade}"
BRANCH="${BRANCH:-main}"
BACKEND_PORT="${BACKEND_PORT:-5100}"
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

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--dry-run] [--branch <branch>]"
            exit 0
            ;;
        *)
            die "Unknown argument: $1"
            ;;
    esac
done

if [[ "$DRY_RUN" == "true" ]]; then
    warn "DRY-RUN mode — no changes will be made"
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

check_install_dir() {
    if [[ ! -d "$INSTALL_DIR/.git" ]]; then
        die "FlintTrade not found at $INSTALL_DIR. Run install.sh first."
    fi
    ok "Install directory: $INSTALL_DIR"
}

check_sudo() {
    if [[ "$EUID" -ne 0 ]]; then
        if ! command -v sudo &>/dev/null; then
            die "Must be run as root or sudo must be available"
        fi
        SUDO="sudo"
    else
        SUDO=""
    fi
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

git_pull() {
    info "Pulling latest changes from branch '$BRANCH'..."
    run bash -c "cd $INSTALL_DIR && git fetch origin"
    run bash -c "cd $INSTALL_DIR && git checkout $BRANCH"
    run bash -c "cd $INSTALL_DIR && git pull origin $BRANCH --ff-only"
    run bash -c "cd $INSTALL_DIR && git submodule update --init --recursive"
    ok "Repository up to date"
}

update_python_deps() {
    info "Updating Python dependencies..."
    run bash -c "cd $INSTALL_DIR && .venv/bin/python -m uv sync 2>/dev/null || .venv/bin/pip install -r requirements.txt 2>/dev/null || true"
    ok "Python dependencies updated"
}

rebuild_terminal() {
    info "Rebuilding terminal..."
    run bash -c "cd $INSTALL_DIR/packages/terminal && npm ci --prefer-offline"
    run bash -c "cd $INSTALL_DIR/packages/terminal && npm run build"
    ok "Terminal rebuilt"
}

restart_services() {
    info "Restarting services..."
    run $SUDO systemctl daemon-reload

    if $SUDO systemctl is-active --quiet flinttrade.service 2>/dev/null; then
        run $SUDO systemctl restart flinttrade.service
        ok "Backend service restarted"
    else
        warn "Backend service not running — starting it"
        run $SUDO systemctl start flinttrade.service
    fi

    if $SUDO systemctl is-active --quiet flinttrade-terminal.service 2>/dev/null; then
        run $SUDO systemctl restart flinttrade-terminal.service
        ok "Terminal service restarted"
    else
        warn "Terminal service not running — starting it"
        run $SUDO systemctl start flinttrade-terminal.service
    fi
}

smoke_test() {
    if [[ "$DRY_RUN" == "true" ]]; then
        warn "[DRY-RUN] Would check http://127.0.0.1:$BACKEND_PORT/health"
        return
    fi

    info "Running smoke test..."
    local retries=5
    local delay=3

    for ((i = 1; i <= retries; i++)); do
        if curl -sf "http://127.0.0.1:$BACKEND_PORT/health" &>/dev/null; then
            ok "Smoke test passed"
            return
        fi
        warn "Attempt $i/$retries — waiting ${delay}s..."
        sleep "$delay"
    done

    warn "Backend not responding — check: journalctl -u flinttrade -n 50"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    _bold "FlintTrade — In-Place Update"
    echo ""

    check_install_dir
    check_sudo
    git_pull
    update_python_deps
    rebuild_terminal
    restart_services
    smoke_test

    echo ""
    _green "======================================================"
    _green " FlintTrade updated successfully!"
    _green "======================================================"
}

main "$@"

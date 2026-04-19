#!/usr/bin/env bash
# FlintTrade uninstall script
#
# Usage:
#   bash uninstall.sh [--dry-run] [--keep-data]
#
# What this does:
#   1. Stops and disables systemd services
#   2. Removes service files
#   3. Optionally removes ~/.flinttrade (user data) — asks for confirmation
#   4. Removes the install directory
#
# Idempotent: safe to re-run even if services are already removed.

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/flinttrade}"
DRY_RUN=false
KEEP_DATA=false

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
        --keep-data)
            KEEP_DATA=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--dry-run] [--keep-data]"
            echo ""
            echo "  --dry-run    Print all commands without executing them"
            echo "  --keep-data  Do not remove ~/.flinttrade user data"
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

stop_service() {
    local name="$1"
    if $SUDO systemctl is-active --quiet "$name" 2>/dev/null; then
        info "Stopping $name..."
        run $SUDO systemctl stop "$name"
        ok "$name stopped"
    else
        info "$name is not running — skipping stop"
    fi
}

disable_service() {
    local name="$1"
    if $SUDO systemctl is-enabled --quiet "$name" 2>/dev/null; then
        info "Disabling $name..."
        run $SUDO systemctl disable "$name"
        ok "$name disabled"
    else
        info "$name is not enabled — skipping disable"
    fi
}

remove_service_file() {
    local path="$1"
    if [[ -f "$path" ]]; then
        info "Removing $path..."
        run $SUDO rm -f "$path"
        ok "Removed $path"
    else
        info "$path not found — skipping"
    fi
}

# ---------------------------------------------------------------------------
# Main steps
# ---------------------------------------------------------------------------

stop_services() {
    stop_service flinttrade.service
    stop_service flinttrade-terminal.service
}

disable_services() {
    disable_service flinttrade.service
    disable_service flinttrade-terminal.service
}

remove_service_files() {
    remove_service_file /etc/systemd/system/flinttrade.service
    remove_service_file /etc/systemd/system/flinttrade-terminal.service
    run $SUDO systemctl daemon-reload
    ok "systemd reloaded"
}

remove_nginx_config() {
    local nginx_enabled="/etc/nginx/sites-enabled/flinttrade"
    local nginx_available="/etc/nginx/sites-available/flinttrade"

    if [[ -L "$nginx_enabled" ]] || [[ -f "$nginx_enabled" ]]; then
        info "Removing Nginx symlink..."
        run $SUDO rm -f "$nginx_enabled"
        ok "Nginx symlink removed"
    fi

    if [[ -f "$nginx_available" ]]; then
        info "Removing Nginx config..."
        run $SUDO rm -f "$nginx_available"
        ok "Nginx config removed"
    fi

    if command -v nginx &>/dev/null; then
        run $SUDO nginx -t 2>/dev/null && run $SUDO systemctl reload nginx || true
    fi
}

remove_install_dir() {
    if [[ -d "$INSTALL_DIR" ]]; then
        info "Removing install directory $INSTALL_DIR..."
        run $SUDO rm -rf "$INSTALL_DIR"
        ok "Install directory removed"
    else
        info "$INSTALL_DIR not found — skipping"
    fi
}

handle_user_data() {
    if [[ "$KEEP_DATA" == "true" ]]; then
        info "Keeping user data (--keep-data)"
        return
    fi

    local data_dir="$HOME/.flinttrade"

    if [[ ! -d "$data_dir" ]]; then
        info "No user data at $data_dir"
        return
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        warn "[DRY-RUN] Would prompt to remove $data_dir"
        return
    fi

    echo ""
    warn "User data found at $data_dir"
    warn "This contains: workspace settings, API keys, stored data"
    read -r -p "  Remove $data_dir? [y/N]: " confirm
    case "$confirm" in
        [yY]|[yY][eE][sS])
            rm -rf "$data_dir"
            ok "User data removed"
            ;;
        *)
            info "Keeping user data at $data_dir"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    _bold "FlintTrade — Uninstall"
    echo "  Install dir: $INSTALL_DIR"
    echo ""

    if [[ "$DRY_RUN" == "false" ]]; then
        warn "This will remove FlintTrade from $INSTALL_DIR"
        read -r -p "  Continue? [y/N]: " confirm
        case "$confirm" in
            [yY]|[yY][eE][sS]) ;;
            *) die "Aborted." ;;
        esac
    fi

    check_sudo
    stop_services
    disable_services
    remove_service_files
    remove_nginx_config
    handle_user_data
    remove_install_dir

    echo ""
    _green "======================================================"
    _green " FlintTrade uninstalled."
    _green "======================================================"
}

main "$@"

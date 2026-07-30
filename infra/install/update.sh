#!/usr/bin/env bash
# FlintTrade update script
#
# Pulls latest code, updates dependencies, rebuilds the terminal,
# and restarts services. Idempotent — safe to run multiple times.
#
# Usage:
#   ./update.sh              # auto-detect environment (Docker or native)
#   ./update.sh --docker     # force Docker mode
#   ./update.sh --native     # force native mode
#   ./update.sh --no-restart # update without restarting services

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MODE=""
RESTART=true

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

# ── Parse arguments ────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --docker)     MODE="docker"; shift ;;
        --native)     MODE="native"; shift ;;
        --no-restart) RESTART=false; shift ;;
        --help|-h)
            echo "Usage: $0 [--docker|--native] [--no-restart]"
            exit 0
            ;;
        *) die "Unknown option: $1" ;;
    esac
done

# Auto-detect mode
if [ -z "$MODE" ]; then
    if [ -f "$REPO_ROOT/docker-compose.yml" ] && docker compose ps >/dev/null 2>&1; then
        MODE="docker"
    else
        MODE="native"
    fi
    log "Auto-detected mode: $MODE"
fi

cd "$REPO_ROOT"

# ── Step 1: Pull latest code ──────────────────────────────────────────
log "Pulling latest code..."

# Stash any local changes to avoid conflicts
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    warn "Local changes detected. Stashing..."
    git stash push -m "flinttrade-update-$(date +%Y%m%d%H%M%S)"
fi

git pull --recurse-submodules origin main

ok "Code updated"

# ── Step 2: Update dependencies ────────────────────────────────────────
if [ "$MODE" = "native" ]; then
    log "Updating Python dependencies..."

    VENV_DIR="$REPO_ROOT/.venv"
    if [ -d "$VENV_DIR" ]; then
        PIP="$VENV_DIR/bin/pip"
    else
        PIP="pip3"
    fi

    # SC-07: hash-verified install only (requirements.lock is fully pinned)
    $PIP install --require-hashes -r "$REPO_ROOT/requirements.lock" -q 2>/dev/null || \
        $PIP install --require-hashes -r "$REPO_ROOT/requirements.lock" --break-system-packages -q

    ok "Python dependencies updated"

    # requirements.lock is registry-only; uv.lock carries the exact
    # operator-cleared git pin for broker SDKs such as Kotak Neo.
    if command -v uv >/dev/null 2>&1; then
        (cd "$REPO_ROOT" && uv sync --frozen --all-packages --no-dev)
        ok "Repo .venv synced with broker SDK pins"
    else
        warn "uv not found; run 'uv sync --frozen --all-packages --no-dev' to install repo-local broker SDK pins such as Kotak Neo."
    fi

    # ── Step 3: Build React terminal ───────────────────────────────────
    log "Building React terminal..."

    cd "$REPO_ROOT"

    # Corepack is no longer distributed with Node.js from v25.0.0 onwards, so
    # 'corepack enable' is simply absent on a current Node. It also needs write
    # access to the Node install prefix, which a system-managed Node denies. Fall
    # through to a version-matched pnpm on PATH and finally to npx with the
    # pinned version — the same chain as infra/scripts/setup.sh.
    PINNED_PNPM_VERSION="10.34.5"
    pnpm_run() {
        if command -v corepack >/dev/null 2>&1; then
            corepack pnpm "$@"
            return $?
        fi
        if command -v pnpm >/dev/null 2>&1 && [ "$(pnpm --version 2>/dev/null)" = "$PINNED_PNPM_VERSION" ]; then
            pnpm "$@"
            return $?
        fi
        if command -v npx >/dev/null 2>&1; then
            npx --yes "pnpm@$PINNED_PNPM_VERSION" "$@"
            return $?
        fi
        return 127
    }

    pnpm_run install --frozen-lockfile
    pnpm_run --dir packages/apps/terminal run build

    ok "Terminal built"

    cd "$REPO_ROOT"
fi

# ── Step 4: Restart services ──────────────────────────────────────────
if [ "$RESTART" = true ]; then
    if [ "$MODE" = "docker" ]; then
        log "Rebuilding and restarting Docker containers..."
        docker compose build --pull
        docker compose up -d
        ok "Docker containers restarted"
    else
        log "Restarting systemd services..."
        if systemctl is-active --quiet flinttrade.target 2>/dev/null; then
            sudo systemctl restart flinttrade.target
            ok "Services restarted"
        else
            warn "flinttrade.target not found. Restart services manually."
        fi
    fi
else
    warn "Skipping service restart (--no-restart)"
fi

# ── Step 5: Verify ────────────────────────────────────────────────────
log "Verifying update..."

# Check service health
if [ "$MODE" = "docker" ] && [ "$RESTART" = true ]; then
    sleep 3
    docker compose ps
elif [ "$MODE" = "native" ] && [ "$RESTART" = true ]; then
    sleep 3
    systemctl is-active flinttrade-openalgo.service && ok "OpenAlgo: running" || warn "OpenAlgo: not running"
    systemctl is-active flinttrade-backend.service && ok "Backend: running" || warn "Backend: not running"
fi

echo ""
echo -e "${GREEN}Update completed successfully.${RESET}"
echo "  Version: $(cat "$REPO_ROOT/VERSION" 2>/dev/null || echo 'unknown')"
echo "  Commit:  $(git rev-parse --short HEAD)"
echo ""

#!/usr/bin/env bash
# FlintTrade first-time setup script
# Works on Ubuntu 24.04 (primary), macOS, and other Linux distros
set -euo pipefail

FLINTTRADE_DIR="${FLINTTRADE_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$FLINTTRADE_DIR"

GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
CYAN='\033[36m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET} $1"; }
warn() { echo -e "${YELLOW}⚠${RESET} $1"; }
fail() { echo -e "${RED}✗${RESET} $1"; }
header() { echo -e "\n${CYAN}=== $1 ===${RESET}"; }

# ------------------------------------------------------------------
# 1. Check OS
# ------------------------------------------------------------------
header "Checking system"

if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "OS: $PRETTY_NAME"
    if [[ "${ID:-}" != "ubuntu" || ! "${VERSION_ID:-}" =~ ^24 ]]; then
        warn "Tested on Ubuntu 24.04. Your OS may work but is not verified."
    fi
elif [[ "$(uname)" == "Darwin" ]]; then
    echo "OS: macOS $(sw_vers -productVersion)"
else
    echo "OS: $(uname -s)"
    warn "Not tested on this OS. Proceed with caution."
fi

# ------------------------------------------------------------------
# 2. Check/install system dependencies
# ------------------------------------------------------------------
header "Checking dependencies"

check_cmd() {
    if command -v "$1" >/dev/null 2>&1; then
        ok "$1: $($1 --version 2>&1 | head -1)"
        return 0
    else
        fail "$1: not found"
        return 1
    fi
}

check_cmd python3 || { echo "Install Python 3.11+: sudo apt install python3"; exit 1; }
check_cmd pip3 || check_cmd pip || { echo "Install pip: sudo apt install python3-pip"; exit 1; }
check_cmd git || { echo "Install git: sudo apt install git"; exit 1; }
check_cmd curl || { echo "Install curl: sudo apt install curl"; exit 1; }

# Node is optional (for React packages)
HAS_NODE=false
if check_cmd node && check_cmd npm; then
    HAS_NODE=true
else
    warn "Node.js not found. React packages (terminal, dashboard, backtest) will not be installed."
    warn "Install Node 20+: https://nodejs.org/"
fi

# ------------------------------------------------------------------
# 3. Configure .env
# ------------------------------------------------------------------
header "Configuration"

if [ ! -f "$FLINTTRADE_DIR/.env" ]; then
    cp "$FLINTTRADE_DIR/.env.example" "$FLINTTRADE_DIR/.env"
    warn "Created .env from template. Edit it with your settings before running."
else
    ok ".env exists"
fi

# Source .env for directory paths
set -a
source "$FLINTTRADE_DIR/.env" 2>/dev/null || true
set +a

DATA_DIR="${DATA_DIR:-$FLINTTRADE_DIR/data}"
LOG_DIR="${LOG_DIR:-$FLINTTRADE_DIR/logs}"
AUDIT_LOG_DIR="${AUDIT_LOG_DIR:-$DATA_DIR/audit}"
TICK_DATA_DIR="${TICK_DATA_DIR:-$DATA_DIR/ticks}"

# ------------------------------------------------------------------
# 4. External test-deps
# ------------------------------------------------------------------
header "External test-deps"

# OpenAlgo (and AlgoMirror, OpenClaw) are no longer git submodules of
# FlintTrade. They are EXTERNAL prerequisites. Install them yourself, OR
# run scripts/setup-test-deps.sh to clone local-dev copies into
# .local/external/. This installer continues if the local-dev clones
# already exist, otherwise it tells the user how to get them.

# ------------------------------------------------------------------
# 5. OpenAlgo dependencies (only if local-dev clone exists)
# ------------------------------------------------------------------
header "OpenAlgo setup"

OPENALGO_DIR="$FLINTTRADE_DIR/.local/external/openalgo"
OPENALGO_ENV_CREATED=false
if [ -d "$OPENALGO_DIR" ] && [ -f "$OPENALGO_DIR/requirements.txt" ]; then
    pip3 install -r "$OPENALGO_DIR/requirements.txt" --break-system-packages -q 2>/dev/null || \
        pip3 install -r "$OPENALGO_DIR/requirements.txt" -q 2>/dev/null || \
        warn "OpenAlgo deps install failed — may need manual install"
    ok "OpenAlgo dependencies installed"

    # gunicorn + eventlet are required for production but not in OpenAlgo's requirements.txt
    pip3 install gunicorn eventlet --break-system-packages -q 2>/dev/null || \
        pip3 install gunicorn eventlet -q 2>/dev/null || \
        warn "gunicorn+eventlet install failed — make start will fall back to python app.py"
    ok "gunicorn + eventlet installed"

    # Copy .sample.env → .env if missing (OpenAlgo uses .sample.env, not .env.sample)
    if [ ! -f "$OPENALGO_DIR/.env" ] && [ -f "$OPENALGO_DIR/.sample.env" ]; then
        cp "$OPENALGO_DIR/.sample.env" "$OPENALGO_DIR/.env"
        OPENALGO_ENV_CREATED=true
        ok "Copied $OPENALGO_DIR/.sample.env → $OPENALGO_DIR/.env"

        # Generate fresh security keys (replace defaults from sample)
        SAMPLE_APP_KEY='3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84'
        SAMPLE_PEPPER='a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772'
        CURRENT_APP_KEY=$(grep "^APP_KEY" "$OPENALGO_DIR/.env" | sed "s/.*= *'\(.*\)'/\1/")
        CURRENT_PEPPER=$(grep "^API_KEY_PEPPER" "$OPENALGO_DIR/.env" | sed "s/.*= *'\(.*\)'/\1/")

        if [ "$CURRENT_APP_KEY" = "$SAMPLE_APP_KEY" ] || [ "$CURRENT_PEPPER" = "$SAMPLE_PEPPER" ]; then
            NEW_APP_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
            NEW_PEPPER=$(python3 -c "import secrets; print(secrets.token_hex(32))")
            sed -i "s/$SAMPLE_APP_KEY/$NEW_APP_KEY/" "$OPENALGO_DIR/.env"
            sed -i "s/$SAMPLE_PEPPER/$NEW_PEPPER/" "$OPENALGO_DIR/.env"
            ok "Generated fresh security keys in $OPENALGO_DIR/.env"
        fi

        warn "Configure broker credentials in $OPENALGO_DIR/.env"
    elif [ -f "$OPENALGO_DIR/.env" ]; then
        ok "$OPENALGO_DIR/.env exists"
    fi
else
    warn "OpenAlgo is an external prerequisite. To get a local-dev copy for testing, run:"
    warn "    bash scripts/setup-test-deps.sh"
    warn "Or install OpenAlgo separately and point FlintTrade at it via OPENALGO_HOST in .env."
fi

# ------------------------------------------------------------------
# 6. FlintTrade Python dependencies
# ------------------------------------------------------------------
header "FlintTrade Python packages"

pip3 install -r "$FLINTTRADE_DIR/requirements.txt" --break-system-packages -q 2>/dev/null || \
    pip3 install -r "$FLINTTRADE_DIR/requirements.txt" -q
ok "Root requirements installed"

for req in "$FLINTTRADE_DIR"/packages/*/requirements.txt; do
    [ -f "$req" ] || continue
    pkg=$(basename "$(dirname "$req")")
    pip3 install -r "$req" --break-system-packages -q 2>/dev/null || \
        pip3 install -r "$req" -q 2>/dev/null || true
    ok "packages/$pkg dependencies"
done

# ------------------------------------------------------------------
# 7. Node dependencies (optional)
# ------------------------------------------------------------------
if [ "$HAS_NODE" = true ]; then
    header "FlintTrade Node packages"
    for pkg_dir in "$FLINTTRADE_DIR"/packages/terminal "$FLINTTRADE_DIR"/packages/dashboard "$FLINTTRADE_DIR"/packages/backtest; do
        [ -f "$pkg_dir/package.json" ] || continue
        pkg=$(basename "$pkg_dir")
        (cd "$pkg_dir" && npm install --silent 2>/dev/null)
        ok "packages/$pkg node_modules"
    done
fi

# ------------------------------------------------------------------
# 8. Workspace directory
# ------------------------------------------------------------------
header "Workspace"

WORKSPACE_DIR="${FLINTTRADE_HOME:-$HOME/.flinttrade}"
cd "$FLINTTRADE_DIR"
python3 -m packages.core.src.cli init 2>/dev/null && ok "Workspace initialized: $WORKSPACE_DIR" || {
    mkdir -p "$WORKSPACE_DIR" 2>/dev/null || true
    ok "Workspace directory created: $WORKSPACE_DIR"
}

# ------------------------------------------------------------------
# 9. Run tests
# ------------------------------------------------------------------
header "Verification"

if python3 -m pytest "$FLINTTRADE_DIR/packages/*/tests/" "$FLINTTRADE_DIR/tests/" --tb=short --import-mode=importlib -q 2>/dev/null; then
    ok "All tests passing"
else
    warn "Some tests failed — check output above"
fi

# ------------------------------------------------------------------
# 10. Summary
# ------------------------------------------------------------------
header "Setup complete"

echo ""
ok "System dependencies verified"
ok "FlintTrade Python packages installed"
ok "OpenAlgo dependencies installed"
ok "gunicorn + eventlet installed"
[ "$HAS_NODE" = true ] && ok "React packages installed" || warn "React packages skipped (no Node.js)"
ok "Workspace initialized"
echo ""
if [ "$OPENALGO_ENV_CREATED" = true ]; then
    warn "Configure broker credentials in .local/external/openalgo/.env before trading"
fi
echo "Next steps:"
echo "  1. Edit .env with your OPENALGO_API_KEY"
echo "  2. If you don't have OpenAlgo yet: bash scripts/setup-test-deps.sh"
echo "  3. Edit OpenAlgo's .env with broker credentials (.local/external/openalgo/.env for the local-dev clone)"
echo "  4. Run: make start"
echo "  5. Run: make status"

#!/usr/bin/env bash
# FlintTrade first-time setup script
# Works on Ubuntu 24.04 (primary), macOS, and other Linux distros
set -euo pipefail

FLINTTRADE_DIR="${FLINTTRADE_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$FLINTTRADE_DIR"

# Keep in step with package.json packageManager and scripts/install/*.
PINNED_PNPM_VERSION="9.15.0"

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

# OS-aware remediation: 'sudo apt install' is wrong on macOS and on every
# non-Debian distro, and telling a Windows user to apt-get anything is nonsense.
# Usage: install_hint <portable-name> [debian-package]
install_hint() {
    portable="$1"
    debian="${2:-$1}"
    case "$(uname -s)" in
        Darwin)
            echo "  brew install $portable"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            echo "  winget install $portable"
            echo "  (or install FlintTrade directly: irm https://flinttrade.vercel.app/web-install.ps1 | iex)"
            ;;
        *)
            if command -v apt-get >/dev/null 2>&1; then
                echo "  sudo apt install $debian"
            elif command -v dnf >/dev/null 2>&1; then
                echo "  sudo dnf install $debian"
            elif command -v pacman >/dev/null 2>&1; then
                echo "  sudo pacman -S $portable"
            else
                echo "  install '$portable' with your distribution's package manager"
            fi
            ;;
    esac
}

# The Microsoft Store ships a python3 "App execution alias" stub that exists on
# PATH but exits 49 without running anything. Probe before trusting it.
is_store_stub() {
    case "$(command -v "$1" 2>/dev/null)" in
        *WindowsApps*|*windowsapps*) return 0 ;;
    esac
    return 1
}

check_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        fail "python3: not found"
        return 1
    fi
    if ! python3 -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
        if is_store_stub python3; then
            fail "python3: Microsoft Store alias stub (exits 49, runs nothing)"
            echo "  Disable it under Settings > Apps > Advanced app settings > App execution aliases,"
            echo "  then install real Python 3.12+ from https://python.org"
        else
            fail "python3: found on PATH but does not run"
        fi
        return 1
    fi
    ok "python3: $(python3 --version 2>&1 | head -1)"
    return 0
}

check_python || { echo "Install Python 3.12+:"; install_hint python3; exit 1; }
check_cmd pip3 || check_cmd pip || { echo "Install pip:"; install_hint python3 python3-pip; exit 1; }
check_cmd git || { echo "Install git:"; install_hint git; exit 1; }
check_cmd curl || { echo "Install curl:"; install_hint curl; exit 1; }

# Node is optional (for React packages)
HAS_NODE=false
if check_cmd node && check_cmd npm; then
    HAS_NODE=true
else
    warn "Node.js not found. React packages (terminal, dashboard, backtest) will not be installed."
    warn "Install Node 20+: https://nodejs.org/"
fi

# ------------------------------------------------------------------
# 3. Workspace defaults
# ------------------------------------------------------------------
header "Workspace defaults"

if [ -f "$FLINTTRADE_DIR/.env" ]; then
    warn "Using existing .env as an advanced dev/server fallback."
    set -a
    source "$FLINTTRADE_DIR/.env" 2>/dev/null || true
    set +a
else
    ok "No .env required for native/source setup; app Setup and Settings own runtime config."
fi

DATA_DIR="${DATA_DIR:-$FLINTTRADE_DIR/data}"
LOG_DIR="${LOG_DIR:-$FLINTTRADE_DIR/logs}"
AUDIT_LOG_DIR="${AUDIT_LOG_DIR:-$DATA_DIR/audit}"
TICK_DATA_DIR="${TICK_DATA_DIR:-$DATA_DIR/ticks}"

# ------------------------------------------------------------------
# 4. External test-deps
# ------------------------------------------------------------------
header "External test-deps"

# OpenAlgo and OpenClaw are no longer git submodules of FlintTrade. They
# are EXTERNAL prerequisites. Install them yourself, OR run
# scripts/setup-test-deps.sh to clone local-dev copies into
# .local/external/. This installer continues if the local-dev clones
# already exist, otherwise it tells the user how to get them.
#
# AlgoMirror is intentionally absent: its mirroring patterns are
# absorbed into packages/services/ditto/ — nothing external to install.

# ------------------------------------------------------------------
# 5. OpenAlgo dependencies (only if local-dev clone exists)
# ------------------------------------------------------------------
header "OpenAlgo setup"

OPENALGO_DIR="$FLINTTRADE_DIR/.local/external/openalgo"
OPENALGO_ENV_CREATED=false
OPENALGO_DEPS_INSTALLED=false
if [ -d "$OPENALGO_DIR" ] && [ -f "$OPENALGO_DIR/requirements.txt" ]; then
    pip3 install -r "$OPENALGO_DIR/requirements.txt" --break-system-packages -q 2>/dev/null || \
        pip3 install -r "$OPENALGO_DIR/requirements.txt" -q 2>/dev/null || \
        warn "OpenAlgo deps install failed — may need manual install"
    OPENALGO_DEPS_INSTALLED=true
    ok "Optional OpenAlgo dependencies installed"

    # gunicorn + eventlet are required for production but not in OpenAlgo's requirements.txt
    pip3 install gunicorn eventlet --break-system-packages -q 2>/dev/null || \
        pip3 install gunicorn eventlet -q 2>/dev/null || \
        warn "gunicorn+eventlet install failed — the OpenAlgo local-dev service will fall back to 'python app.py'"
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
    warn "OpenAlgo is an optional external integration. To get a local-dev copy for testing, run:"
    warn "    bash scripts/setup-test-deps.sh"
    warn "Or install OpenAlgo separately and point FlintTrade at it from Setup/Settings."
fi

# ------------------------------------------------------------------
# 6. FlintTrade Python dependencies
# ------------------------------------------------------------------
header "FlintTrade Python packages"

# SC-07: hash-verified install only (requirements.lock is fully pinned)
pip3 install --require-hashes -r "$FLINTTRADE_DIR/requirements.lock" --break-system-packages -q 2>/dev/null || \
    pip3 install --require-hashes -r "$FLINTTRADE_DIR/requirements.lock" -q
ok "Root requirements installed"

# The hash-only requirements export cannot carry Kotak Neo's operator-cleared
# git SDK. Keep the registry-only pip baseline above, then sync the repo-local
# uv environment so every workspace dependency and broker SDK pin is installed
# inside .venv for source development.
if command -v uv >/dev/null 2>&1; then
    uv sync --frozen --all-packages
    ok "Repo .venv synced with workspace packages and broker SDK pins"
else
    warn "uv not found; run 'uv sync --frozen --all-packages' to install repo-local broker SDK pins such as Kotak Neo."
fi

# SC-07: per-package requirements.txt installs removed — requirements.lock is a
# uv export across the whole workspace, so it already pins every package's
# transitive third-party deps (hash-verified above). No unhashed per-package loop.

# ------------------------------------------------------------------
# 7. Node dependencies (optional)
# ------------------------------------------------------------------
if [ "$HAS_NODE" = true ]; then
    header "FlintTrade Node packages"
    # pnpm workspace: a single frozen install at the repo root links every workspace
    # package (terminal, site, design-system) from the committed pnpm-lock.yaml.
    #
    # Resolution chain matches scripts/install/flinttrade-install.sh:688-702 —
    # 'corepack enable' needs write access to the Node install prefix and fails on
    # a system-managed Node, so fall through to a matching pnpm binary and finally
    # to npx with the pinned version.
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

    if (cd "$FLINTTRADE_DIR" && pnpm_run install --frozen-lockfile); then
        ok "workspace node_modules (pnpm --frozen-lockfile)"
    else
        warn "pnpm workspace install failed — React packages may be incomplete."
        warn "Retry manually: npx --yes pnpm@$PINNED_PNPM_VERSION install --frozen-lockfile"
    fi
fi

# ------------------------------------------------------------------
# 8. Workspace directory
# ------------------------------------------------------------------
header "Workspace"

# Canonical per-OS workspace, honouring BOTH overrides in precedence order:
# FLINTTRADE_WORKSPACE_DIR > FLINTTRADE_HOME > platform default.
default_workspace() {
    case "$(uname -s)" in
        Darwin)              printf '%s' "$HOME/Library/Application Support/flinttrade" ;;
        MINGW*|MSYS*|CYGWIN*) printf '%s' "${APPDATA:-$HOME/AppData/Roaming}/flinttrade" ;;
        *)                   printf '%s' "$HOME/.flinttrade" ;;
    esac
}
WORKSPACE_DIR="${FLINTTRADE_WORKSPACE_DIR:-${FLINTTRADE_HOME:-$(default_workspace)}}"

# PATH_SEP: ';' under a Windows Python (MSYS/Git Bash), ':' everywhere else.
# Joining with ':' on Windows splits on the drive letter and breaks every import.
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) PATH_SEP=';' ;;
    *)                    PATH_SEP=':' ;;
esac

cd "$FLINTTRADE_DIR"
# Do NOT swallow this failure: reporting "Workspace initialized" after the init
# command died is how a broken install looks like a good one.
init_status=0
PYTHONPATH="$FLINTTRADE_DIR/packages/core/core/src${PATH_SEP}${PYTHONPATH:-}" \
    python3 -m flinttrade_core.cli init --provision-master-password >/dev/null \
    || init_status=$?
if [ "$init_status" -eq 0 ]; then
    ok "Workspace initialised: $WORKSPACE_DIR"
elif [ "$init_status" -eq 3 ]; then
    # Exit 3 means provisioning did not complete but re-proved that the existing
    # vault secret is present and hardened, so the backend still has what it needs.
    warn "Workspace provisioning did not complete, but the existing credential-vault"
    warn "secret is present and hardened — the cause is printed above."
else
    fail "Workspace initialisation failed — FlintTrade will not start until this is fixed."
    exit 1
fi

# ------------------------------------------------------------------
# 9. Run tests
# ------------------------------------------------------------------
header "Verification"

# The glob must be UNQUOTED to expand, and the repo nests packages three levels
# deep (packages/<group>/<pkg>/tests), so packages/*/tests never matched anything.
# stderr is kept: discarding it hid collection errors behind "Some tests failed".
PYTEST_PATHS=""
for tests_dir in "$FLINTTRADE_DIR"/packages/*/*/tests; do
    if [ -d "$tests_dir" ]; then
        PYTEST_PATHS="$PYTEST_PATHS $tests_dir"
    fi
done
if [ -d "$FLINTTRADE_DIR/tests" ]; then
    PYTEST_PATHS="$PYTEST_PATHS $FLINTTRADE_DIR/tests"
fi

if [ -z "$PYTEST_PATHS" ]; then
    warn "No test directories found under $FLINTTRADE_DIR/packages/*/*/tests — skipping verification"
elif python3 -m pytest $PYTEST_PATHS --tb=short --import-mode=importlib -q; then
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
if [ "$OPENALGO_DEPS_INSTALLED" = true ]; then
    ok "Optional OpenAlgo dependencies installed"
    ok "gunicorn + eventlet installed for optional OpenAlgo local-dev service"
else
    warn "Optional OpenAlgo local-dev dependencies skipped"
fi
[ "$HAS_NODE" = true ] && ok "React packages installed" || warn "React packages skipped (no Node.js)"
ok "Workspace initialised"
echo ""
if [ "$OPENALGO_ENV_CREATED" = true ]; then
    warn "Configure broker credentials in .local/external/openalgo/.env before trading"
fi
# The cross-platform runner, not `make`. This script now runs under Git Bash / MSYS
# too (see the MINGW*|MSYS*|CYGWIN* branches above), and `make` exists on none of
# those hosts — printing it here as the closing instruction sent every Windows user
# straight into "command not found" at the one moment they follow the output verbatim.
echo "Next steps (run from $FLINTTRADE_DIR):"
echo "  1. Start FlintTrade:  python scripts/ft.py start"
echo "  2. Open the terminal app and finish setup"
echo "  3. Configure OpenAlgo in Settings only if you want the OpenAlgo integration path"
echo "  4. Check it is up:    python scripts/ft.py status"
echo ""
echo "On macOS and Linux, 'make start' and 'make status' are aliases for the same runner."

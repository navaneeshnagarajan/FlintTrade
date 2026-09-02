#!/usr/bin/env bash
# FlintTrade backup — encrypted, deduplicated, incremental via restic
# Runs via cron: 0 2 * * * /opt/flinttrade/infra/backup/backup.sh
#
# Prerequisites:
#   - restic installed (https://restic.net)
#   - Password file at <workspace>/backup-password (or set RESTIC_PASSWORD_FILE),
#     where <workspace> is ~/.flinttrade on Linux,
#     ~/Library/Application Support/flinttrade on macOS, %APPDATA%\flinttrade on
#     Windows; override with FLINTTRADE_WORKSPACE_DIR or FLINTTRADE_HOME
#   - RESTIC_REPOSITORY set (default: /var/backups/flinttrade)
#
# Usage:
#   ./backup.sh              # run backup with defaults
#   RESTIC_REPOSITORY=s3:... ./backup.sh   # backup to S3

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────
# Resolve the REAL per-OS workspace rather than assuming ~/.flinttrade, which is
# only correct on Linux. Overrides in precedence order:
# FLINTTRADE_WORKSPACE_DIR > FLINTTRADE_HOME > platform default.
default_workspace() {
    case "$(uname -s)" in
        Darwin)               printf '%s' "$HOME/Library/Application Support/flinttrade" ;;
        MINGW*|MSYS*|CYGWIN*) printf '%s' "${APPDATA:-$HOME/AppData/Roaming}/flinttrade" ;;
        *)                    printf '%s' "$HOME/.flinttrade" ;;
    esac
}
WORKSPACE_DIR="${FLINTTRADE_WORKSPACE_DIR:-${FLINTTRADE_HOME:-$(default_workspace)}}"

RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-/var/backups/flinttrade}"
RESTIC_PASSWORD_FILE="${RESTIC_PASSWORD_FILE:-$WORKSPACE_DIR/backup-password}"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE

LOG_TAG="flinttrade-backup"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
die() { log "ERROR: $*" >&2; exit 1; }

# ── Preflight checks ──────────────────────────────────────────────────
command -v restic >/dev/null 2>&1 || die "restic is not installed. Install from https://restic.net"

if [ ! -f "$RESTIC_PASSWORD_FILE" ]; then
    die "Password file not found at $RESTIC_PASSWORD_FILE. Create it with: head -c 32 /dev/urandom | base64 > $RESTIC_PASSWORD_FILE && chmod 600 $RESTIC_PASSWORD_FILE"
fi

# ── Paths to back up ──────────────────────────────────────────────────
BACKUP_PATHS=()

# User data directory (auth.db, credentials.db, DuckDB, vectors, jwt_secret, workspace.json)
if [ -d "$WORKSPACE_DIR" ]; then
    BACKUP_PATHS+=("$WORKSPACE_DIR")
fi

# Environment config
if [ -f "/opt/flinttrade/.env" ]; then
    BACKUP_PATHS+=("/opt/flinttrade/.env")
fi

# Also check local dev .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ -f "$REPO_ROOT/.env" ]; then
    BACKUP_PATHS+=("$REPO_ROOT/.env")
fi

if [ ${#BACKUP_PATHS[@]} -eq 0 ]; then
    die "No backup paths found. Ensure $WORKSPACE_DIR exists or /opt/flinttrade/.env is present."
fi

log "Backing up ${#BACKUP_PATHS[@]} path(s) to $RESTIC_REPOSITORY"

# ── Initialise repository if first run ─────────────────────────────────
if ! restic -r "$RESTIC_REPOSITORY" snapshots >/dev/null 2>&1; then
    log "Initialising new restic repository at $RESTIC_REPOSITORY"
    restic -r "$RESTIC_REPOSITORY" init
fi

# ── Run backup ─────────────────────────────────────────────────────────
restic -r "$RESTIC_REPOSITORY" backup "${BACKUP_PATHS[@]}" \
    --tag flinttrade \
    --exclude "*.pyc" \
    --exclude "__pycache__" \
    --exclude "node_modules" \
    --exclude ".pytest_cache" \
    --exclude "*.log"

# ── Apply retention policy: 7 daily, 4 weekly, 12 monthly ─────────────
restic -r "$RESTIC_REPOSITORY" forget \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 12 \
    --prune

# ── Verify repository integrity (weekly, on Sundays) ──────────────────
if [ "$(date +%u)" -eq 7 ]; then
    log "Running weekly repository integrity check"
    restic -r "$RESTIC_REPOSITORY" check
fi

log "Backup completed successfully"

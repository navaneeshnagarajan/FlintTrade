#!/usr/bin/env bash
# FlintTrade restore — recover data from restic backup
#
# Usage:
#   ./restore.sh                    # restore latest snapshot to original locations
#   ./restore.sh --target /tmp/restore   # restore to a specific directory
#   ./restore.sh --snapshot abc123  # restore a specific snapshot
#   ./restore.sh --list             # list available snapshots
#   ./restore.sh --dry-run          # show what would be restored without writing
#
# Environment variables:
#   RESTIC_REPOSITORY    — backup repository path (default: /var/backups/flinttrade)
#   RESTIC_PASSWORD_FILE — path to password file (default: ~/.flinttrade/backup-password)

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────
RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-/var/backups/flinttrade}"
RESTIC_PASSWORD_FILE="${RESTIC_PASSWORD_FILE:-$HOME/.flinttrade/backup-password}"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE

TARGET_DIR=""
SNAPSHOT_ID="latest"
DRY_RUN=false
LIST_ONLY=false

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
die() { log "ERROR: $*" >&2; exit 1; }

# ── Parse arguments ────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --target)
            TARGET_DIR="$2"
            shift 2
            ;;
        --snapshot)
            SNAPSHOT_ID="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --list)
            LIST_ONLY=true
            shift
            ;;
        --help|-h)
            head -n 12 "$0" | tail -n 10
            exit 0
            ;;
        *)
            die "Unknown option: $1. Use --help for usage."
            ;;
    esac
done

# ── Preflight checks ──────────────────────────────────────────────────
command -v restic >/dev/null 2>&1 || die "restic is not installed. Install from https://restic.net"

if [ ! -f "$RESTIC_PASSWORD_FILE" ]; then
    die "Password file not found at $RESTIC_PASSWORD_FILE"
fi

# Verify repository exists
restic -r "$RESTIC_REPOSITORY" snapshots >/dev/null 2>&1 || \
    die "Cannot access repository at $RESTIC_REPOSITORY. Check path and password."

# ── List snapshots ─────────────────────────────────────────────────────
if [ "$LIST_ONLY" = true ]; then
    log "Available snapshots in $RESTIC_REPOSITORY:"
    echo ""
    restic -r "$RESTIC_REPOSITORY" snapshots --tag flinttrade
    echo ""
    log "Use --snapshot <id> to restore a specific snapshot"
    exit 0
fi

# ── Dry run ────────────────────────────────────────────────────────────
if [ "$DRY_RUN" = true ]; then
    log "Dry run — showing contents of snapshot '$SNAPSHOT_ID':"
    echo ""
    restic -r "$RESTIC_REPOSITORY" ls "$SNAPSHOT_ID" --tag flinttrade
    exit 0
fi

# ── Confirmation ───────────────────────────────────────────────────────
if [ -z "$TARGET_DIR" ]; then
    log "WARNING: This will restore files to their ORIGINAL locations."
    log "Existing files will be overwritten."
    echo ""
    read -rp "Are you sure you want to proceed? [y/N] " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        log "Restore cancelled."
        exit 0
    fi
    RESTORE_TARGET="/"
else
    mkdir -p "$TARGET_DIR"
    RESTORE_TARGET="$TARGET_DIR"
    log "Restoring to: $TARGET_DIR"
fi

# ── Stop services before restore ──────────────────────────────────────
if [ -z "$TARGET_DIR" ] && systemctl is-active --quiet flinttrade.target 2>/dev/null; then
    log "Stopping FlintTrade services before restore..."
    sudo systemctl stop flinttrade.target || true
    SERVICES_STOPPED=true
else
    SERVICES_STOPPED=false
fi

# ── Perform restore ───────────────────────────────────────────────────
log "Restoring snapshot '$SNAPSHOT_ID' from $RESTIC_REPOSITORY"

restic -r "$RESTIC_REPOSITORY" restore "$SNAPSHOT_ID" \
    --tag flinttrade \
    --target "$RESTORE_TARGET"

# ── Restart services ──────────────────────────────────────────────────
if [ "$SERVICES_STOPPED" = true ]; then
    log "Restarting FlintTrade services..."
    sudo systemctl start flinttrade.target || true
fi

log "Restore completed successfully"

if [ -n "$TARGET_DIR" ]; then
    log "Files restored to: $TARGET_DIR"
    log "Inspect the restored files, then copy them to their correct locations manually."
fi

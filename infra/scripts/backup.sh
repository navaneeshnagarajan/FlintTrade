#!/bin/bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../../.env" 2>/dev/null || true
BACKUP_DIR="${DATA_DIR:-/data/flinttrade}/backups/$(date +%Y-%m-%d)"
mkdir -p "$BACKUP_DIR"
for db in ~/FlintTrade/infra/openalgo/db/*.db; do [ -f "$db" ] && cp "$db" "$BACKUP_DIR/"; done
[ -f "${DUCKDB_PATH:-/data/flinttrade/flint.duckdb}" ] && cp "${DUCKDB_PATH}" "$BACKUP_DIR/"
find "${DATA_DIR:-/data/flinttrade}/backups/" -maxdepth 1 -mtime +30 -exec rm -rf {} + 2>/dev/null
echo "✅ Backup → $BACKUP_DIR"

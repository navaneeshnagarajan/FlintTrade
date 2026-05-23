#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/flinttrade-design/baselines/build-perf-2026-05-23.json"
TERM_LOG="$(mktemp -t flinttrade-terminal-build.XXXXXX.log)"
SITE_LOG="$(mktemp -t flinttrade-site-build.XXXXXX.log)"
PYTHON_BIN="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

run_timed() {
  local label="$1"
  local dir="$2"
  local log="$3"
  local start end
  start="$(date +%s)"
  (
    cd "$dir"
    npm run build
  ) 2>&1 | tee "$log"
  end="$(date +%s)"
  printf 'wall_seconds=%s\n' "$((end - start))" >> "$log"
  printf '%s build log: %s\n' "$label" "$log"
}

run_timed terminal "$ROOT/packages/apps/terminal" "$TERM_LOG"
run_timed site "$ROOT/packages/apps/site" "$SITE_LOG"

"$PYTHON_BIN" "$ROOT/scripts/emit_build_perf_json.py" \
  --terminal-log "$TERM_LOG" \
  --site-log "$SITE_LOG" \
  --output "$OUT"

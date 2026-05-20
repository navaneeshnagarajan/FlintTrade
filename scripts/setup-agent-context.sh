#!/usr/bin/env bash
# Scaffold .local/agent-context/ from the template tree shipped at
# templates/agent-context/. Idempotent: skips files that already exist.
#
# Run this once per fresh clone if you use a CLAUDE-aware or AGENTS-aware
# coding agent (Claude Code, Cursor, Aider, Continue, Codex, etc.). The
# resulting .local/agent-context/ tree is gitignored and machine-local —
# each contributor maintains their own.
#
# Usage:
#   bash scripts/setup-agent-context.sh           # scaffold missing files
#   bash scripts/setup-agent-context.sh --force   # overwrite existing files
#
# What it does:
#   templates/agent-context/CLAUDE.md.template      -> .local/agent-context/CLAUDE.md
#   templates/agent-context/AGENTS.md.template      -> .local/agent-context/AGENTS.md
#   templates/agent-context/PLAN.md.template        -> .local/agent-context/PLAN.md
#   templates/agent-context/packages/<pkg>/*.template -> .local/agent-context/packages/<pkg>/*

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SRC="templates/agent-context"
DST=".local/agent-context"

FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        -h|--help)
            sed -n '2,18p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown flag: $arg" >&2
            exit 2
            ;;
    esac
done

if [ ! -d "$SRC" ]; then
    echo "Templates not found at $SRC." >&2
    echo "Are you running this from the repo root after a fresh clone?" >&2
    exit 1
fi

mkdir -p "$DST/packages"

copied=0
skipped=0
forced=0

while IFS= read -r tpl; do
    rel="${tpl#$SRC/}"
    out="${rel%.template}"
    dst_path="$DST/$out"

    mkdir -p "$(dirname "$dst_path")"

    if [ -e "$dst_path" ]; then
        if [ "$FORCE" -eq 1 ]; then
            cp "$tpl" "$dst_path"
            forced=$((forced + 1))
        else
            skipped=$((skipped + 1))
        fi
    else
        cp "$tpl" "$dst_path"
        copied=$((copied + 1))
    fi
done < <(find "$SRC" -type f -name '*.template')

echo "Agent context scaffolded at $DST/"
echo "  copied:    $copied files"
echo "  skipped:   $skipped files (already present — use --force to overwrite)"
if [ "$FORCE" -eq 1 ]; then
    echo "  forced:    $forced files (overwritten)"
fi
echo ""
echo "These files are gitignored and machine-local. Edit them as needed for"
echo "your local coding-agent setup."

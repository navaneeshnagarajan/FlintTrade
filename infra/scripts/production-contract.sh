#!/bin/bash
# Shared production systemd install contract. Sourced by setup-production.sh
# and deploy.sh. No side effects — functions only.
#
# Ubuntu 24.04 / Python >= 3.12. The unit is hardcoded to /opt/flinttrade.

flinttrade_production_prefix() {
  printf '%s\n' "/opt/flinttrade"
}

flinttrade_assert_python_floor() {
  local python_bin="${1:-python3}"
  if ! "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
    echo "ERROR: Python >= 3.12 is required (Ubuntu 24.04)." >&2
    echo "Raspberry Pi OS Bookworm ships Python 3.11 — use the one-line or native installer." >&2
    return 1
  fi
}

flinttrade_assert_no_dir_override() {
  if [ -n "${FLINTTRADE_DIR:-}" ]; then
    echo "ERROR: FLINTTRADE_DIR is not supported. The systemd unit is hardcoded to /opt/flinttrade." >&2
    return 1
  fi
}

flinttrade_assert_safe_install_dir() {
  local dir="${1:-}"
  if [ -z "$dir" ]; then
    echo "ERROR: install dir is empty; expected /opt/flinttrade" >&2
    return 1
  fi
  case "$dir" in
    /*) ;;
    *)
      echo "ERROR: $dir is not an absolute path; expected /opt/flinttrade" >&2
      return 1
      ;;
  esac
  if [ -L "$dir" ]; then
    echo "ERROR: $dir is a symlink; refuse symlink install targets" >&2
    return 1
  fi
  if [ -e "$dir" ] && [ ! -d "$dir/.git" ]; then
    echo "ERROR: $dir exists but is not a git checkout; refuse a non-git install dir" >&2
    return 1
  fi
}

flinttrade_production_pythonpath() {
  local prefix="${1:-/opt/flinttrade}"
  printf '%s\n' "${prefix}/packages/core/core/src:${prefix}/packages/core/data/src:${prefix}/packages/core/historical/src:${prefix}/packages/core/indicators/src:${prefix}/packages/integrations/gateway/src:${prefix}/packages/integrations/webhooks/src:${prefix}/packages/services/ai/src:${prefix}/packages/services/automation/src:${prefix}/packages/services/backtest/src:${prefix}/packages/services/ditto/src:${prefix}/packages/services/engine/src:${prefix}/packages/services/journal/src:${prefix}/packages/services/screener/src"
}

flinttrade_pnpm_run() {
  local pinned="${FLINTTRADE_PNPM_VERSION:-10.34.5}"
  if command -v corepack >/dev/null 2>&1; then
    corepack pnpm "$@"
    return $?
  fi
  if command -v pnpm >/dev/null 2>&1 && [ "$(pnpm --version 2>/dev/null)" = "$pinned" ]; then
    pnpm "$@"
    return $?
  fi
  if command -v npx >/dev/null 2>&1; then
    npx --yes "pnpm@${pinned}" "$@"
    return $?
  fi
  echo "ERROR: pnpm ${pinned} is required (corepack, matching pnpm, or npx)." >&2
  return 127
}

flinttrade_build_terminal() {
  local prefix="${1:-/opt/flinttrade}"
  local contract="${FLINTTRADE_PRODUCTION_CONTRACT:-}"
  if [ -z "$contract" ]; then
    echo "ERROR: FLINTTRADE_PRODUCTION_CONTRACT is unset; cannot sudo pnpm." >&2
    return 1
  fi
  sudo env FLINTTRADE_PNPM_VERSION="${FLINTTRADE_PNPM_VERSION:-10.34.5}" \
    bash -c "set -euo pipefail; source \"\$1\"; cd \"\$2\"; flinttrade_pnpm_run install --frozen-lockfile; flinttrade_pnpm_run --dir packages/apps/terminal run build" \
    bash "$contract" "$prefix"
}

flinttrade_provision_workspace() {
  local prefix="${1:-/opt/flinttrade}"
  local service_user="${2:-www-data}"
  local venv_python="${3:-${prefix}/.venv/bin/python}"
  local workspace="${prefix}/.flinttrade"
  sudo mkdir -p "$workspace"
  sudo chown -R "${service_user}:${service_user}" "$workspace"
  sudo -u "$service_user" \
    env FLINTTRADE_WORKSPACE_DIR="$workspace" \
        PYTHONPATH="$(flinttrade_production_pythonpath "$prefix")" \
    "$venv_python" -m flinttrade_core.cli init --provision-master-password
}

flinttrade_apply_checkout_modes() {
  # Reclaim leftover service-user ownership and files created under a
  # restrictive sudo umask (077) so www-data can read newly deployed code.
  # Never recurse chmod into data/.flinttrade — those hold owner-only 0600
  # secrets (master_password, peppers, JWT, credential DBs).
  local dir="${1:-}"
  local service_user="${2:-www-data}"
  if [ -z "$dir" ] || [ ! -d "$dir" ]; then
    echo "ERROR: checkout dir is missing; expected /opt/flinttrade" >&2
    return 1
  fi
  sudo chown "root:${service_user}" "$dir"
  sudo chmod g+rX,go-w "$dir"
  local path base
  while IFS= read -r -d '' path; do
    base="$(basename "$path")"
    case "$base" in
      data|.flinttrade) continue ;;
    esac
    sudo chown -R "root:${service_user}" "$path"
    sudo chmod -R g+rX,go-w "$path"
  done < <(sudo find "$dir" -mindepth 1 -maxdepth 1 -print0)
  if [ -d "${dir}/data" ]; then
    sudo chown -R "${service_user}:${service_user}" "${dir}/data"
  fi
  if [ -d "${dir}/.flinttrade" ]; then
    sudo chown -R "${service_user}:${service_user}" "${dir}/.flinttrade"
  fi
  if [ -f "${dir}/.env" ]; then
    sudo chown "root:${service_user}" "${dir}/.env"
    sudo chmod 640 "${dir}/.env"
  fi
}

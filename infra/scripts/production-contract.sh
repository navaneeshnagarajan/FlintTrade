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

flinttrade_pinned_pnpm_version() {
  # One home for the pin: root package.json packageManager. Do not write the
  # version down a second time.
  local repo="${1:-}"
  if [ ! -f "${repo}/package.json" ]; then
    echo "ERROR: ${repo}/package.json is missing; cannot resolve the pinned pnpm." >&2
    return 1
  fi
  if command -v node >/dev/null 2>&1; then
    (cd "$repo" && node -p "const v=(require('./package.json').packageManager||'').split('+')[0];if(!v.startsWith('pnpm@'))throw new Error('root package.json must pin pnpm in its packageManager field');v.slice(5)")
    return
  fi
  python3 -c 'import json, sys
pin = json.load(open(sys.argv[1], encoding="utf-8")).get("packageManager", "").split("+")[0]
if not pin.startswith("pnpm@"):
    raise SystemExit("root package.json must pin pnpm in its packageManager field")
print(pin[len("pnpm@"):])' "${repo}/package.json"
}

flinttrade_pnpm_run() {
  local pinned="${FLINTTRADE_PNPM_VERSION:-}"
  if [ -z "$pinned" ]; then
    echo "ERROR: FLINTTRADE_PNPM_VERSION is unset; resolve it from package.json." >&2
    return 1
  fi
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
  local pinned
  if [ -z "$contract" ]; then
    echo "ERROR: FLINTTRADE_PRODUCTION_CONTRACT is unset; cannot sudo pnpm." >&2
    return 1
  fi
  pinned="$(flinttrade_pinned_pnpm_version "$prefix")" || return 1
  sudo env FLINTTRADE_PNPM_VERSION="$pinned" \
    bash -c "set -euo pipefail; source \"\$1\"; cd \"\$2\"; flinttrade_pnpm_run install --frozen-lockfile; flinttrade_pnpm_run --dir packages/apps/terminal run build" \
    bash "$contract" "$prefix"
  if [ ! -f "${prefix}/packages/apps/terminal/dist/index.html" ]; then
    echo "ERROR: terminal build did not produce packages/apps/terminal/dist/index.html" >&2
    return 1
  fi
}

flinttrade_provision_workspace() {
  local prefix="${1:-/opt/flinttrade}"
  local service_user="${2:-www-data}"
  local venv_python="${3:-${prefix}/.venv/bin/python}"
  local workspace="${prefix}/.flinttrade"
  if [ ! -x "$venv_python" ]; then
    echo "ERROR: $venv_python is missing; create the unit venv first." >&2
    return 1
  fi
  sudo mkdir -p "$workspace"
  sudo chown -R "${service_user}:${service_user}" "$workspace"
  local status=0
  sudo -u "$service_user" \
    env FLINTTRADE_HOME="$prefix" \
        FLINTTRADE_WORKSPACE_DIR="$workspace" \
        PYTHONPATH="$(flinttrade_production_pythonpath "$prefix")" \
    "$venv_python" -m flinttrade_core.cli init --provision-master-password \
    || status=$?
  if [ "$status" -eq 0 ]; then
    return 0
  fi
  if [ "$status" -eq 3 ]; then
    echo "WARNING: workspace provisioning did not complete, but the existing master password is present and hardened." >&2
    return 0
  fi
  echo "ERROR: workspace initialisation failed — the backend cannot start without master_password." >&2
  return 1
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

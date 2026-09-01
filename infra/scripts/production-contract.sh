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

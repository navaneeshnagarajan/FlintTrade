#!/bin/sh
# Canonical packaged source-build entrypoint. Tool acquisition and checksums are owned by Electron.
set -eu

if [ "$#" -ne 6 ]; then
  printf '%s\n' "usage: flinttrade-bootstrap.sh <candidate> <uv> <node> <corepack-js> <tools-root> <pnpm-version>" >&2
  exit 64
fi

candidate=$1
uv=$2
node=$3
corepack_js=$4
tools=$5
pnpm_version_expected=$6

[ "$pnpm_version_expected" = "9.15.0" ] || {
  printf '%s\n' "bootstrap entrypoint requires pnpm 9.15.0" >&2
  exit 66
}

for required in package.json pyproject.toml uv.lock pnpm-lock.yaml packages/apps/terminal/package.json; do
  [ -f "$candidate/$required" ] || {
    printf 'candidate is missing %s\n' "$required" >&2
    exit 65
  }
done
[ -f "$corepack_js" ] || {
  printf '%s\n' "verified Corepack JavaScript is missing" >&2
  exit 67
}

export COREPACK_DEFAULT_TO_LATEST=0
export COREPACK_HOME="$tools/corepack"
export UV_CACHE_DIR="$tools/uv-cache"
export UV_NO_EDITABLE=1
export UV_PYTHON=3.12
export UV_PYTHON_INSTALL_DIR="$tools/python"
PATH=$(dirname "$node"):$PATH
export PATH

"$uv" --version
"$node" --version
"$node" "$corepack_js" --version

cd "$candidate"
printf 'FLINTTRADE_BOOTSTRAP_PHASE\tsyncing-python\t48\tInstalling managed Python 3.12\n'
"$uv" python install 3.12
"$uv" venv --relocatable --python 3.12 .venv
"$uv" sync --frozen --all-packages --no-install-package flinttrade-ticks
printf 'FLINTTRADE_BOOTSTRAP_PHASE\tsyncing-javascript\t68\tInstalling pnpm 9.15.0 dependencies\n'
pnpm_version=$("$node" "$corepack_js" pnpm --version)
[ "$pnpm_version" = "9.15.0" ] || {
  printf 'Corepack resolved pnpm %s; expected 9.15.0.\n' "$pnpm_version" >&2
  exit 66
}
"$node" "$corepack_js" pnpm install --frozen-lockfile
printf 'FLINTTRADE_BOOTSTRAP_PHASE\tbuilding-terminal\t84\tBuilding the terminal for production\n'
"$node" "$corepack_js" pnpm --filter @flinttrade/terminal build

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

[ "$pnpm_version_expected" = "10.34.5" ] || {
  printf '%s\n' "bootstrap entrypoint requires pnpm 10.34.5" >&2
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
if [ -L "$tools/python" ] || { [ -e "$tools/python" ] && [ ! -d "$tools/python" ]; }; then
  printf '%s\n' "Refusing managed Python tool root because it is linked or not a directory." >&2
  exit 68
fi

reuse_virtual_environment=0
if [ -L "$candidate/.venv" ]; then
  printf '%s\n' "Refusing linked .venv in the managed source checkout." >&2
  exit 68
elif [ -e "$candidate/.venv" ]; then
  if [ ! -d "$candidate/.venv" ] || [ ! -f "$candidate/.venv/pyvenv.cfg" ] || [ -L "$candidate/.venv/pyvenv.cfg" ]; then
    printf '%s\n' "Refusing existing .venv because it is not a regular virtual environment." >&2
    exit 68
  fi
  if ! grep -Eq '^uv = [^[:space:]]+[[:space:]]*$' "$candidate/.venv/pyvenv.cfg" ||
    ! grep -Eq '^version_info = 3\.12\.[0-9]+[[:space:]]*$' "$candidate/.venv/pyvenv.cfg" ||
    ! grep -Eq '^relocatable = true[[:space:]]*$' "$candidate/.venv/pyvenv.cfg"; then
    printf '%s\n' "Refusing existing .venv because it is not a uv-managed relocatable Python 3.12 environment." >&2
    exit 68
  fi
  python_home=$(sed -n 's/^home = //p' "$candidate/.venv/pyvenv.cfg")
  python_home_canonical=$(CDPATH= cd "$python_home" 2>/dev/null && pwd -P) || {
    printf '%s\n' "Refusing existing .venv because its managed Python home is unavailable." >&2
    exit 68
  }
  tools_python_canonical=$(CDPATH= cd "$tools/python" 2>/dev/null && pwd -P) || {
    printf '%s\n' "Refusing existing .venv because its managed Python tool root is unavailable." >&2
    exit 68
  }
  case "$python_home_canonical/" in
    "$tools_python_canonical/"*) ;;
    *)
      printf '%s\n' "Refusing existing .venv because its Python is outside the managed tool root." >&2
      exit 68
      ;;
  esac
  unsafe_environment_links=$(
    find "$candidate/.venv" -type l -exec sh -c '
      environment_root=$1
      expected_python=$2
      shift 2
      for link do
        target=$(readlink "$link") || {
          printf "%s\n" "$link"
          continue
        }
        case "$link" in
          "$environment_root/lib64") [ "$target" = lib ] || printf "%s\n" "$link" ;;
          "$environment_root/bin/python") [ "$target" = "$expected_python" ] || printf "%s\n" "$link" ;;
          "$environment_root/bin/python3"|"$environment_root/bin/python3.12")
            [ "$target" = python ] || printf "%s\n" "$link"
            ;;
          *) printf "%s\n" "$link" ;;
        esac
      done
    ' sh "$candidate/.venv" "$python_home/python3.12" {} +
  )
  if [ -n "$unsafe_environment_links" ]; then
    printf '%s\n' "Refusing unexpected linked entry inside .venv in the managed source checkout." >&2
    exit 68
  fi
  reuse_virtual_environment=1
fi

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
if [ "$reuse_virtual_environment" -eq 0 ]; then
  "$uv" python install 3.12
  "$uv" venv --relocatable --python 3.12 .venv
fi
"$uv" sync --frozen --all-packages --no-install-package flinttrade-ticks
printf 'FLINTTRADE_BOOTSTRAP_PHASE\tsyncing-javascript\t68\tInstalling pnpm 10.34.5 dependencies\n'
pnpm_version=$("$node" "$corepack_js" pnpm --version)
[ "$pnpm_version" = "10.34.5" ] || {
  printf 'Corepack resolved pnpm %s; expected 10.34.5.\n' "$pnpm_version" >&2
  exit 66
}
"$node" "$corepack_js" pnpm install --frozen-lockfile
printf 'FLINTTRADE_BOOTSTRAP_PHASE\tbuilding-terminal\t84\tBuilding the terminal for production\n'
"$node" "$corepack_js" pnpm --filter @flinttrade/terminal build

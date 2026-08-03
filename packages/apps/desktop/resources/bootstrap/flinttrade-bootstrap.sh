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
PATH=/usr/bin:/bin
export PATH

normalise_absolute_path() (
  input=$1
  case "$input" in
    /*) ;;
    *) return 1 ;;
  esac
  result=
  rest=${input#/}
  while [ -n "$rest" ]; do
    component=${rest%%/*}
    if [ "$component" = "$rest" ]; then
      rest=
    else
      rest=${rest#*/}
    fi
    case "$component" in
      ""|.) ;;
      ..) result=${result%/*} ;;
      *) result=$result/$component ;;
    esac
  done
  printf '%s\n' "${result:-/}"
)

validate_managed_tools_path() (
  normalised_tools=$(normalise_absolute_path "$tools") || {
    printf '%s\n' "Refusing managed Python tool root because its tools path is not absolute." >&2
    exit 68
  }
  [ "$normalised_tools" = "$tools" ] || {
    printf '%s\n' "Refusing managed Python tool root because its tools path is not canonical." >&2
    exit 68
  }
  current=$normalised_tools
  while :; do
    if [ -L "$current" ]; then
      printf '%s\n' "Refusing managed Python tool root because its tools path contains a linked ancestor." >&2
      exit 68
    fi
    [ "$current" != / ] || break
    current=${current%/*}
    [ -n "$current" ] || current=/
  done
)

validate_managed_python_tree() (
  python_root="$tools/python"
  if [ -L "$python_root" ] || { [ -e "$python_root" ] && [ ! -d "$python_root" ]; }; then
    printf '%s\n' "Refusing managed Python tool root because it is linked or not a directory." >&2
    exit 68
  fi
  [ -e "$python_root" ] || exit 0

  canonical_root=$(CDPATH= cd "$python_root" 2>/dev/null && pwd -P) || {
    printf '%s\n' "Refusing managed Python tool root because it cannot be resolved." >&2
    exit 68
  }
  unsafe_python_links=$(
    find "$python_root" -type l -exec sh -c '
      canonical_root=$1
      shift
      normalise_absolute_path() {
        input=$1
        case "$input" in
          /*) ;;
          *) return 1 ;;
        esac
        result=
        rest=${input#/}
        while [ -n "$rest" ]; do
          component=${rest%%/*}
          if [ "$component" = "$rest" ]; then rest=; else rest=${rest#*/}; fi
          case "$component" in
            ""|.) ;;
            ..) result=${result%/*} ;;
            *) result=$result/$component ;;
          esac
        done
        printf "%s\n" "${result:-/}"
      }
      directory_is_within_root() {
        current=$1
        while :; do
          [ "$current" -ef "$canonical_root" ] && return 0
          [ "$current" != / ] || return 1
          current=${current%/*}
          [ -n "$current" ] || current=/
        done
      }
      for link do
        unsafe=0
        link_target=$(readlink "$link") || {
          printf "%s\n" "$link"
          continue
        }
        case "$link_target" in
          /*) target=$link_target ;;
          *) target=${link%/*}/$link_target ;;
        esac
        lexical_target=$(normalise_absolute_path "$target") || {
          printf "%s\n" "$link"
          continue
        }
        case "$lexical_target" in
          "$canonical_root"|"$canonical_root"/*) ;;
          *) unsafe=1 ;;
        esac
        [ -e "$link" ] || unsafe=1
        if [ "$unsafe" -eq 0 ]; then
          if [ -d "$target" ]; then
            physical_directory=$(CDPATH= cd -P "$target" 2>/dev/null && pwd -P) || unsafe=1
          else
            target_parent=${target%/*}
            [ -n "$target_parent" ] || target_parent=/
            physical_directory=$(CDPATH= cd -P "$target_parent" 2>/dev/null && pwd -P) || unsafe=1
          fi
        fi
        if [ "$unsafe" -eq 0 ] && ! directory_is_within_root "$physical_directory"; then
          unsafe=1
        fi
        [ "$unsafe" -eq 0 ] || printf "%s\n" "$link"
      done
    ' sh "$canonical_root" {} +
  )
  if [ -n "$unsafe_python_links" ]; then
    printf '%s\n' "Refusing managed Python tool root because a linked entry is broken or resolves outside it." >&2
    exit 68
  fi
)

read_uv_config_value() {
  expected_key=$1
  config_path=$2
  LC_ALL=C awk -v expected="$expected_key" '
    function trim(value) {
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      return value
    }
    {
      separator = index($0, "=")
      if (separator == 0) next
      key = trim(substr($0, 1, separator - 1))
      value = trim(substr($0, separator + 1))
      if (key !~ /^[A-Za-z0-9_-]+$/) invalid_file = 1
      normalised_key = tolower(key)
      version_alias = normalised_key == "version"
      if (version_alias) normalised_key = "version_info"
      if (normalised_key == expected) {
        occurrences++
        if (version_alias || key != normalised_key) invalid = 1
        result = value
      }
    }
    END {
      if (occurrences != 1 || invalid || invalid_file) exit 1
      print result
    }
  ' "$config_path"
}

config_has_utf8_bom() {
  config_path=$1
  prefix=$(LC_ALL=C od -An -tx1 -N3 "$config_path" | tr -d ' \t\r\n') || return 1
  [ "$prefix" = efbbbf ]
}

validate_virtual_environment_links() (
  environment_root=$1
  expected_python=$2
  error_message=$3
  unsafe_environment_links=$(
    find "$environment_root" -type l -exec sh -c '
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
    ' sh "$environment_root" "$expected_python" {} +
  )
  if [ -n "$unsafe_environment_links" ]; then
    printf '%s\n' "$error_message" >&2
    exit 68
  fi
)

safe_rename_python=
safe_rename_directory() {
  source_path=$1
  destination_path=$2
  "$safe_rename_python" -I -S -c '
import os
import stat
import sys

source, destination = sys.argv[1:]

def split_path(value):
    if not os.path.isabs(value):
        raise RuntimeError("rename path is not absolute")
    parent, name = os.path.split(value)
    if not name or name in (".", ".."):
        raise RuntimeError("rename entry name is invalid")
    return os.path.realpath(parent), name

source_parent, source_name = split_path(source)
destination_parent, destination_name = split_path(destination)
flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
source_parent_fd = os.open(source_parent, flags)
destination_parent_fd = os.open(destination_parent, flags)
try:
    before = os.stat(source_name, dir_fd=source_parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise RuntimeError("rename source is not an ordinary directory")
    try:
        os.stat(destination_name, dir_fd=destination_parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError("rename destination is occupied")
    os.rename(
        source_name,
        destination_name,
        src_dir_fd=source_parent_fd,
        dst_dir_fd=destination_parent_fd,
    )
    after = os.stat(destination_name, dir_fd=destination_parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(after.st_mode) or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
        raise RuntimeError("rename destination identity changed")
    try:
        os.stat(source_name, dir_fd=source_parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError("rename source still exists")
finally:
    os.close(destination_parent_fd)
    os.close(source_parent_fd)
' "$source_path" "$destination_path"
}

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
validate_managed_tools_path
[ -f "$corepack_js" ] || {
  printf '%s\n' "verified Corepack JavaScript is missing" >&2
  exit 67
}
if [ -L "$tools/python" ] || { [ -e "$tools/python" ] && [ ! -d "$tools/python" ]; }; then
  printf '%s\n' "Refusing managed Python tool root because it is linked or not a directory." >&2
  exit 68
fi

replace_virtual_environment=0
if [ -L "$candidate/.venv" ]; then
  printf '%s\n' "Refusing linked .venv in the managed source checkout." >&2
  exit 68
elif [ -e "$candidate/.venv" ]; then
  if [ ! -d "$candidate/.venv" ] || [ ! -f "$candidate/.venv/pyvenv.cfg" ] || [ -L "$candidate/.venv/pyvenv.cfg" ]; then
    printf '%s\n' "Refusing existing .venv because it is not a regular virtual environment." >&2
    exit 68
  fi
  if config_has_utf8_bom "$candidate/.venv/pyvenv.cfg"; then
    printf '%s\n' "Refusing existing .venv because its pyvenv.cfg is not valid BOM-less UTF-8." >&2
    exit 68
  fi
  configuration_valid=1
  uv_value=$(read_uv_config_value uv "$candidate/.venv/pyvenv.cfg") || configuration_valid=0
  version_value=$(read_uv_config_value version_info "$candidate/.venv/pyvenv.cfg") || configuration_valid=0
  relocatable_value=$(read_uv_config_value relocatable "$candidate/.venv/pyvenv.cfg") || configuration_valid=0
  python_home=$(read_uv_config_value home "$candidate/.venv/pyvenv.cfg") || configuration_valid=0
  [ "$uv_value" = 0.11.16 ] || configuration_valid=0
  case "$version_value" in
    3.12.*)
      version_patch=${version_value#3.12.}
      case "$version_patch" in ""|*[!0-9]*) configuration_valid=0 ;; esac
      ;;
    *) configuration_valid=0 ;;
  esac
  [ "$relocatable_value" = true ] || configuration_valid=0
  [ -n "$python_home" ] || configuration_valid=0
  if [ "$configuration_valid" -ne 1 ]; then
    printf '%s\n' "Refusing existing .venv because it is not a uv-managed relocatable Python 3.12 environment." >&2
    exit 68
  fi
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
  validate_managed_python_tree
  validate_virtual_environment_links \
    "$candidate/.venv" \
    "$python_home/python3.12" \
    "Refusing unexpected linked entry inside .venv in the managed source checkout."
  replace_virtual_environment=1
fi
validate_managed_python_tree

export COREPACK_DEFAULT_TO_LATEST=0
export COREPACK_HOME="$tools/corepack"
for uv_environment_name in $(env | sed -n 's/^\(UV_[A-Za-z0-9_]*\)=.*/\1/p'); do
  unset "$uv_environment_name"
done
export UV_CACHE_DIR="$tools/uv-cache"
export UV_MANAGED_PYTHON=1
export UV_NO_CONFIG=1
export UV_NO_EDITABLE=1
export UV_PROJECT="$candidate"
export UV_PYTHON=3.12
export UV_PYTHON_INSTALL_DIR="$tools/python"
export UV_WORKING_DIR="$candidate"
PATH=${node%/*}:$PATH
export PATH

swap_parent=$(mktemp -d "$candidate/.venv.flinttrade-swap.XXXXXX") || {
  printf '%s\n' "Could not create a private virtual-environment swap directory." >&2
  exit 68
}
chmod 700 "$swap_parent"
staging_virtual_environment="$swap_parent/staging"
backup_virtual_environment="$swap_parent/backup"
backup_created=0
bootstrap_completed=0
cleanup_staging_virtual_environment() {
  if [ "$backup_created" -eq 1 ] &&
    { [ -e "$backup_virtual_environment" ] || [ -L "$backup_virtual_environment" ]; }; then
    if [ -L "$backup_virtual_environment" ] || [ ! -d "$backup_virtual_environment" ]; then
      printf '%s\n' "Refusing an unsafe virtual-environment backup path during cleanup." >&2
      return
    fi
    if [ "$bootstrap_completed" -eq 0 ]; then
      if [ -e "$candidate/.venv" ] || [ -L "$candidate/.venv" ]; then
        if [ -e "$staging_virtual_environment" ] || [ -L "$staging_virtual_environment" ]; then
          printf '%s\n' "Virtual-environment rollback state is ambiguous." >&2
          return
        fi
        if [ -L "$candidate/.venv" ] || [ ! -d "$candidate/.venv" ]; then
          printf '%s\n' "Refusing to roll back an unsafe current virtual environment." >&2
          return
        fi
        safe_rename_directory "$candidate/.venv" "$staging_virtual_environment" || {
          printf '%s\n' "Failed to quarantine the replacement virtual environment during cleanup." >&2
          return
        }
      fi
      safe_rename_directory "$backup_virtual_environment" "$candidate/.venv" || {
        printf '%s\n' "Failed to restore the previous virtual environment during cleanup." >&2
        return
      }
      backup_created=0
    fi
    if [ "$bootstrap_completed" -eq 1 ]; then
      validate_virtual_environment_links \
        "$backup_virtual_environment" \
        "$python_home/python3.12" \
        "Refusing to clean a changed virtual-environment backup path."
      rm -rf -- "$backup_virtual_environment"
      backup_created=0
    fi
  elif [ "$backup_created" -eq 1 ]; then
    backup_created=0
  fi
  if [ -e "$staging_virtual_environment" ] || [ -L "$staging_virtual_environment" ]; then
    if [ -L "$staging_virtual_environment" ] || [ ! -d "$staging_virtual_environment" ]; then
      printf '%s\n' "Refusing to clean an unsafe virtual-environment staging path." >&2
      return
    fi
    rm -rf -- "$staging_virtual_environment"
  fi
  if [ -d "$swap_parent" ] && [ ! -L "$swap_parent" ]; then
    rmdir "$swap_parent" 2>/dev/null || true
  fi
}
trap cleanup_staging_virtual_environment EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
export UV_PROJECT_ENVIRONMENT="$staging_virtual_environment"

"$uv" --version
"$node" --version
"$node" "$corepack_js" --version

cd "$candidate"
printf 'FLINTTRADE_BOOTSTRAP_PHASE\tsyncing-python\t48\tInstalling managed Python 3.12\n'
"$uv" python install 3.12 --no-bin --no-config --directory "$candidate"
validate_managed_python_tree
tools_python_canonical=$(CDPATH= cd "$tools/python" 2>/dev/null && pwd -P) || {
  printf '%s\n' "Refusing an unavailable managed Python tool root." >&2
  exit 68
}
"$uv" venv --relocatable --python 3.12 "$staging_virtual_environment" \
  --no-project --no-config --managed-python --directory "$candidate"
"$uv" sync --frozen --all-packages --no-install-package flinttrade-ticks \
  --no-config --managed-python --directory "$candidate" --project "$candidate"

if [ -L "$staging_virtual_environment" ] ||
  [ ! -d "$staging_virtual_environment" ] ||
  [ ! -f "$staging_virtual_environment/pyvenv.cfg" ] ||
  [ -L "$staging_virtual_environment/pyvenv.cfg" ]; then
  printf '%s\n' "Refusing an invalid staged virtual environment." >&2
  exit 68
fi
if config_has_utf8_bom "$staging_virtual_environment/pyvenv.cfg"; then
  printf '%s\n' "Refusing staged .venv because its pyvenv.cfg is not valid BOM-less UTF-8." >&2
  exit 68
fi
staged_configuration_valid=1
staged_uv_value=$(read_uv_config_value uv "$staging_virtual_environment/pyvenv.cfg") || staged_configuration_valid=0
staged_version_value=$(read_uv_config_value version_info "$staging_virtual_environment/pyvenv.cfg") || staged_configuration_valid=0
staged_python_home=$(read_uv_config_value home "$staging_virtual_environment/pyvenv.cfg") || {
  staged_configuration_valid=0
  staged_python_home=
}
staged_relocatable=$(read_uv_config_value relocatable "$staging_virtual_environment/pyvenv.cfg") || {
  staged_configuration_valid=0
  staged_relocatable=
}
[ "$staged_uv_value" = 0.11.16 ] || staged_configuration_valid=0
case "$staged_version_value" in
  3.12.*)
    staged_version_patch=${staged_version_value#3.12.}
    case "$staged_version_patch" in ""|*[!0-9]*) staged_configuration_valid=0 ;; esac
    ;;
  *) staged_configuration_valid=0 ;;
esac
[ "$staged_relocatable" = true ] || staged_configuration_valid=0
[ -n "$staged_python_home" ] || staged_configuration_valid=0
if [ "$staged_configuration_valid" -ne 1 ]; then
  printf '%s\n' "Refusing staged .venv because it is not a uv-managed relocatable Python 3.12 environment." >&2
  exit 68
fi
staged_python_home_canonical=$(CDPATH= cd "$staged_python_home" 2>/dev/null && pwd -P) || {
  printf '%s\n' "Refusing an unavailable staged Python home." >&2
  exit 68
}
case "$staged_python_home_canonical/" in
  "$tools_python_canonical/"*) ;;
  *) printf '%s\n' "Refusing a staged Python home outside the managed tool root." >&2; exit 68 ;;
esac
safe_rename_python="$staged_python_home/python3.12"
[ -x "$safe_rename_python" ] || {
  printf '%s\n' "Refusing an unavailable managed Python rename helper." >&2
  exit 68
}
validate_virtual_environment_links \
  "$staging_virtual_environment" \
  "$staged_python_home/python3.12" \
  "Refusing unexpected linked entry inside the staged virtual environment."

if [ "$replace_virtual_environment" -eq 1 ]; then
  [ ! -L "$candidate/.venv" ] && [ -d "$candidate/.venv" ] || {
    printf '%s\n' "Refusing to replace a changed or linked existing virtual environment." >&2
    exit 68
  }
  validate_virtual_environment_links \
    "$candidate/.venv" \
    "$python_home/python3.12" \
    "Refusing to replace a changed existing virtual environment."
  backup_created=1
  safe_rename_directory "$candidate/.venv" "$backup_virtual_environment"
fi
if ! safe_rename_directory "$staging_virtual_environment" "$candidate/.venv"; then
  if [ "$replace_virtual_environment" -eq 1 ] &&
    [ -d "$backup_virtual_environment" ] && [ ! -L "$backup_virtual_environment" ]; then
    if [ ! -e "$candidate/.venv" ] && [ ! -L "$candidate/.venv" ] &&
      safe_rename_directory "$backup_virtual_environment" "$candidate/.venv"; then
      backup_created=0
    fi
  fi
  printf '%s\n' "Failed to promote the staged virtual environment." >&2
  exit 68
fi
export UV_PROJECT_ENVIRONMENT="$candidate/.venv"

printf 'FLINTTRADE_BOOTSTRAP_PHASE\tsyncing-javascript\t68\tInstalling pnpm 10.34.5 dependencies\n'
pnpm_version=$("$node" "$corepack_js" pnpm --version)
[ "$pnpm_version" = "10.34.5" ] || {
  printf 'Corepack resolved pnpm %s; expected 10.34.5.\n' "$pnpm_version" >&2
  exit 66
}
"$node" "$corepack_js" pnpm install --frozen-lockfile
printf 'FLINTTRADE_BOOTSTRAP_PHASE\tbuilding-terminal\t84\tBuilding the terminal for production\n'
"$node" "$corepack_js" pnpm --filter @flinttrade/terminal build
bootstrap_completed=1
if [ "$backup_created" -eq 1 ]; then
  [ ! -L "$backup_virtual_environment" ] && [ -d "$backup_virtual_environment" ] || {
    printf '%s\n' "Refusing to clean an unsafe virtual-environment backup path." >&2
    exit 68
  }
  validate_virtual_environment_links \
    "$backup_virtual_environment" \
    "$python_home/python3.12" \
    "Refusing to clean a changed virtual-environment backup path."
  rm -rf -- "$backup_virtual_environment"
  backup_created=0
fi
rmdir "$swap_parent"

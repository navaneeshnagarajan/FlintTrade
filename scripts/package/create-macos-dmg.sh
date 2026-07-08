#!/usr/bin/env bash
# Create a macOS DMG from the Tauri .app bundle using the generated Tauri
# create-dmg helper, but skip Finder AppleScript cosmetics. This is a fallback
# for headless/local macOS environments where osascript can hang or fail after
# the app bundle itself has already built successfully.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/package/create-macos-dmg.sh [--stamp PATH]

Options:
  --stamp PATH  Require the app bundle to contain files newer than PATH. This
                prevents a failed Tauri build from being hidden by stale output.
EOF
}

stamp_path=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --stamp)
      stamp_path="${2:-}"
      if [ -z "$stamp_path" ]; then
        echo "error: --stamp requires a path" >&2
        exit 2
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ "$(uname -s)" != "Darwin" ]; then
  echo "error: macOS DMG packaging only runs on Darwin" >&2
  exit 1
fi

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tauri_dir="$root_dir/packages/apps/desktop/src-tauri"
bundle_dir="$tauri_dir/target/release/bundle"
macos_dir="$bundle_dir/macos"
dmg_dir="$bundle_dir/dmg"
app_path="$macos_dir/FlintTrade.app"
dmg_script="$dmg_dir/bundle_dmg.sh"
icon_path="$dmg_dir/icon.icns"

if [ ! -d "$app_path" ]; then
  echo "error: expected app bundle not found: $app_path" >&2
  exit 1
fi
if [ ! -f "$dmg_script" ]; then
  echo "error: expected Tauri DMG helper not found: $dmg_script" >&2
  exit 1
fi
if [ ! -f "$icon_path" ]; then
  echo "error: expected DMG icon not found: $icon_path" >&2
  exit 1
fi
if [ -n "$stamp_path" ] && ! find "$app_path" -newer "$stamp_path" -print -quit | grep -q .; then
  echo "error: app bundle is not newer than the failed build stamp; refusing stale DMG fallback" >&2
  exit 1
fi

version="$(python3 - <<'PY' "$tauri_dir/tauri.conf.json"
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])
PY
)"
case "$(uname -m)" in
  arm64|aarch64) asset_arch="aarch64" ;;
  x86_64|amd64) asset_arch="x64" ;;
  *)
    echo "error: unsupported macOS architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

mkdir -p "$dmg_dir"
output_path="$dmg_dir/FlintTrade_${version}_${asset_arch}.dmg"
temp_dir="$(mktemp -d /tmp/flinttrade-dmg-src.XXXXXX)"
cleanup() {
  rm -rf "$temp_dir"
}
trap cleanup EXIT

cp -R "$app_path" "$temp_dir/FlintTrade.app"
rm -f "$output_path"

bash "$dmg_script" \
  --volname FlintTrade \
  --volicon "$icon_path" \
  --window-size 660 400 \
  --icon-size 128 \
  --icon FlintTrade.app 180 170 \
  --hide-extension FlintTrade.app \
  --app-drop-link 480 170 \
  --skip-jenkins \
  "$output_path" "$temp_dir"

echo "Created $output_path"

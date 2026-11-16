#!/usr/bin/env bash
# One-time preparation from an existing XFCE terminal; never changes autologin.
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$project_root"
# Cargo defaults to the manifest-local target directory in this standalone
# crate. Honour a caller-specified target directory as well, so the printed
# nested preview actually uses the binary produced by this build.
binary_dir="${CARGO_TARGET_DIR:-$project_root/components/riceplate-wayland/target}"
case "$binary_dir" in
    /*) ;;
    *) binary_dir="$project_root/$binary_dir" ;;
esac
binary_dir="$binary_dir/release"

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    echo "Build XP Luna as your normal desktop user, without sudo." >&2
    exit 1
fi
for binary in cargo python3; do
    command -v "$binary" >/dev/null || { echo "Missing tool: $binary" >&2; exit 1; }
done

echo "Building the schema-v12 native RicePlate (limited to two compile jobs)..."
CARGO_BUILD_JOBS=2 cargo build --locked --release --manifest-path \
    "$project_root/components/riceplate-wayland/Cargo.toml"

echo "Validating XP Luna without changing your selected desktop..."
python3 -c 'from pathlib import Path; from macrice.de import recipes; recipes.parse(Path("examples/wayland/xp-luna-columns.json").read_bytes())'
if python3 launcher.py de review --recipe xp-luna-columns --json >/dev/null 2>&1; then
    echo "XP Luna already imported. If you changed the recipe, inspect it before replacing your copy."
else
    python3 launcher.py de recipe-import --recipe "$project_root/examples/wayland/xp-luna-columns.json"
fi
# The old hard-coded checkout path was wrong when this helper was run from
# ~/RiceBowl or another directory. Print shell-escaped commands for the
# actual source tree instead of suggesting a non-existent project checkout.
if ! command -v labwc >/dev/null 2>&1; then
    echo "Warning: labwc is missing; the Wayland compositor preview cannot start." >&2
fi
if ! command -v swaybg >/dev/null 2>&1; then
    echo "Warning: swaybg is missing; XP Luna will launch without its wallpaper." >&2
fi
printf 'Built and validated XP Luna from %s\n' "$project_root"
printf 'Safe nested preview from XFCE:\n  cd %q && PATH=%q:$PATH python3 launcher.py de start --nested --panel native --recipe xp-luna-columns\n' \
    "$project_root" "$binary_dir"
printf 'Optional supervised full-session TTY trial:\n  bash %q\n' \
    "$project_root/scripts/try_wayland_xp_luna.sh"

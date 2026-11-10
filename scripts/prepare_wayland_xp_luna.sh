#!/usr/bin/env bash
# One-time preparation from an existing XFCE terminal; never changes autologin.
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$project_root"

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
echo "Ready. From a separate text console: bash ~/RiceBowl-Wayland-Test/scripts/try_wayland_xp_luna.sh"

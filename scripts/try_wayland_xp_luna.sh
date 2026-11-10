#!/usr/bin/env bash
# Supervised two-minute local Wayland test; exits back to the existing TTY.
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
binary_dir="$project_root/components/riceplate-wayland/target/release"
if [[ ! -x "$binary_dir/riceplate-native" ]]; then
    echo "Native RicePlate not built. Run scripts/prepare_wayland_xp_luna.sh in XFCE first." >&2
    exit 1
fi
cd "$project_root"
PATH="$binary_dir:$PATH" \
    timeout --signal=TERM --kill-after=5s 120s \
    python3 launcher.py de start --panel native --recipe xp-luna-columns

#!/bin/sh
# CI only: compare a real XWayland titlebar before and after a private labwc theme.
set -eu

source_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$source_root/components/riceplate-wayland/target/release/riceplate-native"
test -x "$native" || { echo 'Build riceplate-native first' >&2; exit 1; }
runtime=$(mktemp -d)
chmod 0700 "$runtime"
trap 'rm -r -- "$runtime"' EXIT
mkdir -m 0700 "$runtime/config"
export XDG_CONFIG_HOME="$runtime/config"
export XDG_RUNTIME_DIR="$runtime"
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=1
cp "$source_root/examples/wayland/xp-luna-columns.json" "$runtime/luna-private.json"
chmod 0600 "$runtime/luna-private.json"

# Compile the exact validated Luna recipe through the production session helper.
# The initial compositor uses the ordinary labwc look for comparison.
python3 - "$source_root" "$runtime" <<'PY'
from pathlib import Path
import sys

root, runtime = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
from macrice.de import recipes, session
from macrice.de.window_chrome import labwc_chrome

recipe = recipes.parse((root / 'examples/wayland/xp-luna-columns.json').read_bytes())
theme = labwc_chrome(recipe)
assert theme and 'Gradient Vertical' in theme
config = session._custom_labwc_config(None, str(runtime))
(runtime / 'labwc-config-path').write_text(str(config), encoding='utf-8')
(runtime / 'luna-theme.txt').write_text(theme, encoding='utf-8')
PY
config=$(cat "$runtime/labwc-config-path")
artifact="$source_root/dist/riceplate-native-preview"
mkdir -p "$artifact"

dbus-run-session -- sh -eu -c '
    config=$1; runtime=$2; native=$3; source_root=$4; artifact=$5
    labwc --config-dir "$config" \
        --startup "sh \"$source_root/scripts/wayland_luna_chrome_client.sh\" \"$runtime\"" \
        >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    wallpaper=; plate=; terminal=
    cleanup() {
        for pid in "$terminal" "$plate" "$wallpaper" "$compositor"; do
            if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || :; fi
        done
        for pid in "$terminal" "$plate" "$wallpaper" "$compositor"; do
            if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || :; fi
        done
    }
    trap cleanup EXIT
    count=0
    while [ "$count" -lt 40 ] && [ ! -S "$runtime/wayland-0" ]; do
        if ! kill -0 "$compositor" 2>/dev/null; then
            sed -n "1,65p" "$runtime/labwc.log" >&2
            echo "Luna compositor exited before creating a socket" >&2; exit 1
        fi
        count=$((count + 1)); sleep 0.25
    done
    test -S "$runtime/wayland-0" || { echo "No Wayland socket" >&2; exit 1; }
    output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
    test -n "$output" || { echo "No Wayland output" >&2; exit 1; }
    WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1
    WAYLAND_DISPLAY=wayland-0 swaybg --image "$source_root/assets/wallpapers/luna-hills.jpg" \
        --mode fill >"$runtime/wallpaper.log" 2>&1 &
    wallpaper=$!
    WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/luna-private.json" \
        >"$runtime/native.log" 2>&1 &
    plate=$!
    : > "$runtime/launch-client"
    count=0
    while [ ! -s "$runtime/client.pid" ] && [ "$count" -lt 40 ]; do
        sleep 0.25; count=$((count + 1))
    done
    test -s "$runtime/client.pid" || {
        echo "labwc did not launch its XWayland client" >&2
        sed -n "1,70p" "$runtime/labwc.log" >&2; exit 1
    }
    terminal=$(sed -n "1p" "$runtime/client.pid")
    sleep 2
    for pid in "$plate" "$wallpaper" "$terminal"; do
        kill -0 "$pid" 2>/dev/null || {
            echo "A required preview process exited" >&2
            sed -n "1,70p" "$runtime/labwc.log" >&2; exit 1
        }
    done
    WAYLAND_DISPLAY=wayland-0 grim - > "$artifact/xp-luna-window-default.png"
    cp "$runtime/luna-theme.txt" "$config/themerc-override"
    chmod 0600 "$config/themerc-override"
    # Unlike the supervised session process, this outer CI harness did not
    # inherit the labwc startup environment. Target only our compositor PID.
    LABWC_PID="$compositor" WAYLAND_DISPLAY=wayland-0 labwc --reconfigure
    sleep 1
    WAYLAND_DISPLAY=wayland-0 grim - > "$artifact/xp-luna-window-chrome.png"
' sh "$config" "$runtime" "$native" "$source_root" "$artifact"

python3 - "$artifact" <<'PY'
from pathlib import Path
from PIL import Image, ImageChops
import sys

artifact = Path(sys.argv[1])
before = Image.open(artifact / 'xp-luna-window-default.png').convert('RGB')
after = Image.open(artifact / 'xp-luna-window-chrome.png').convert('RGB')
assert before.size == after.size == (1366, 768)
# Compare only the central window area, not the changing panel clock or sky.
window = (230, 90, 1150, 540)
diff = ImageChops.difference(before.crop(window), after.crop(window))
changed = sum(1 for px in diff.getdata() if px != (0, 0, 0))
assert changed > 500, f'labwc did not visibly reload Luna chrome: {changed} pixels'
print(f'Real XWayland window titlebar changed in {changed} pixels after private labwc reconfigure')
PY

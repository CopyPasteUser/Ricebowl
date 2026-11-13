#!/bin/sh
# Actual labwc layer-shell Auto-hide: pointer, Start and popup dismissal.
# Owner-private disposable session; no production device changes.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$root/components/riceplate-wayland/target/release/riceplate-native"
clicker="$root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
for command in labwc grim dbus-run-session wlr-randr; do
    command -v "$command" >/dev/null || { echo "Missing: $command" >&2; exit 1; }
done
test -x "$native" && test -x "$clicker"
runtime=$(mktemp -d)
chmod 0700 "$runtime"
trap 'rm -rf -- "$runtime"' EXIT
mkdir -m 0700 -p "$runtime/config/ricebowl"
cp "$root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
chmod 0600 "$runtime/luna.json"
printf '%s\n' '{"version":1,"auto_hide":true,"quick_launch":true}' \
    > "$runtime/config/ricebowl/luna-taskbar.json"
chmod 0600 "$runtime/config/ricebowl/luna-taskbar.json"
export XDG_RUNTIME_DIR="$runtime" XDG_CONFIG_HOME="$runtime/config"
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=1

dbus-run-session -- sh -eu -c '
    root=$1; runtime=$2; native=$3; clicker=$4
    labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
        > "$runtime/labwc.log" 2>&1 &
    wm=$!
    plate=
    cleanup() {
        if [ -n "$plate" ]; then
            kill "$plate" 2>/dev/null || :
            wait "$plate" 2>/dev/null || :
        fi
        kill "$wm" 2>/dev/null || :
        wait "$wm" 2>/dev/null || :
    }
    trap cleanup EXIT
    i=0
    while [ "$i" -lt 40 ] && [ ! -S "$runtime/wayland-0" ]; do
        kill -0 "$wm" || { sed -n "1,70p" "$runtime/labwc.log"; exit 1; }
        sleep .25; i=$((i+1))
    done
    test -S "$runtime/wayland-0"
    output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
    test -n "$output"
    WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" \
        --custom-mode 1024x768@60Hz --scale 1
    WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/luna.json" \
        >"$runtime/plate.log" 2>&1 &
    plate=$!
    sleep 1
    kill -0 "$plate" || { cat "$runtime/plate.log"; exit 1; }
    # Move off the panel. Initial layer-shell size must be 3px, not 40px.
    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 500 400 1024 768
    sleep .3
    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/hidden.png"
    # Enter only the 3px reveal handle; compositor must reconfigure to 40px.
    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 186 767 1024 768
    sleep .65
    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/visible.png"
    # Open Start through the real pointer and leave the panel into its menu.
    WAYLAND_DISPLAY=wayland-0 "$clicker" 35 748 1024 768
    sleep .3
    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 120 585 1024 768
    sleep .4
    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/menu-open.png"
    # Outside click dismisses Start. No new panel Leave event is expected:
    # this is the precise stale-expanded-state regression being tested.
    WAYLAND_DISPLAY=wayland-0 "$clicker" 760 450 1024 768
    sleep .45
    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/menu-closed.png"
    /usr/bin/python3 - "$runtime" <<PY
from pathlib import Path
from PIL import Image, ImageChops
import sys
root = Path(sys.argv[1])
frames = {name: Image.open(root / f"{name}.png").convert("RGB") for name in
          ("hidden", "visible", "menu-open", "menu-closed")}
for name, image in frames.items():
    assert image.size == (1024, 768), (name, image.size)
def changed(first, second):
    # Ignore the cursor and overlay outside the actual taskbar rows.
    a, b = (frames[name].crop((0, 728, 1024, 765)) for name in (first, second))
    diff = ImageChops.difference(a, b)
    return sum(any(pixel) for pixel in diff.getdata())
expanded = changed("hidden", "visible")
menu_stays = changed("hidden", "menu-open")
collapsed = changed("hidden", "menu-closed")
print(f"Real Luna taskbar changed pixels: reveal={expanded} menu-open={menu_stays} dismissed={collapsed}")
assert expanded > 3000, "Taskbar did not expand after real pointer Enter"
assert menu_stays > 3000, "Start popup incorrectly collapsed the taskbar"
assert collapsed < 1000, "Closing Start left the auto-hidden taskbar expanded"
PY
    output_dir="$root/dist/riceplate-native-preview"
    if [ -d "$output_dir" ]; then
        for name in hidden visible menu-open menu-closed; do
            cp "$runtime/$name.png" "$output_dir/luna-autohide-$name.png"
        done
        (cd "$output_dir" &&
          sha256sum luna-autohide-*.png > luna-autohide-SHA256SUMS)
    fi
    kill -0 "$plate"
    echo "PASS: actual labwc Auto-hide reveal, popup protection and dismissal"
' sh "$root" "$runtime" "$native" "$clicker"

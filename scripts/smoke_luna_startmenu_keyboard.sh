#!/bin/sh
# Focused real-labwc acceptance: XP Luna All Programs -> XDG folder -> Escape.
# All XDG inputs and captures stay in a disposable private test environment.
set -eu

if [ "${1:-}" != "--inner" ]; then
    root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
    native="$root/components/riceplate-wayland/target/release/riceplate-native"
    clicker="$root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
    [ -x "$native" ] && [ -x "$clicker" ] || {
        echo "Build the native release binary and pointer example first" >&2
        exit 1
    }
    runtime=$(mktemp -d)
    chmod 0700 "$runtime"
    trap 'rm -rf "$runtime"' EXIT
    export XDG_RUNTIME_DIR="$runtime"
    export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
    export RICEBOWL_DE_NESTED=1
    dbus-run-session -- sh "$0" --inner "$runtime" "$root"
    exit $?
fi

runtime=$2
root=$3
native="$root/components/riceplate-wayland/target/release/riceplate-native"
clicker="$root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
captures="$root/dist/luna-startmenu-keyboard"
mkdir -p "$captures" "$runtime/xdg/applications" "$runtime/xdg-config" "$runtime/xdg-system"
chmod 0700 "$runtime/xdg" "$runtime/xdg-config"
# Native recipe admission intentionally rejects world-readable source recipes.
# Copy the tracked fixture into this isolated, owner-private session runtime.
cp "$root/examples/wayland/xp-luna-columns.json" "$runtime/luna-recipe.json"
chmod 0600 "$runtime/luna-recipe.json"
# No installed applications, host file history, real user config or network.
cat > "$runtime/xdg/applications/ricebowl-ci-office.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=RiceBowl CI Office
Exec=/usr/bin/true
Categories=Office;
DESKTOP

compositor=
plate=
cleanup() {
    if [ -n "$plate" ]; then kill "$plate" 2>/dev/null || :; wait "$plate" 2>/dev/null || :; fi
    if [ -n "$compositor" ]; then kill "$compositor" 2>/dev/null || :; wait "$compositor" 2>/dev/null || :; fi
}
trap cleanup EXIT
labwc --config-dir "$root/macrice/de/resources/labwc" --startup true >"$runtime/labwc.log" 2>&1 &
compositor=$!
count=0
while [ ! -S "$runtime/wayland-0" ] && [ "$count" -lt 40 ]; do
    kill -0 "$compositor" 2>/dev/null || {
        echo "labwc quit before opening Wayland socket" >&2
        sed -n '1,60p' "$runtime/labwc.log" >&2
        exit 1
    }
    count=$((count + 1))
    sleep 0.25
done
[ -S "$runtime/wayland-0" ] || { echo "No Wayland socket" >&2; exit 1; }
output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n '1s/[[:space:]].*//p')
[ -n "$output" ] || { echo "No headless output" >&2; exit 1; }

for geometry in 1024x768 1366x768 1920x1080; do
    width=${geometry%x*}
    height=${geometry#*x}
    WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" \
        --custom-mode "${width}x${height}@60Hz" --scale 1
    sleep 0.4
    XDG_CONFIG_HOME="$runtime/xdg-config" XDG_DATA_HOME="$runtime/xdg" \
        XDG_DATA_DIRS="$runtime/xdg-system" RICEBOWL_DE_TRACE_MENU=1 \
        WAYLAND_DISPLAY=wayland-0 "$native" \
        --recipe "$runtime/luna-recipe.json" \
        >"$runtime/plate-$geometry.log" 2>&1 &
    plate=$!
    sleep 0.9
    if ! kill -0 "$plate" 2>/dev/null; then
        echo "Native RicePlate exited before Start Menu acceptance ($geometry)" >&2
        tail -n 80 "$runtime/plate-$geometry.log" >&2 || :
        exit 1
    fi
    button_y=$((height - 20))
    WAYLAND_DISPLAY=wayland-0 "$clicker" 35 "$button_y" "$width" "$height"
    sleep 0.35
    WAYLAND_DISPLAY=wayland-0 grim - > "$captures/luna-start-$geometry.png"

    # The first geometry is the functional acceptance. The others prove
    # actual compositor output and prevent screenshot size regressions.
    if [ "$geometry" = 1024x768 ]; then
        WAYLAND_DISPLAY=wayland-0 "$clicker" 60 680 "$width" "$height"
        sleep 0.3
        WAYLAND_DISPLAY=wayland-0 grim - > "$captures/luna-programs-$geometry.png"
        WAYLAND_DISPLAY=wayland-0 "$clicker" 60 548 "$width" "$height"
        sleep 0.3
        WAYLAND_DISPLAY=wayland-0 grim - > "$captures/luna-category-$geometry.png"
        WAYLAND_DISPLAY=wayland-0 wtype -k Escape
        sleep 0.35
        WAYLAND_DISPLAY=wayland-0 grim - > "$captures/luna-category-back-$geometry.png"
    fi
    cp "$runtime/plate-$geometry.log" "$captures/plate-$geometry.log"
    if [ "$geometry" = 1024x768 ]; then
        if python3 - "$captures" <<'PY'
from pathlib import Path
from PIL import Image, ImageChops
import sys
root = Path(sys.argv[1])
images = [Image.open(root / f"luna-{name}-1024x768.png").convert("RGB")
          for name in ("programs", "category", "category-back")]
region = (0, 424, 320, 700)
def differs(left, right):
    return ImageChops.difference(left.crop(region), right.crop(region)).getbbox() is not None
assert differs(images[0], images[1]), "Real Office category did not open"
assert differs(images[1], images[2]), "Real Escape did not return to XDG folder list"
print("Verified real labwc XP Luna folder selection and Escape framebuffer changes")
PY
        then
            :
        else
            echo "Real menu keyboard focus diagnostics:" >&2
            grep -E "RicePlate: (luna|menu trace)" "$captures/plate-$geometry.log" \
                | tail -n 80 >&2 || :
            exit 1
        fi
    fi
    kill "$plate"
    wait "$plate" 2>/dev/null || :
    plate=
done

python3 - "$captures" <<'PY'
from pathlib import Path
from PIL import Image
import sys
root = Path(sys.argv[1])
for width, height in ((1024, 768), (1366, 768), (1920, 1080)):
    file = root / f"luna-start-{width}x{height}.png"
    with Image.open(file) as image:
        image.load()
        assert image.size == (width, height), (file, image.size)
print("Verified genuine full-size 1024/1366/1920 compositor captures")
PY

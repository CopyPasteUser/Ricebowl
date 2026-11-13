#!/bin/sh
# Real labwc + virtual keyboard gate: XP Super shortcuts must reach native IPC.
# No host Wayland/XFCE config changes and no fake screenshots.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$root/components/riceplate-wayland/target/release/riceplate-native"
test -x "$native" || { echo 'Build native RicePlate first' >&2; exit 1; }
runtime=$(mktemp -d -t ricebowl-luna-hotkeys-XXXXXXXX)
chmod 0700 "$runtime"
trap 'rm -r -- "$runtime"' EXIT
mkdir -m 0700 "$runtime/config" "$runtime/mock-bin"
export XDG_RUNTIME_DIR="$runtime" XDG_CONFIG_HOME="$runtime/config"
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export PATH="$runtime/mock-bin:$root/components/riceplate-wayland/target/release:$PATH"
export RICEBOWL_DE_NESTED=0 RICEBOWL_DE_TRACE_SHORTCUTS=1

# Explorer must be a real fixed native action, but do not launch a user's
# file-manager during CI: intercept that executable in the private PATH.
cat > "$runtime/mock-bin/ricefield" <<'SH'
#!/bin/sh
printf "%s\n" "$@" > "$XDG_RUNTIME_DIR/explorer-args"
SH
chmod 0700 "$runtime/mock-bin/ricefield"

cp "$root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
chmod 0600 "$runtime/luna.json"
python3 - "$root" "$runtime" <<'PY'
from pathlib import Path
import sys
root, runtime = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
from macrice.de import luna_hotkeys, recipes, session
rice = recipes.parse((root / "examples/wayland/xp-luna-columns.json").read_bytes())
config = session._custom_labwc_config(rice, str(runtime), native_luna_hotkeys=True)
commands = luna_hotkeys.commands((config / "rc.xml").read_text())
assert commands["W-d"] == "riceplate-native --desktop-command show-desktop"
assert commands["W-e"] == "riceplate-native --desktop-command explorer"
assert commands["W-r"] == "riceplate-native --desktop-command run"
(runtime / "config-path").write_text(str(config))
PY
config=$(cat "$runtime/config-path")
artifact="$root/dist/riceplate-native-preview"
mkdir -p "$artifact"

dbus-run-session -- sh -eu -c '
    config=$1; runtime=$2; native=$3; artifact=$4; root=$5
    labwc --config-dir "$config" >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    wallpaper=; plate=
    cleanup() {
        for pid in "$plate" "$wallpaper" "$compositor"; do
            if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || :; fi
        done
        for pid in "$plate" "$wallpaper" "$compositor"; do
            if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || :; fi
        done
    }
    trap cleanup EXIT
    count=0
    while [ "$count" -lt 40 ] && [ ! -S "$runtime/wayland-0" ]; do
        if ! kill -0 "$compositor" 2>/dev/null; then
            sed -n "1,90p" "$runtime/labwc.log" >&2
            exit 1
        fi
        sleep 0.25; count=$((count + 1))
    done
    test -S "$runtime/wayland-0" || { echo "No labwc socket" >&2; exit 1; }
    output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
    test -n "$output" || { echo "No active wl_output" >&2; exit 1; }
    WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1
    WAYLAND_DISPLAY=wayland-0 swaybg --image "$root/assets/wallpapers/luna-hills.jpg" \
        --mode fill >"$runtime/wallpaper.log" 2>&1 &
    wallpaper=$!
    WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/luna.json" \
        >"$runtime/native.log" 2>&1 &
    plate=$!
    count=0
    while [ "$count" -lt 50 ] && [ ! -S "$runtime/riceplate-luna-desktop.sock" ]; do
        if ! kill -0 "$plate" 2>/dev/null; then
            sed -n "1,100p" "$runtime/native.log" >&2
            echo "Native RicePlate exited before binding IPC" >&2; exit 1
        fi
        count=$((count + 1)); sleep 0.2
    done
    test -S "$runtime/riceplate-luna-desktop.sock" || {
        echo "Luna IPC socket never started" >&2; exit 1;
    }
    sleep 1
    WAYLAND_DISPLAY=wayland-0 grim - > "$artifact/xp-luna-hotkeys-before.png"
    WAYLAND_DISPLAY=wayland-0 wtype -M logo -k d -m logo
    sleep 0.3
    grep -q "Luna private IPC ShowDesktop" "$runtime/native.log" || {
        echo "Super+D did not reach the RicePlate Show Desktop action" >&2
        sed -n "1,100p" "$runtime/native.log" >&2; exit 1;
    }
    WAYLAND_DISPLAY=wayland-0 wtype -M logo -k e -m logo
    count=0
    while [ ! -s "$runtime/explorer-args" ] && [ "$count" -lt 20 ]; do
        count=$((count + 1)); sleep 0.1
    done
    test -s "$runtime/explorer-args" || {
        echo "Super+E did not reach the existing My Computer action" >&2; exit 1;
    }
    grep -q "Luna private IPC Explorer" "$runtime/native.log"
    WAYLAND_DISPLAY=wayland-0 wtype -M logo -k r -m logo
    sleep 0.7
    grep -q "Luna private IPC Run" "$runtime/native.log" || {
        echo "Super+R did not reach RicePlate Run" >&2; exit 1;
    }
    WAYLAND_DISPLAY=wayland-0 grim - > "$artifact/xp-luna-hotkeys-run.png"
    kill -0 "$plate"
' sh "$config" "$runtime" "$native" "$artifact" "$root"

python3 - "$runtime" "$artifact" <<'PY'
import sys
from pathlib import Path
from PIL import Image, ImageChops
runtime, artifact = map(Path, sys.argv[1:])
assert (runtime / "explorer-args").read_text().splitlines() == [
    "--theme", "xp-luna", "--separate-window", "/"
], "Super+E must navigate only to the fixed Computer location"
before = Image.open(artifact / "xp-luna-hotkeys-before.png").convert("RGB")
after = Image.open(artifact / "xp-luna-hotkeys-run.png").convert("RGB")
assert before.size == after.size == (1366, 768)
diff = ImageChops.difference(before.crop((410, 160, 980, 560)),
                             after.crop((410, 160, 980, 560)))
changed = sum(pixel != (0, 0, 0) for pixel in diff.getdata())
assert changed > 2000, f"Super+R did not display the real native Run dialog ({changed} pixels)"
print(f"Native labwc Super+D/E/R dispatched; Run changed {changed} real compositor pixels")
PY

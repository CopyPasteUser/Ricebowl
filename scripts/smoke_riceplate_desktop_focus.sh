#!/bin/sh
# Self-contained, opt-in diagnostic. Never modifies XFCE, the login manager,
# a home Desktop directory, or any existing Wayland session.
# Usage: sh scripts/smoke_riceplate_desktop_focus.sh
# Requires: cargo, labwc, dbus-run-session, wlr-randr, wtype, grim, python3/Pillow
set -eu
umask 077

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
manifest="$root/components/riceplate-wayland/Cargo.toml"
target="$root/components/riceplate-wayland/target/release"
output="$root/dist/riceplate-focus-proof"
for command in cargo labwc dbus-run-session wlr-randr wtype grim python3; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "FOCUS_PROBE_BLOCKED missing=$command" >&2
        exit 2
    }
done
python3 -c 'from PIL import Image, ImageChops' || {
    echo "FOCUS_PROBE_BLOCKED missing=python3-Pillow" >&2
    exit 2
}
# This builds only our isolated helper and the already existing virtual pointer
# example. Neither binary is installed or launched outside the private session.
cargo build --locked --release --manifest-path "$manifest" \
    --bin riceplate_focus_probe --example wayland_pointer_click
test -x "$target/riceplate_focus_probe"
test -x "$target/examples/wayland_pointer_click"

runtime=$(mktemp -d "${TMPDIR:-/tmp}/ricebowl-focus-XXXXXXXX")
chmod 0700 "$runtime"
cleanup() {
    rm -rf -- "$runtime"
}
trap cleanup EXIT HUP INT TERM
mkdir -m 0700 "$runtime/config"
export XDG_RUNTIME_DIR="$runtime"
export XDG_CONFIG_HOME="$runtime/config"
export XDG_SESSION_TYPE=wayland
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=1
export WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=1
unset WAYLAND_DISPLAY DISPLAY || :
mkdir -p "$output"
chmod 0700 "$output"
labwc --version > "$output/labwc-version.txt" 2>&1 || :
printf '%s\n' 'All frames are real grim captures of an isolated headless labwc.' \
    'Only protocol event names and event counts are recorded; key values are not logged.' \
    'This probe is not the RicePlate desktop integration acceptance.' \
    > "$output/README.txt"

dbus-run-session -- sh -eu -c '
    root=$1
    runtime=$2
    target=$3
    output=$4
    labwc --config-dir "$root/macrice/de/resources/labwc" \
        --startup true > "$output/labwc.log" 2>&1 &
    compositor=$!
    child=
    cleanup_inner() {
        if [ -n "$child" ]; then
            kill "$child" 2>/dev/null || :
            wait "$child" 2>/dev/null || :
        fi
        kill "$compositor" 2>/dev/null || :
        wait "$compositor" 2>/dev/null || :
    }
    trap cleanup_inner EXIT HUP INT TERM
    i=0
    while [ "$i" -lt 60 ] && [ ! -S "$runtime/wayland-0" ]; do
        kill -0 "$compositor" || {
            echo "FOCUS_PROBE_BLOCKED compositor-crashed" >&2
            exit 2
        }
        i=$((i + 1))
        sleep 0.1
    done
    test -S "$runtime/wayland-0" || {
        echo "FOCUS_PROBE_BLOCKED no-private-wayland-socket" >&2
        exit 2
    }
    export WAYLAND_DISPLAY=wayland-0
    name=$(wlr-randr | sed -n "1{s/ .*//;p;}")
    test -n "$name" || {
        echo "FOCUS_PROBE_BLOCKED no-headless-output" >&2
        exit 2
    }
    wlr-randr --output "$name" --custom-mode 1366x768@60Hz
    for layer in bottom top; do
        "$target/riceplate_focus_probe" "$layer" >"$output/$layer.events.log" 2>&1 &
        child=$!
        i=0
        until grep -q "event=mapped" "$output/$layer.events.log"; do
            kill -0 "$child" || {
                echo "FOCUS_PROBE_FAIL $layer-probe-exited" >&2
                exit 1
            }
            i=$((i + 1))
            if [ "$i" -gt 50 ]; then
                echo "FOCUS_PROBE_FAIL $layer-not-mapped" >&2
                exit 1
            fi
            sleep 0.1
        done
        sleep 0.15
        grim - >"$output/$layer-before.png"
        # Probe bounds: x=220..476 y=220..348 on 1366x768.
        "$target/examples/wayland_pointer_click" 280 270 1366 768
        sleep 0.2
        # F13 is only a harmless compositor virtual-keyboard warmup.
        # No actual key text is captured or logged by the probe.
        wtype -k F13
        wtype -d 30 a
        sleep 0.25
        grim - >"$output/$layer-after.png"
        grep -q "event=pointer_press" "$output/$layer.events.log" || {
            echo "FOCUS_PROBE_FAIL $layer-pointer-event-missing" >&2
            exit 1
        }
        if [ "$layer" = top ]; then
            grep -q "event=keyboard_enter" "$output/$layer.events.log" || {
                echo "FOCUS_PROBE_FAIL top-no-compositor-keyboard-enter" >&2
                exit 1
            }
            grep -q "event=keyboard_press" "$output/$layer.events.log" || {
                echo "FOCUS_PROBE_FAIL top-no-compositor-key-event" >&2
                exit 1
            }
        fi
        kill "$child" 2>/dev/null || :
        wait "$child" 2>/dev/null || :
        child=
    done
' sh "$root" "$runtime" "$target" "$output"

# A screenshot with no pixels changed is not accepted as keyboard evidence.
python3 - "$output" <<'PY'
from PIL import Image, ImageChops
from pathlib import Path
import sys
out = Path(sys.argv[1])
for layer in ("bottom", "top"):
    with Image.open(out / f"{layer}-before.png") as a, Image.open(out / f"{layer}-after.png") as b:
        a.verify()
        b.verify()
    with Image.open(out / f"{layer}-before.png") as a, Image.open(out / f"{layer}-after.png") as b:
        a.load()
        b.load()
        assert a.size == b.size == (1366, 768), f"{layer}: wrong compositor output size"
        patch = (220, 220, 476, 348)
        changed = ImageChops.difference(
            a.convert("RGB").crop(patch), b.convert("RGB").crop(patch)
        ).getbbox()
        if layer == "top":
            assert changed is not None, "top probe did not visibly change after click/focus"
        print(f"FOCUS_PROBE_IMAGE layer={layer} changed={changed is not None}")
bottom_events = (out / "bottom.events.log").read_text()
top_events = (out / "top.events.log").read_text()
assert "event=keyboard_enter" in top_events and "event=keyboard_press" in top_events
print(f"FOCUS_PROBE_RESULT isolated_labwc_top=PASS bottom_focus_enter={'event=keyboard_enter' in bottom_events}")
print("FOCUS_PROBE_LIMIT no real RicePlate focus, normal-client return, XWayland, IME or hardware acceptance")
PY

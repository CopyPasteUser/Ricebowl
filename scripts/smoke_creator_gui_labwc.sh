#!/bin/sh
# SG4: real Wayland keyboard -> GTK Creator -> private Composer draft.
# The test hook focuses an accessible button but never clicks it. Only external
# compositor-delivered Return can create a draft. No live rice is switched.
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
output=${1:?Provide an absolute empty output directory}
case "$output" in /*) : ;; *) echo "Output must be absolute" >&2; exit 2 ;; esac
[ "$(id -u)" -ne 0 ] || { echo "Do not run labwc GTK QA as root" >&2; exit 2; }
[ -d "$output" ] && [ ! -L "$output" ] && [ -z "$(ls -A "$output")" ] || {
    echo "Provide a new empty output directory" >&2; exit 2;
}
runtime=$(mktemp -d -t ricebowl-sg4-wayland-XXXXXXXX)
chmod 0700 "$runtime"
trap 'rm -rf -- "$runtime"' EXIT
mkdir -m 0700 "$runtime/run" "$runtime/config" "$runtime/state" "$runtime/home"
export XDG_RUNTIME_DIR="$runtime/run"
export XDG_CONFIG_HOME="$runtime/config"
export XDG_STATE_HOME="$runtime/state"
export HOME="$runtime/home"
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export GDK_BACKEND=wayland XDG_SESSION_TYPE=wayland RICEBOWL_DE_NESTED=1

dbus-run-session -- sh -eu -c '
    root=$1; runtime=$2; output=$3
    export WAYLAND_DISPLAY=wayland-0
    labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
        >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    keyboard_keeper= creator=
    cleanup() {
        for pid in "$creator" "$keyboard_keeper" "$compositor"; do
            if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || :; fi
        done
        for pid in "$creator" "$keyboard_keeper" "$compositor"; do
            if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || :; fi
        done
    }
    trap cleanup EXIT

    i=0
    while [ "$i" -lt 60 ] && [ ! -S "$XDG_RUNTIME_DIR/wayland-0" ]; do
        kill -0 "$compositor" 2>/dev/null || {
            sed -n "1,90p" "$runtime/labwc.log" >&2; exit 1;
        }
        i=$((i + 1)); sleep 0.2
    done
    test -S "$XDG_RUNTIME_DIR/wayland-0" || { echo "labwc socket missing" >&2; exit 1; }

    # Match the persistent keyboard seat in a normal desktop. A one-shot
    # wtype invocation can otherwise revoke keyboard capability on exit.
    wtype -k F13 -s 1800000 -k F13 >"$runtime/keyboard.log" 2>&1 &
    keyboard_keeper=$!
    sleep 0.3
    kill -0 "$keyboard_keeper" || { cat "$runtime/keyboard.log" >&2; exit 1; }
    output_name=$(wlr-randr | sed -n "1s/[[:space:]].*//p")
    test -n "$output_name"
    wlr-randr --output "$output_name" --custom-mode 1600x900@60Hz --scale 1

    for template in heritage-composer orbit-composer; do
        rm -f "$XDG_STATE_HOME/sg4-creator-wayland-ready" \
              "$XDG_STATE_HOME/sg4-creator-wayland-done"
        export RICEBOWL_CREATOR_WAYLAND_PROBE="$template"
        /usr/bin/python3 "$root/launcher.py" creator >"$runtime/$template.log" 2>&1 &
        creator=$!
        i=0
        while [ "$i" -lt 65 ] && [ ! -f "$XDG_STATE_HOME/sg4-creator-wayland-ready" ]; do
            kill -0 "$creator" 2>/dev/null || break
            i=$((i + 1)); sleep 0.2
        done
        if ! grep -Fxq "$template" "$XDG_STATE_HOME/sg4-creator-wayland-ready" 2>/dev/null; then
            echo "No focused GTK Composer button for $template" >&2
            sed -n "1,100p" "$runtime/$template.log" >&2
            exit 1
        fi
        # Capture pixels from the *real* compositor, not the schematic canvas.
        grim - > "$output/$template-gtk-labwc.png"
        # The test hook does not synthesize this click/key event. It must
        # traverse wl_seat via labwc to the focused actual GTK3 button.
        wtype -k Return
        i=0
        while [ "$i" -lt 65 ] && [ ! -f "$XDG_STATE_HOME/sg4-creator-wayland-done" ]; do
            kill -0 "$creator" 2>/dev/null || break
            i=$((i + 1)); sleep 0.2
        done
        if ! test -f "$XDG_STATE_HOME/sg4-creator-wayland-done"; then
            echo "Wayland Return did not activate $template" >&2
            sed -n "1,100p" "$runtime/$template.log" >&2
            exit 1
        fi
        cp "$XDG_STATE_HOME/sg4-creator-wayland-done" "$output/$template-keyboard.json"
        wait "$creator"
        creator=
    done
' sh "$root" "$runtime" "$output"

/usr/bin/python3 - "$output" <<'PY'
from pathlib import Path
from PIL import Image
import hashlib
import json
import sys

root = Path(sys.argv[1])
for template, expected in (("heritage-composer", "bottom"), ("orbit-composer", "top")):
    receipt = json.loads((root / f"{template}-keyboard.json").read_text())
    assert (receipt["template"], receipt["position"], receipt["gtk_focus"],
            receipt["atk_role"], receipt["native_input"]) == (
            template, expected, True, "push button", "external Wayland keyboard")
    assert len(receipt["sha256"]) == 64
    screenshot = root / f"{template}-gtk-labwc.png"
    with Image.open(screenshot) as pixels:
        pixels.load()
        assert pixels.format == "PNG" and pixels.size == (1600, 900)
        assert len(set(pixels.resize((32, 18)).convert("RGB").getdata())) > 4, (
            "GTK Creator compositor frame is blank or not rendered")
    print(f"SG4: real labwc GTK focus/keyboard {template}: {receipt['sha256'][:12]} "
          f"capture SHA {hashlib.sha256(screenshot.read_bytes()).hexdigest()[:12]}")
print("SG4: two real compositor keyboard -> GUI template activations passed")
PY

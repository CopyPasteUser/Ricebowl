#!/bin/sh
# SG5: real labwc keyboard delivery + external AT-SPI Run editor semantics.
# The Python client can only query the public accessibility bus; no private
# Rust entrypoints or synthetic AccessKit model are accepted as evidence.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$root/components/riceplate-wayland/target/release/riceplate-native"
test -x "$native" || { echo 'Build native RicePlate first' >&2; exit 1; }
runtime=$(mktemp -d -t ricebowl-sg5-atspi-XXXXXXXX)
chmod 0700 "$runtime"
trap 'rm -rf -- "$runtime"' EXIT
mkdir -m 0700 "$runtime/config"
export XDG_RUNTIME_DIR="$runtime" XDG_CONFIG_HOME="$runtime/config"
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=0 RICEBOWL_DE_SCREEN_READER=1
export PATH="$root/components/riceplate-wayland/target/release:$PATH"

python3 - "$root" "$runtime" <<'PY'
from pathlib import Path
import sys
root, runtime = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
from macrice.de import luna_hotkeys, recipes, session
rice = recipes.parse((root / "examples/wayland/xp-luna-columns.json").read_bytes())
config = session._custom_labwc_config(rice, str(runtime), native_luna_hotkeys=True)
assert luna_hotkeys.commands((config / "rc.xml").read_text())["W-r"] == \
    "riceplate-native --desktop-command run"
(runtime / "config-path").write_text(str(config))
PY

dbus-run-session -- sh -eu -c '
    root=$1; runtime=$2; native=$3
    export WAYLAND_DISPLAY=wayland-0
    labwc --config-dir "$(cat "$runtime/config-path")" >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    plate=
    cleanup() {
        for pid in "$plate" "$compositor"; do
            if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || :; fi
        done
        for pid in "$plate" "$compositor"; do
            if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || :; fi
        done
    }
    trap cleanup EXIT

    count=0
    while [ "$count" -lt 50 ] && [ ! -S "$runtime/wayland-0" ]; do
        kill -0 "$compositor" 2>/dev/null || {
            sed -n "1,100p" "$runtime/labwc.log" >&2; exit 1;
        }
        count=$((count + 1)); sleep 0.2
    done
    test -S "$runtime/wayland-0" || { echo "labwc socket missing" >&2; exit 1; }
    output=$(wlr-randr | sed -n "1s/[[:space:]].*//p")
    test -n "$output"
    wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1

    "$native" --recipe "$root/examples/wayland/xp-luna-columns.json" \
        >"$runtime/native.log" 2>&1 &
    plate=$!
    count=0
    while [ "$count" -lt 50 ] && [ ! -S "$runtime/riceplate-luna-desktop.sock" ]; do
        kill -0 "$plate" 2>/dev/null || {
            sed -n "1,100p" "$runtime/native.log" >&2; exit 1;
        }
        count=$((count + 1)); sleep 0.2
    done
    test -S "$runtime/riceplate-luna-desktop.sock" || exit 1
    probe() { timeout -k 2s 14s /usr/bin/python3 "$root/scripts/smoke_riceplate_atspi_client.py" "$@"; }

    wtype -M logo -k r -m logo
    probe --text "" --caret 0
    wtype "AB"
    probe --text "AB" --caret 2
    wtype -k Left
    probe --text "AB" --caret 1
    wtype -k BackSpace
    probe --text "B" --caret 0
    wtype -M ctrl -k a -m ctrl
    probe --text "B" --caret 1 --selection 0 1
    wtype "Z"
    probe --text "Z" --caret 1
    wtype -k BackSpace
    probe --text "" --caret 0
    wtype -k Escape
    probe --absent
    wtype -M logo -k r -m logo
    probe --text "" --caret 0
    kill -0 "$plate"
    echo "SG5: native labwc keyboard -> AccessKit AT-SPI lifecycle PASS"
' sh "$root" "$runtime" "$native"

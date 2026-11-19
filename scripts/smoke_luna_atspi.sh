#!/bin/sh
# SG5: real labwc keyboard delivery + external AT-SPI Run editor semantics.
# The Python client can only query the public accessibility bus; no private
# Rust entrypoints or synthetic AccessKit model are accepted as evidence.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$root/components/riceplate-wayland/target/release/riceplate-native"
ime="$root/components/riceplate-wayland/target/release/examples/wayland_ime_v2_client"
test -x "$ime" || { echo "Build the external v2 IME fixture first" >&2; exit 1; }
test -x "$native" || { echo 'Build native RicePlate first' >&2; exit 1; }
runtime=$(mktemp -d -t ricebowl-sg5-atspi-XXXXXXXX)
chmod 0700 "$runtime"
trap 'rm -rf -- "$runtime"' EXIT
mkdir -m 0700 "$runtime/config"
export XDG_RUNTIME_DIR="$runtime" XDG_CONFIG_HOME="$runtime/config"
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=0 RICEBOWL_DE_SCREEN_READER=1
export PATH="$root/components/riceplate-wayland/target/release:$PATH"

# Native recipe ownership contract: never launch directly from a world-readable
# checkout. Keep all runtime inputs in a private disposable directory.
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
assert luna_hotkeys.commands((config / "rc.xml").read_text())["W-r"] == \
    "riceplate-native --desktop-command run"
(runtime / "config-path").write_text(str(config))
PY

dbus-run-session -- sh -eu -c '
    root=$1; runtime=$2; native=$3; ime=$4
    export WAYLAND_DISPLAY=wayland-0
    labwc --config-dir "$(cat "$runtime/config-path")" >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    plate=; imepid=
    cleanup() {
        for pid in "$imepid" "$plate" "$compositor"; do
            if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || :; fi
        done
        for pid in "$imepid" "$plate" "$compositor"; do
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

    # Real desktops have an AT-SPI registry before applications register;
    # make this disposable session obey the same ordering.
    /usr/bin/python3 -c "import pyatspi; pyatspi.Registry.getDesktop(0).childCount" >/dev/null

    "$native" --recipe "$runtime/luna.json" \
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
    probe() {
        if timeout -k 2s 14s /usr/bin/python3 "$root/scripts/smoke_riceplate_atspi_client.py" "$@"; then
            return 0
        fi
        echo "RicePlate diagnostics after missing AT-SPI text node:" >&2
        sed -n "1,100p" "$runtime/native.log" >&2
        sed -n "1,60p" "$runtime/labwc.log" >&2
        return 1
    }

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
    # Register a separate input-method-v2 producer *before* re-focusing Run.
    # Its preedit, commit and byte deletion must traverse labwc to the
    # unmodified text-input-v3 application and return as surrounding text.
    timeout -k 2s 16s "$ime" >"$runtime/ime.log" 2>&1 &
    imepid=$!
    sleep 0.3
    wtype -M logo -k r -m logo
    if ! wait "$imepid"; then
        echo "External IME v2 -> text-input-v3 transaction failed:" >&2
        sed -n "1,100p" "$runtime/ime.log" >&2
        sed -n "1,90p" "$runtime/native.log" >&2
        exit 1
    fi
    imepid=
    probe --text "日本界" --caret 3
    wtype -k Escape
    probe --absent
    kill -0 "$plate"
    echo "SG5: real labwc keyboard, external input-method-v2 and AT-SPI lifecycle PASS"
' sh "$root" "$runtime" "$native" "$ime"

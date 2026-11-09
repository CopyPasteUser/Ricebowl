#!/bin/sh
# A real Wayland client must populate, paint and leave the native taskbar.
# Runs only in a disposable headless labwc compositor, never in the login session.
set -eu

source_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$source_root/components/riceplate-wayland/target/release/riceplate-native"
test -x "$native"
for executable in labwc grim foot dbus-run-session; do
    command -v "$executable" >/dev/null || { echo "Missing test dependency: $executable" >&2; exit 1; }
done
runtime=$(mktemp -d)
chmod 0700 "$runtime"
trap 'rm -r -- "$runtime"' EXIT
export XDG_RUNTIME_DIR="$runtime"
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=1
export WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=1

dbus-run-session -- sh -eu -c '
    source_root=$1
    runtime=$2
    native=$3
    labwc --config-dir "$source_root/macrice/de/resources/labwc" \
        --startup true >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    plate=
    window=
    cleanup() {
        if [ -n "$window" ]; then
            kill "$window" 2>/dev/null || :
            wait "$window" 2>/dev/null || :
        fi
        if [ -n "$plate" ]; then
            kill "$plate" 2>/dev/null || :
            wait "$plate" 2>/dev/null || :
        fi
        kill "$compositor" 2>/dev/null || :
        wait "$compositor" 2>/dev/null || :
    }
    trap cleanup EXIT

    count=0
    while [ "$count" -lt 40 ] && [ ! -S "$runtime/wayland-0" ]; do
        if ! kill -0 "$compositor" 2>/dev/null; then
            echo "Window test compositor exited early" >&2
            sed -n "1,50p" "$runtime/labwc.log" >&2
            exit 1
        fi
        sleep 0.25
        count=$((count + 1))
    done
    test -S "$runtime/wayland-0" || { echo "No Wayland socket" >&2; exit 1; }

    WAYLAND_DISPLAY=wayland-0 RICEBOWL_DE_TRACE_WINDOWS=1 \
        "$native" --recipe classic >"$runtime/panel.log" 2>&1 &
    plate=$!
    sleep 1
    kill -0 "$plate" || { sed -n "1,50p" "$runtime/panel.log" >&2; exit 1; }
    WAYLAND_DISPLAY=wayland-0 grim - >"$runtime/before.png"

    WAYLAND_DISPLAY=wayland-0 foot --app-id=ricebowl-wayland-smoke \
        --title=RiceBowl-Window-Smoke /bin/sh -c "sleep 30" \
        >"$runtime/window.log" 2>&1 &
    window=$!
    count=0
    while [ "$count" -lt 40 ]; do
        if grep -Fq "event=ready app_id=\"ricebowl-wayland-smoke\"" "$runtime/panel.log"; then
            break
        fi
        if ! kill -0 "$window" 2>/dev/null; then
            echo "Real Wayland application exited without a task" >&2
            sed -n "1,60p" "$runtime/window.log" >&2
            sed -n "1,60p" "$runtime/panel.log" >&2
            exit 1
        fi
        sleep 0.25
        count=$((count + 1))
    done
    if [ "$count" -ge 40 ]; then
        echo "RicePlate did not receive the real foreign-toplevel task" >&2
        sed -n "1,60p" "$runtime/panel.log" >&2
        exit 1
    fi
    sleep 0.5
    WAYLAND_DISPLAY=wayland-0 grim - >"$runtime/opened.png"
    kill "$window"
    wait "$window" 2>/dev/null || :
    window=
    count=0
    while [ "$count" -lt 40 ] &&
        ! grep -Fq "event=closed app_id=\"ricebowl-wayland-smoke\"" "$runtime/panel.log"; do
        sleep 0.25
        count=$((count + 1))
    done
    if [ "$count" -ge 40 ]; then
        echo "RicePlate did not remove the closed real Wayland task" >&2
        sed -n "1,60p" "$runtime/panel.log" >&2
        exit 1
    fi
    sleep 0.5
    WAYLAND_DISPLAY=wayland-0 grim - >"$runtime/closed.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_window_outputs.py" \
        "$runtime/before.png" "$runtime/opened.png" "$runtime/closed.png"
    kill -0 "$plate"
    echo "Native RicePlate observed and painted a real Wayland window lifecycle"
' sh "$source_root" "$runtime" "$native"

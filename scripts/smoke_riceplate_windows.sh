#!/bin/sh
# A real Wayland client must populate, paint and leave the native taskbar.
# Runs only in a disposable headless labwc compositor, never in the login session.
set -eu

mode=${1:-native}
case "$mode" in
    native|--xwayland|--luna) ;;
    *) echo "Usage: $0 [--xwayland|--luna]" >&2; exit 2 ;;
esac

source_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$source_root/components/riceplate-wayland/target/release/riceplate-native"
clicker="$source_root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
test -x "$native"
test -x "$clicker"
for executable in labwc grim foot wlr-randr dbus-run-session; do
    command -v "$executable" >/dev/null || { echo "Missing test dependency: $executable" >&2; exit 1; }
done
if [ "$mode" = "--luna" ]; then
    command -v wtype >/dev/null || { echo "Missing test dependency: wtype" >&2; exit 1; }
fi
if [ "$mode" = "--xwayland" ]; then
    for executable in Xwayland xterm; do
        command -v "$executable" >/dev/null || { echo "Missing XWayland test dependency: $executable" >&2; exit 1; }
    done
fi
runtime=$(mktemp -d)
chmod 0700 "$runtime"
if [ "$mode" = "--luna" ]; then
    # RicePlate requires an owner-private file for absolute recipe loading.
    cp "$source_root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
    chmod 0600 "$runtime/luna.json"
fi
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
    clicker=$4
    mode=$5
    if [ "$mode" = "--xwayland" ]; then
        labwc --config-dir "$source_root/macrice/de/resources/labwc" \
            --startup "sh \"$source_root/scripts/wayland_xwayland_smoke_client.sh\" \"$runtime\"" \
            >"$runtime/labwc.log" 2>&1 &
        app_id=RiceBowlXwaylandSmoke
    else
        labwc --config-dir "$source_root/macrice/de/resources/labwc" \
            --startup true >"$runtime/labwc.log" 2>&1 &
        app_id=ricebowl-wayland-smoke
    fi
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

    output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
    test -n "$output" || { echo "Headless output missing" >&2; exit 1; }
    WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" \
        --custom-mode 1024x768@60Hz --scale 1

    if [ "$mode" = "--luna" ]; then
        recipe="$runtime/luna.json"
    else
        recipe=classic
    fi
    WAYLAND_DISPLAY=wayland-0 RICEBOWL_DE_TRACE_WINDOWS=1 \
        "$native" --recipe "$recipe" >"$runtime/panel.log" 2>&1 &
    plate=$!
    sleep 1
    kill -0 "$plate" || { sed -n "1,50p" "$runtime/panel.log" >&2; exit 1; }
    # Compare frames at the same neutral pointer position: compositor focus,
    # pointer and hover artifacts must not masquerade as lingering task pixels.
    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 5 5 1024 768
    sleep 0.25
    WAYLAND_DISPLAY=wayland-0 grim - >"$runtime/before.png"

    if [ "$mode" = "--xwayland" ]; then
        : >"$runtime/launch-client"
        count=0
        while [ ! -s "$runtime/client.pid" ] && [ "$count" -lt 40 ]; do
            sleep 0.25
            count=$((count + 1))
        done
        test -s "$runtime/client.pid" || { echo "XWayland client failed to launch" >&2; sed -n "1,80p" "$runtime/labwc.log" >&2; exit 1; }
        window=$(sed -n "1p" "$runtime/client.pid")
    else
        WAYLAND_DISPLAY=wayland-0 foot --app-id="$app_id" \
            --title=RiceBowl-Window-Smoke /bin/sh -c "sleep 30" \
            >"$runtime/window.log" 2>&1 &
        window=$!
    fi
    count=0
    while [ "$count" -lt 40 ]; do
        if grep -Fq "event=ready app_id=\"$app_id\"" "$runtime/panel.log"; then
            break
        fi
        if ! kill -0 "$window" 2>/dev/null; then
            echo "Real Wayland application exited without a task" >&2
            if [ -f "$runtime/window.log" ]; then sed -n "1,60p" "$runtime/window.log" >&2; fi
            sed -n "1,60p" "$runtime/labwc.log" >&2
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

    # Use compositor input, not direct protocol calls to the window under test.
    # This exercises the RicePlate pointer hit test and click handler.
    last_task_state() {
        grep -F "event=ready app_id=\"$app_id\"" "$runtime/panel.log" \
            | tail -n 1 || :
    }
    wait_window_state() {
        expected=$1
        attempts=0
        while [ "$attempts" -lt 40 ]; do
            case "$(last_task_state)" in
                *"$expected"*) return 0 ;;
            esac
            sleep 0.25
            attempts=$((attempts + 1))
        done
        echo "No real Wayland taskbar state: $expected" >&2
        tail -n 35 "$runtime/panel.log" >&2
        return 1
    }
    wait_window_state "active=true minimized=false"
    task_click_x=132
    if [ "$mode" = "--luna" ]; then
        # Real XP Luna recipe geometry at 1024px: Start 0..94;
        # Apps 102..134, Terminal 136..168, Show Desktop 170..202.
        # These coordinates are additionally asserted by Rust hit tests.
        # The actual virtual pointer hits the wl_surface, not a test hook.
        WAYLAND_DISPLAY=wayland-0 "$clicker" 186 750 1024 768
        wait_window_state "minimized=true"
        kill -0 "$window"
        WAYLAND_DISPLAY=wayland-0 grim - >"$runtime/luna-hidden.png"
        WAYLAND_DISPLAY=wayland-0 "$clicker" 186 750 1024 768
        wait_window_state "minimized=false"
        WAYLAND_DISPLAY=wayland-0 grim - >"$runtime/luna-restored.png"
        if cmp -s "$runtime/opened.png" "$runtime/luna-hidden.png"; then
            echo "Show Desktop did not change real compositor pixels" >&2
            exit 1
        fi
        out="$source_root/dist/riceplate-native-preview"
        if [ -d "$out" ]; then
            cp "$runtime/opened.png" "$out/luna-taskbar-window-open.png"
            cp "$runtime/luna-hidden.png" "$out/luna-taskbar-show-desktop.png"
            cp "$runtime/luna-restored.png" "$out/luna-taskbar-window-restored.png"
            sha256sum "$out/luna-taskbar-window-open.png" \
                      "$out/luna-taskbar-show-desktop.png" \
                      "$out/luna-taskbar-window-restored.png" \
                > "$out/luna-taskbar-interaction-SHA256SUMS"
        fi
        task_click_x=240
        # A real right-click on the XP task button must open a bounded native
        # window context menu (not the settings application or an SNI menu).
        WAYLAND_DISPLAY=wayland-0 "$clicker" --right-click "$task_click_x" 750 1024 768
        sleep 0.3
        WAYLAND_DISPLAY=wayland-0 grim - >"$runtime/luna-task-context.png"
        /usr/bin/python3 - "$runtime/opened.png" "$runtime/luna-task-context.png" <<'PY'
import sys
from PIL import Image, ImageChops
with Image.open(sys.argv[1]) as opened, Image.open(sys.argv[2]) as menu:
    before = opened.convert("RGB")
    after = menu.convert("RGB")
    assert before.size == after.size == (1024, 768)
    # Surface remains 288x240 for SNI compatibility, but the XP owner
    # paints only the compact 132px menu above the bottom panel.
    crop = (240, 588, 528, 720)
    delta = ImageChops.difference(before.crop(crop), after.crop(crop))
    changed = sum(1 for px in delta.getdata() if max(px) > 30)
    assert changed > 4000, f"Native task context not visible: {changed} pixels"
    # The original SNI top-of-surface blue header must be absent.
    # Real compositor pixels there still belong to the underlying window.
    above = ImageChops.difference(
        before.crop((270, 500, 510, 530)), after.crop((270, 500, 510, 530)))
    assert sum(1 for px in above.getdata() if max(px) > 30) < 1200, (
        "Unexpected full-size SNI header above compact XP window menu")
    # Disabled Restore is rendered on a light XP face, not a blue header.
    r, g, b = after.getpixel((340, 600))[:3]
    assert r > 170 and g > 170 and b > 165, (
        f"XP menu body unexpectedly dark or missing: {(r, g, b)}")
print("Real compositor shows compact XP task context without SNI header")
PY
        # Compact XP geometry: 132px menu ending at y=720, 24px rows.
        # The second row is Minimize; validate the compositor-provided click.
        WAYLAND_DISPLAY=wayland-0 "$clicker" 290 628 1024 768
        wait_window_state "minimized=true"
        kill -0 "$window"
        WAYLAND_DISPLAY=wayland-0 "$clicker" "$task_click_x" 750 1024 768
        wait_window_state "active=true minimized=false"
        # Exercise the actual layer-shell keyboard focus: with Restore
        # disabled on a normal window, Enter selects the initial Minimize
        # action. This is a real virtual keyboard request through labwc.
        WAYLAND_DISPLAY=wayland-0 "$clicker" --right-click "$task_click_x" 750 1024 768
        sleep 0.25
        WAYLAND_DISPLAY=wayland-0 wtype -k Return
        wait_window_state "minimized=true"
        WAYLAND_DISPLAY=wayland-0 "$clicker" "$task_click_x" 750 1024 768
        wait_window_state "active=true minimized=false"
        out="$source_root/dist/riceplate-native-preview"
        if [ -d "$out" ]; then
            cp "$runtime/luna-task-context.png" "$out/luna-taskbar-window-context.png"
        fi
        echo "XP Luna Show Desktop and real task context menu: compositor controls confirmed"
    fi
    # Verify the normal task button still works after a Show Desktop cycle.
    WAYLAND_DISPLAY=wayland-0 "$clicker" "$task_click_x" 750 1024 768
    wait_window_state "minimized=true"
    kill -0 "$window"
    WAYLAND_DISPLAY=wayland-0 "$clicker" "$task_click_x" 750 1024 768
    wait_window_state "active=true minimized=false"
    echo "Real taskbar pointer click minimized and restored the Wayland client"

    kill "$window"
    wait "$window" 2>/dev/null || :
    window=
    count=0
    while [ "$count" -lt 40 ] &&
        ! grep -Fq "event=closed app_id=\"$app_id\"" "$runtime/panel.log"; do
        sleep 0.25
        count=$((count + 1))
    done
    if [ "$count" -ge 40 ]; then
        echo "RicePlate did not remove the closed real Wayland task" >&2
        sed -n "1,60p" "$runtime/panel.log" >&2
        exit 1
    fi
    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 5 5 1024 768
    sleep 0.5
    WAYLAND_DISPLAY=wayland-0 grim - >"$runtime/closed.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_window_outputs.py" \
        "$runtime/before.png" "$runtime/opened.png" "$runtime/closed.png"
    kill -0 "$plate"
    echo "Native RicePlate observed and painted a real $mode window lifecycle"
' sh "$source_root" "$runtime" "$native" "$clicker" "$mode"

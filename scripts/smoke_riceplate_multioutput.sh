#!/bin/sh
# CI-only: real two-output labwc with one native RicePlate process. The native
# renderer must own both panel surfaces and recover a secondary hotplug.
set -eu

source_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$source_root/components/riceplate-wayland/target/release/riceplate-native"
if [ ! -x "$native" ]; then
    echo "Missing native RicePlate preview binary" >&2
    exit 1
fi
runtime=$(mktemp -d)
chmod 0700 "$runtime"
trap 'rm -r -- "$runtime" 2>/dev/null || :' EXIT
export XDG_RUNTIME_DIR="$runtime"
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=2
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
    watcher=
    cleanup() {
        status=$?
        if [ "$status" -ne 0 ]; then
            echo "RicePlate two-output diagnostic log:" >&2
            sed -n "1,120p" "$runtime/plate.log" >&2 || :
            if [ -f "$runtime/plate-calendar.log" ]; then
                sed -n "1,120p" "$runtime/plate-calendar.log" >&2 || :
            fi
            if [ -f "$runtime/plate-menu.log" ]; then
                sed -n "1,120p" "$runtime/plate-menu.log" >&2 || :
            fi
            echo "labwc two-output diagnostic log:" >&2
            sed -n "1,100p" "$runtime/labwc.log" >&2 || :
            wlr-randr >&2 || :
        fi
        if [ -n "$plate" ]; then kill "$plate" 2>/dev/null || :; wait "$plate" 2>/dev/null || :; fi
        if [ -n "$watcher" ]; then kill "$watcher" 2>/dev/null || :; wait "$watcher" 2>/dev/null || :; fi
        kill "$compositor" 2>/dev/null || :
        wait "$compositor" 2>/dev/null || :
    }
    trap cleanup EXIT
    count=0
    while [ "$count" -lt 40 ] && [ ! -S "$runtime/wayland-0" ]; do
        kill -0 "$compositor" 2>/dev/null || exit 1
        count=$((count + 1))
        sleep 0.25
    done
    [ -S "$runtime/wayland-0" ] || { echo "No headless Wayland socket" >&2; exit 1; }
    export WAYLAND_DISPLAY=wayland-0
    # This Rust Wayland listener creates no surface and emits only changes,
    # never the initial inventory. It is used solely by the Waybar fallback.
    RICEBOWL_DE_SHELL_CHILD=1 "$native" --watch-outputs \
        >"$runtime/output-events.log" 2>"$runtime/output-watch.log" &
    watcher=$!
    sleep 0.4
    kill -0 "$watcher" 2>/dev/null || { cat "$runtime/output-watch.log" >&2; exit 1; }
    [ ! -s "$runtime/output-events.log" ] || {
        echo "Initial output inventory incorrectly caused a refresh" >&2; exit 1;
    }
    "$native" --recipe classic >"$runtime/plate.log" 2>&1 &
    plate=$!
    count=0
    while [ "$count" -lt 30 ]; do
        if ! kill -0 "$plate" 2>/dev/null; then
            echo "Native panel exited before output test" >&2
            sed -n "1,120p" "$runtime/plate.log" >&2
            exit 1
        fi
        count=$((count + 1))
        sleep 0.1
    done
    set -- $(wlr-randr | sed -n "/^[A-Za-z0-9_.-][A-Za-z0-9_.-]*[[:space:]]/s/[[:space:]].*//p")
    [ "$#" -eq 2 ] || { echo "Expected exactly two Wayland outputs" >&2; exit 1; }
    first=$1
    second=$2
    grim -o "$first" "$runtime/first.png"
    grim -o "$second" "$runtime/second.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_panel_outputs.py" \
        "$runtime/first.png" "$runtime/second.png"
    wlr-randr --output "$second" --off
    sleep 0.6
    grep -q "^changed$" "$runtime/output-events.log" || {
        echo "Output watcher missed headless hot-unplug" >&2
        cat "$runtime/output-watch.log" >&2
        exit 1
    }
    grim -o "$first" "$runtime/first-after-off.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_panel_outputs.py" \
        "$runtime/first-after-off.png"
    wlr-randr --output "$second" --on
    sleep 0.8
    grim -o "$second" "$runtime/second-after-on.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_panel_outputs.py" \
        "$runtime/second-after-on.png"
    kill -0 "$plate" 2>/dev/null || { echo "Native panel exited after hotplug" >&2; exit 1; }
    # A secondary panel clock must open its own calendar on that output, with
    # no duplicate popup on the primary. Identify the actual owner by pixels
    # rather than depending on connector naming or compositor output order.
    kill "$plate" 2>/dev/null || :
    wait "$plate" 2>/dev/null || :
    plate=
    RICEBOWL_DE_CALENDAR_OUTPUT=secondary "$native" --recipe classic --preview-calendar \
        >"$runtime/plate-calendar.log" 2>&1 &
    plate=$!
    sleep 1.5
    kill -0 "$plate" 2>/dev/null || { echo "Native calendar preview exited" >&2; exit 1; }
    grim -o "$first" "$runtime/first-calendar.png"
    grim -o "$second" "$runtime/second-calendar.png"
    calendar_index=$(/usr/bin/python3 "$source_root/scripts/check_wayland_calendar_outputs.py" \
        "$runtime/first-calendar.png" "$runtime/second-calendar.png")
    case "$calendar_index" in
        0) calendar_output=$first; remaining_output=$second ;;
        1) calendar_output=$second; remaining_output=$first ;;
        *) echo "Invalid calendar output index: $calendar_index" >&2; exit 1 ;;
    esac
    wlr-randr --output "$calendar_output" --off
    sleep 0.7
    grim -o "$remaining_output" "$runtime/remaining-calendar-off.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_panel_outputs.py" \
        "$runtime/remaining-calendar-off.png"
    kill -0 "$plate" 2>/dev/null || { echo "Native calendar exited after output removal" >&2; exit 1; }
    wlr-randr --output "$calendar_output" --on
    sleep 0.8
    grim -o "$calendar_output" "$runtime/calendar-after-on.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_panel_outputs.py" \
        "$runtime/calendar-after-on.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_calendar_outputs.py" \
        --closed "$runtime/calendar-after-on.png"
    kill -0 "$plate" 2>/dev/null || { echo "Native calendar exited after output recovery" >&2; exit 1; }
    # A native schema-v5 menu must likewise open on the secondary monitor,
    # using the same action model instead of invoking an unrelated launcher.
    kill "$plate" 2>/dev/null || :
    wait "$plate" 2>/dev/null || :
    plate=
    cp "$source_root/tests/fixtures/riceplate-desktop-v5.json" "$runtime/desktop-v5.json"
    chmod 0600 "$runtime/desktop-v5.json"
    RICEBOWL_DE_MENU_OUTPUT=secondary "$native" --recipe "$runtime/desktop-v5.json" --preview-menu \
        >"$runtime/plate-menu.log" 2>&1 &
    plate=$!
    sleep 1.5
    kill -0 "$plate" 2>/dev/null || { echo "Native menu preview exited" >&2; exit 1; }
    grim -o "$first" "$runtime/first-menu.png"
    grim -o "$second" "$runtime/second-menu.png"
    menu_index=$(/usr/bin/python3 "$source_root/scripts/check_wayland_menu_outputs.py" \
        "$runtime/first-menu.png" "$runtime/second-menu.png")
    case "$menu_index" in
        0) menu_output=$first; remaining_output=$second ;;
        1) menu_output=$second; remaining_output=$first ;;
        *) echo "Invalid menu output index: $menu_index" >&2; exit 1 ;;
    esac
    wlr-randr --output "$menu_output" --off
    sleep 0.7
    grim -o "$remaining_output" "$runtime/remaining-menu-off.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_menu_outputs.py" \
        --closed "$runtime/remaining-menu-off.png"
    kill -0 "$plate" 2>/dev/null || { echo "Native menu exited after output removal" >&2; exit 1; }
    wlr-randr --output "$menu_output" --on
    sleep 0.8
    grim -o "$menu_output" "$runtime/menu-after-on.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_menu_outputs.py" \
        --closed "$runtime/menu-after-on.png"
    kill -0 "$plate" 2>/dev/null || { echo "Native menu exited after output recovery" >&2; exit 1; }
    # With the popup closed, a schema-v5 desktop shortcut must paint on both
    # output-bound Bottom layers and recover when a monitor returns.
    kill "$plate" 2>/dev/null || :
    wait "$plate" 2>/dev/null || :
    plate=
    "$native" --recipe "$runtime/desktop-v5.json" >"$runtime/plate-icons.log" 2>&1 &
    plate=$!
    sleep 1.5
    kill -0 "$plate" 2>/dev/null || { echo "Native icon preview exited" >&2; exit 1; }
    grim -o "$first" "$runtime/first-icons.png"
    grim -o "$second" "$runtime/second-icons.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_icon_outputs.py" \
        "$runtime/first-icons.png" "$runtime/second-icons.png"
    wlr-randr --output "$second" --off
    sleep 0.7
    grim -o "$first" "$runtime/icons-after-off.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_icon_outputs.py" \
        "$runtime/icons-after-off.png"
    wlr-randr --output "$second" --on
    sleep 0.8
    grim -o "$second" "$runtime/icons-after-on.png"
    /usr/bin/python3 "$source_root/scripts/check_wayland_icon_outputs.py" \
        "$runtime/icons-after-on.png"
    kill -0 "$plate" 2>/dev/null || { echo "Native icons exited after hotplug" >&2; exit 1; }
    # These are real grim captures from two actual compositor outputs. Keep
    # them in the workflow artifact for inspection rather than discarding
    # all evidence with the private runtime directory.
    captures="$source_root/dist/riceplate-native-preview/multioutput"
    mkdir -p "$captures"
    cp "$runtime/first.png" "$captures/first.png"
    cp "$runtime/second.png" "$captures/second.png"
    cp "$runtime/first-after-off.png" "$captures/first-after-off.png"
    cp "$runtime/second-after-on.png" "$captures/second-after-on.png"
    cp "$runtime/first-calendar.png" "$captures/first-calendar.png"
    cp "$runtime/second-calendar.png" "$captures/second-calendar.png"
    cp "$runtime/remaining-calendar-off.png" "$captures/remaining-calendar-off.png"
    cp "$runtime/calendar-after-on.png" "$captures/calendar-after-on.png"
    cp "$runtime/first-menu.png" "$captures/first-menu.png"
    cp "$runtime/second-menu.png" "$captures/second-menu.png"
    cp "$runtime/remaining-menu-off.png" "$captures/remaining-menu-off.png"
    cp "$runtime/menu-after-on.png" "$captures/menu-after-on.png"
    cp "$runtime/first-icons.png" "$captures/first-icons.png"
    cp "$runtime/second-icons.png" "$captures/second-icons.png"
    cp "$runtime/icons-after-off.png" "$captures/icons-after-off.png"
    cp "$runtime/icons-after-on.png" "$captures/icons-after-on.png"
    # The ordinary preview is nested and cannot write XDG Desktop state.
    # Restart only this disposable two-headless-output compositor with a
    # real isolated HOME to test XDG file-icon handoff and unplug fallback.
    kill "$plate" 2>/dev/null || :
    wait "$plate" 2>/dev/null || :
    plate=
    wlr-randr --output "$first" --custom-mode 800x600@60Hz --scale 1 --pos 0,0
    wlr-randr --output "$second" --custom-mode 800x600@60Hz --scale 1 --pos 800,0
    mkdir -m 0700 "$runtime/file-home" "$runtime/file-home/Desktop" "$runtime/file-config"
    printf "%s\n" "XDG_DESKTOP_DIR=\"\$HOME/Desktop\"" >"$runtime/file-config/user-dirs.dirs"
    printf "%s\n" "Native multioutput file icon" >"$runtime/file-home/Desktop/00-cross.txt"
    cp "$source_root/examples/wayland/xp-luna-columns.json" "$runtime/file-rice.json"
    chmod 0600 "$runtime/file-rice.json"
    HOME="$runtime/file-home" XDG_CONFIG_HOME="$runtime/file-config" \
        RICEBOWL_DE_NESTED=0 RICEBOWL_DE_TRACE_FILES=1 \
        "$native" --recipe "$runtime/file-rice.json" >"$runtime/file-plate.log" 2>&1 &
    plate=$!
    sleep 1.5
    kill -0 "$plate"
    position=$(sed -n "s/.*XDG mapped x=\([0-9][0-9]*\) y=\([0-9][0-9]*\) kind=File.*/\1 \2/p" \
        "$runtime/file-plate.log" | head -n 1)
    test -n "$position" || {
        echo "Two-output native file icon was not mapped" >&2
        tail -n 50 "$runtime/file-plate.log" >&2
        exit 1
    }
    set -- $position
    start_x=$(($1 + 52))
    start_y=$(($2 + 43))
    test "$start_x" -lt 800
    test "$start_y" -lt 600
    clicker="$source_root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
    grim -o "$first" "$runtime/file-first-before.png"
    grim -o "$second" "$runtime/file-second-before.png"
    # Width is the real composed output layout, not an invented per-output
    # coordinate space. Press on primary, move across x=800 and release.
    "$clicker" --drag-to 920 250 "$start_x" "$start_y" 1600 600
    sleep 0.8
    grep -Fq "RicePlate: XDG icon moved to another display" "$runtime/file-plate.log" || {
        echo "Real Wayland cross-output XDG file drag failed" >&2
        tail -n 65 "$runtime/file-plate.log" >&2
        exit 1
    }
    position_file="$runtime/file-config/ricebowl/native-file-positions.json"
    /usr/bin/python3 - "$position_file" "$second" << "PY"
import json
from pathlib import Path
import sys
state = json.loads(Path(sys.argv[1]).read_text())
assert state["schema_version"] == 1
assert any(value["output"] == sys.argv[2]
           for value in state["records"].values()), state
PY
    test -f "$runtime/file-home/Desktop/00-cross.txt"
    grim -o "$first" "$runtime/file-first-after-transfer.png"
    grim -o "$second" "$runtime/file-second-after-transfer.png"
    /usr/bin/python3 - "$runtime/file-second-before.png" \
        "$runtime/file-second-after-transfer.png" << "PY"
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as before, Image.open(sys.argv[2]) as after:
    assert before.size == after.size == (800, 600)
    diff = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
    assert sum(max(pixel) > 20 for pixel in diff.getdata()) > 100, \
        "No compositor-visible file icon on the second output"
PY
    # Disconnecting the assigned monitor must temporarily show its file on
    # the primary without rewriting the saved second-output assignment.
    wlr-randr --output "$second" --off
    sleep 0.8
    kill -0 "$plate"
    grim -o "$first" "$runtime/file-fallback-primary.png"
    wlr-randr --output "$second" --on
    sleep 0.8
    kill -0 "$plate"
    grim -o "$second" "$runtime/file-restored-secondary.png"
    /usr/bin/python3 - "$position_file" "$second" << "PY"
import json
from pathlib import Path
import sys
state = json.loads(Path(sys.argv[1]).read_text())
assert any(value["output"] == sys.argv[2] for value in state["records"].values())
PY
    cp "$runtime/file-first-before.png" "$captures/file-first-before.png"
    cp "$runtime/file-second-before.png" "$captures/file-second-before.png"
    cp "$runtime/file-second-after-transfer.png" "$captures/file-second-after-transfer.png"
    cp "$runtime/file-fallback-primary.png" "$captures/file-fallback-primary.png"
    cp "$runtime/file-restored-secondary.png" "$captures/file-restored-secondary.png"
    echo "Verified real two-output XDG file drop, persisted target assignment and unplug/restore in labwc"
    echo "Native RicePlate painted two outputs, output-bound menus/calendars/icons and survived hotplug"
' sh "$source_root" "$runtime" "$native"

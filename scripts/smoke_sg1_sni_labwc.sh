#!/bin/sh
# Standalone SG1 proof: real DBus session, provider, layer-shell, virtual input.
# Intentionally NOT part of the shared Chrome/Fuzzel/native smoke script.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$root/components/riceplate-wayland/target/release/riceplate-native"
clicker="$root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
provider="$root/scripts/fixtures/sg1_sni_provider.py"
for command in dbus-run-session labwc wlr-randr wtype gdbus; do
    command -v "$command" >/dev/null || { echo "Missing $command" >&2; exit 77; }
done
test -x "$native" && test -x "$clicker" || {
    echo "Build native release binary and wayland_pointer_click example first" >&2
    exit 77
}
/usr/bin/python3 -c 'import gi; from gi.repository import Gio, GLib' || exit 77

runtime=$(mktemp -d)
chmod 0700 "$runtime"
trap 'rm -rf -- "$runtime"' EXIT
cp "$root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
chmod 0600 "$runtime/luna.json"
export XDG_RUNTIME_DIR="$runtime"
export XDG_CONFIG_HOME="$runtime"
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=1
export WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=1

dbus-run-session -- sh -eu -c '
    root=$1 runtime=$2 native=$3 clicker=$4 provider=$5
    labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
        >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    plate= provider_pid= keyboard_keeper=
    cleanup() {
        [ -z "$provider_pid" ] || { kill "$provider_pid" 2>/dev/null || :; wait "$provider_pid" 2>/dev/null || :; }
        [ -z "$plate" ] || { kill "$plate" 2>/dev/null || :; wait "$plate" 2>/dev/null || :; }
        [ -z "$keyboard_keeper" ] || { kill "$keyboard_keeper" 2>/dev/null || :; wait "$keyboard_keeper" 2>/dev/null || :; }
        kill "$compositor" 2>/dev/null || :
        wait "$compositor" 2>/dev/null || :
    }
    trap cleanup EXIT
    ready() {
        file=$1
        n=0
        while [ ! -s "$file" ] && [ "$n" -lt 80 ]; do
            n=$((n + 1))
            sleep .15
        done
        [ -s "$file" ] || {
            echo "Timeout waiting for $file" >&2
            tail -n 40 "$runtime"/plate-*.log "$runtime"/provider-*.log 2>/dev/null >&2 || :
            exit 1
        }
    }
    ready_socket() {
        n=0
        while [ ! -S "$runtime/wayland-0" ] && [ "$n" -lt 60 ]; do
            kill -0 "$compositor" || exit 1
            n=$((n + 1))
            sleep .2
        done
        [ -S "$runtime/wayland-0" ] || exit 1
    }
    assert_receipt() {
        # All assertions inspect parsed JSON, not timing-sensitive grep text.
        /usr/bin/python3 - "$runtime/receipts.jsonl" "$1" "$2" "$3" <<PY
import json, sys
path, generation, action, node = sys.argv[1:]
items = [json.loads(line) for line in open(path, encoding="utf-8")]
match = [entry for entry in items
         if entry["generation"] == generation
         and entry["event"] == "menu-event"
         and entry.get("action") == action and entry.get("id") == int(node)]
assert match, f"Missing actual D-Bus action {generation}/{action}/{node}: {items[-12:]}"
PY
    }
    assert_no_click() {
        /usr/bin/python3 - "$runtime/receipts.jsonl" "$1" <<PY
import json, sys
entries = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
hits = [e for e in entries if e["generation"] == sys.argv[2]
        and e["event"] == "menu-event" and e.get("action") == "clicked"]
assert not hits, f"New SNI owner inherited stale input: {hits}"
PY
    }
    ready_menu_snapshot() {
        previous=$1
        attempt=0
        while [ "$attempt" -lt 80 ]; do
            count=$(grep -c "RicePlate: SNI DBusMenu snapshot ready" \
                "$runtime/plate-$rice.log" 2>/dev/null || :)
            [ "$count" -gt "$previous" ] && return 0
            kill -0 "$plate" 2>/dev/null || break
            attempt=$((attempt + 1))
            sleep .1
        done
        echo "$rice SNI provider registered but no validated DBusMenu snapshot arrived" >&2
        tail -n 75 "$runtime/plate-$rice.log" >&2 || :
        return 1
    }
    ready_socket
    output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
    test -n "$output"
    WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" \
        --custom-mode 1366x768@60Hz --scale 1
    WAYLAND_DISPLAY=wayland-0 wtype -k F13 -s 1800000 -k F13 >"$runtime/keyboard.log" 2>&1 &
    keyboard_keeper=$!
    sleep .4
    kill -0 "$keyboard_keeper"

    # Both rices must prove the same real DBusMenu context activation path.
    # The Luna primary-click route also closes desktop focus overlays and can
    # produce a distinct seat lifetime; do not equate the two paths.
    open_fixture_menu() {
        WAYLAND_DISPLAY=wayland-0 "$clicker" --right-click "$tray_x" 746 1366 768
    }

    for rice in luna chrome; do
        if [ "$rice" = chrome ]; then
            recipe=chrome tray_x=1270
        else
            recipe="$runtime/luna.json" tray_x=1185
        fi
        RICEBOWL_DE_TRACE_TRAY=1 RICEBOWL_DE_TRACE_FOCUS=1 WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$recipe" \
            >"$runtime/plate-$rice.log" 2>&1 &
        plate=$!
        sleep 1
        kill -0 "$plate" || { tail -n 40 "$runtime/plate-$rice.log" >&2; exit 1; }

        # The real SNI host exports the Watcher; provider retries registration
        # until it exists, then records exact unique owner and menu events.
        prior_menus=$(grep -c "RicePlate: SNI DBusMenu snapshot ready" \
            "$runtime/plate-$rice.log" 2>/dev/null || :)
        /usr/bin/python3 "$provider" \
            --generation "$rice-old" \
            --receipts "$runtime/receipts.jsonl" --ready "$runtime/ready-old" \
            >"$runtime/provider-$rice-old.log" 2>&1 &
        provider_pid=$!
        ready "$runtime/ready-old"
        ready_menu_snapshot "$prior_menus"

        # Real compositor pointer -> native menu, real keyboard into submenu,
        # real D-Bus method Event(clicked) receipt from independently owned app.
        open_fixture_menu
        # Prove that the explicit pointer menu request actually acquired
        # compositor-confirmed wl_keyboard focus, not just a D-Bus root menu.
        count=0
        while [ "$count" -lt 30 ] &&
            ! grep -Fq "compositor confirmed tray popup keyboard focus" "$runtime/plate-$rice.log"; do
            count=$((count + 1))
            sleep .1
        done
        if [ "$count" -ge 30 ]; then
            echo "$rice SNI menu opened without compositor keyboard focus" >&2
            tail -n 65 "$runtime/plate-$rice.log" >&2 || :
            exit 1
        fi
        # Keep one compositor virtual-keyboard object alive through submenu
        # transition. Separate wtype clients can briefly drop keyboard focus
        # between their wl_keyboard.leave/enter events (XP Luna on labwc).
        WAYLAND_DISPLAY=wayland-0 wtype -k Return -s 350 -k Return
        sleep .5
        if ! assert_receipt "$rice-old" clicked 21; then
            tail -n 60 "$runtime/plate-$rice.log" >&2 || :
            tail -n 40 "$runtime/provider-$rice-old.log" >&2 || :
            exit 1
        fi

        # Open a fresh menu and leave it pending while the item owner dies.
        open_fixture_menu
        sleep .3
        kill "$provider_pid"
        wait "$provider_pid" 2>/dev/null || :
        provider_pid=
        sleep .45
        prior_menus=$(grep -c "RicePlate: SNI DBusMenu snapshot ready" \
            "$runtime/plate-$rice.log" 2>/dev/null || :)
        /usr/bin/python3 "$provider" \
            --generation "$rice-new" \
            --receipts "$runtime/receipts.jsonl" --ready "$runtime/ready-new" \
            >"$runtime/provider-$rice-new.log" 2>&1 &
        provider_pid=$!
        ready "$runtime/ready-new"
        ready_menu_snapshot "$prior_menus"
        WAYLAND_DISPLAY=wayland-0 wtype -k Return
        sleep .4
        assert_no_click "$rice-new"

        # A deliberate fresh pointer reopen restores working actions.
        open_fixture_menu
        sleep .4
        # The fresh owner requires a new pointer open; keep the subsequent
        # nested keyboard navigation within a single virtual keyboard client.
        WAYLAND_DISPLAY=wayland-0 wtype -k Return -s 350 -k Return
        sleep .4
        if ! assert_receipt "$rice-new" clicked 21; then
            tail -n 60 "$runtime/plate-$rice.log" >&2 || :
            tail -n 40 "$runtime/provider-$rice-new.log" >&2 || :
            exit 1
        fi

        # Removing a live remote node must revoke the old keyboard selection.
        gdbus call --session --dest org.ricebowl.SNIFixture \
            --object-path /Control \
            --method org.ricebowl.SNIFixtureControl.SetMode removed >/dev/null
        sleep .35
        kill -0 "$plate"
        WAYLAND_DISPLAY=wayland-0 wtype -k Escape
        kill "$provider_pid"
        wait "$provider_pid" 2>/dev/null || :
        provider_pid=
        kill "$plate"
        wait "$plate" 2>/dev/null || :
        plate=
        rm -f "$runtime/ready-old" "$runtime/ready-new"
        echo "SG1 real DBus/labwc SNI lifecycle receipts PASS: $rice"
    done
' sh "$root" "$runtime" "$native" "$clicker" "$provider"

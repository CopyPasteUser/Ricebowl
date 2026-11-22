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
# The native Luna installed-app index and its Gio-launch target are
# deliberately private to this disposable compositor session.
mkdir -m 0700 "$runtime/data" "$runtime/data/applications"
export XDG_DATA_HOME="$runtime/data"
export RICEBOWL_CI_SG1_LAUNCH_RECEIPT="$runtime/luna-launch-receipt"
cat >"$runtime/luna-app-witness" <<'SG1_LUNA_WITNESS'
#!/bin/sh
[ "$#" -eq 0 ] || exit 64
[ -n "${RICEBOWL_CI_SG1_LAUNCH_RECEIPT:-}" ] || exit 64
printf '%s\n' 'luna-keyboard-launch-received' >"$RICEBOWL_CI_SG1_LAUNCH_RECEIPT"
SG1_LUNA_WITNESS
chmod 0700 "$runtime/luna-app-witness"
cat >"$XDG_DATA_HOME/applications/ricebowl-sg1-witness.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=RiceBowl SG1 Witness
Keywords=sg1witness;
Exec=$runtime/luna-app-witness
Terminal=false
EOF
chmod 0600 "$XDG_DATA_HOME/applications/ricebowl-sg1-witness.desktop"
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
    count_receipt() {
        /usr/bin/python3 - "$runtime/receipts.jsonl" "$1" "$2" "$3" <<PY
import json, sys
path, generation, action, node = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    entries = [json.loads(line) for line in stream]
print(sum(1 for entry in entries
          if entry["generation"] == generation
          and entry["event"] == "menu-event"
          and entry.get("action") == action and entry.get("id") == int(node)))
PY
    }
    assert_no_item_method() {
        # ItemIsMenu=true must route left-click to a native DBusMenu, not
        # silently fall back to a provider Activate/ContextMenu method.
        /usr/bin/python3 - "$runtime/receipts.jsonl" "$1" <<PY
import json, sys
path, generation = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    items = [json.loads(line) for line in stream]
calls = [row for row in items if row["generation"] == generation
         and row["event"] == "item"]
assert not calls, f"ItemIsMenu fell back to SNI item method: {calls}"
PY
    }
    set_fixture_mode() {
        # The D-Bus SetMode reply only confirms the provider, not the shell
        # cache. Wait for a *new* GetLayout receipt for this mode, or a
        # keyboard press could target an obsolete enabled menu snapshot.
        mode=$1
        /usr/bin/python3 - "$runtime/receipts.jsonl" "$rice-new" "$mode" <<PY >"$runtime/layout-before"
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    rows = [json.loads(line) for line in source]
print(sum(r["generation"] == sys.argv[2] and r["event"] == "layout"
          and r.get("mode") == sys.argv[3] for r in rows))
PY
        before=$(cat "$runtime/layout-before")
        gdbus call --session --dest org.ricebowl.SNIFixture \
            --object-path /Control \
            --method org.ricebowl.SNIFixtureControl.SetMode "$mode" >/dev/null
        count=0
        while [ "$count" -lt 40 ]; do
            current=$(/usr/bin/python3 - "$runtime/receipts.jsonl" "$rice-new" "$mode" <<PY
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    rows = [json.loads(line) for line in source]
print(sum(r["generation"] == sys.argv[2] and r["event"] == "layout"
          and r.get("mode") == sys.argv[3] for r in rows))
PY
)
            if [ "$current" -gt "$before" ]; then
                # Give the reactor one compositor event-loop tick to install
                # the fetched snapshot before input can be dispatched.
                sleep .2
                return 0
            fi
            count=$((count + 1))
            sleep .1
        done
        echo "$rice did not refetch SNI layout after SetMode $mode" >&2
        tail -n 70 "$runtime/plate-$rice.log" >&2 || :
        /usr/bin/python3 - "$runtime/receipts.jsonl" "$rice-new" <<PY >&2
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    rows=[json.loads(line) for line in stream]
print("Private fixture last events:", rows[-14:])
PY
        return 1
    }
    assert_action_mode_once() {
        /usr/bin/python3 - "$runtime/receipts.jsonl" "$1" "$2" "$3" "$4" <<PY
import json, sys
path, generation, action, node, mode = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    events = [json.loads(line) for line in stream]
matches = [r for r in events
           if r["generation"] == generation and r["event"] == "menu-event"
           and r.get("action") == action and r.get("id") == int(node)
           and r.get("mode") == mode]
assert len(matches) == 1, f"Expected one {mode} receipt {generation}/{node}, got {len(matches)}"
PY
    }
    assert_no_action_for_mode() {
        /usr/bin/python3 - "$runtime/receipts.jsonl" "$1" "$2" <<PY
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    events = [json.loads(line) for line in stream]
bad = [r for r in events
       if r["generation"] == sys.argv[2] and r["event"] == "menu-event"
       and r.get("mode") == sys.argv[3] and r.get("action") == "clicked"]
assert not bad, f"Unsafe action in {sys.argv[3]}: {bad}"
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
    # A virtual keyboard in wtype is a seat-bound protocol object, not a
    # physical keyboard. Reusing it after the previous RicePlate disconnects
    # can leave the disposable compositor with a stale synthetic seat focus.
    # Attach a fresh input device for each rice while keeping the SAME labwc,
    # D-Bus session, and screen. Test each actual compositor input path; do
    # not count synthetic logs as an action receipt or infer a hot-swap pass.
    renew_keyboard_seat() {
        if [ -n "$keyboard_keeper" ]; then
            kill "$keyboard_keeper" 2>/dev/null || :
            wait "$keyboard_keeper" 2>/dev/null || :
            keyboard_keeper=
        fi
        WAYLAND_DISPLAY=wayland-0 wtype -k F13 -s 1800000 -k F13 \
            >"$runtime/keyboard-$rice.log" 2>&1 &
        keyboard_keeper=$!
        sleep .4
        kill -0 "$keyboard_keeper" || {
            echo "$rice virtual keyboard failed to attach to labwc" >&2
            cat "$runtime/keyboard-$rice.log" >&2 || :
            exit 1
        }
    }

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
        renew_keyboard_seat
        RICEBOWL_DE_TRACE_TRAY=1 RICEBOWL_DE_TRACE_FOCUS=1 WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$recipe" \
            >"$runtime/plate-$rice.log" 2>&1 &
        plate=$!
        sleep 1
        kill -0 "$plate" || { tail -n 40 "$runtime/plate-$rice.log" >&2; exit 1; }

        if [ "$rice" = luna ]; then
            # Complete the XP Luna half of SG1 app/search acceptance. Chrome
            # already proves pointer -> Fuzzel keyboard search -> real Exec
            # in smoke_riceplate_native.sh (#573). Here a real compositor
            # pointer opens Start; keyboard slash filters the actual native
            # installed-app index; Return must traverse Gio launch and execute
            # an XDG desktop entry visible ONLY in this private XDG_DATA_HOME.
            # A painted search result alone is not a successful app launch.
            test ! -e "$RICEBOWL_CI_SG1_LAUNCH_RECEIPT"
            WAYLAND_DISPLAY=wayland-0 "$clicker" 35 748 1366 768
            sleep .3
            WAYLAND_DISPLAY=wayland-0 wtype -k slash -d 50 "sg1witness" -s 350 -k Return
            count=0
            while [ ! -s "$RICEBOWL_CI_SG1_LAUNCH_RECEIPT" ] && [ "$count" -lt 40 ]; do
                count=$((count + 1))
                sleep .1
            done
            if [ "$(cat "$RICEBOWL_CI_SG1_LAUNCH_RECEIPT" 2>/dev/null || :)" != "luna-keyboard-launch-received" ]; then
                echo "XP Luna pointer/Search/Return did not execute private installed application" >&2
                tail -n 75 "$runtime/plate-$rice.log" >&2 || :
                exit 1
            fi
            WAYLAND_DISPLAY=wayland-0 wtype -k Escape -k Escape
            sleep .2
            kill -0 "$plate"
            echo "SG1 XP Luna pointer -> installed-app search -> compositor keyboard Return -> Gio Exec PASS"
        fi

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

        # The real fixture advertises ItemIsMenu=true. Its PRIMARY click must
        # open the same native menu as the secondary-click path, and a fresh
        # compositor keyboard action must dispatch exactly one additional
        # clicked/21 event to the original D-Bus owner on BOTH rices.
        # Checking a delta prevents the earlier right-click receipt from
        # falsely satisfying this new acceptance path.
        primary_before=$(count_receipt "$rice-old" clicked 21)
        WAYLAND_DISPLAY=wayland-0 "$clicker" "$tray_x" 746 1366 768
        sleep .3
        WAYLAND_DISPLAY=wayland-0 wtype -k Return -s 350 -k Return
        sleep .4
        primary_after=$(count_receipt "$rice-old" clicked 21)
        if [ "$primary_after" -ne "$((primary_before + 1))" ]; then
            echo "$rice ItemIsMenu primary click did not dispatch exactly one nested action" >&2
            tail -n 65 "$runtime/plate-$rice.log" >&2 || :
            tail -n 40 "$runtime/provider-$rice-old.log" >&2 || :
            exit 1
        fi
        assert_no_item_method "$rice-old"

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

        # Real provider state matrix: both rices share one compositor and
        # each has a freshly owned D-Bus generation with isolated receipts.
        set_fixture_mode disabled
        enabled_before=$(count_receipt "$rice-new" clicked 10)
        disabled_before=$(count_receipt "$rice-new" clicked 11)
        open_fixture_menu
        sleep .2
        WAYLAND_DISPLAY=wayland-0 wtype -k Down -s 120 -k Down -s 120 -k Return
        sleep .3
        disabled_after=$(count_receipt "$rice-new" clicked 11)
        enabled_after=$(count_receipt "$rice-new" clicked 10)
        [ "$disabled_after" -eq "$disabled_before" ] || {
            echo "$rice disabled SNI item was invoked" >&2
            tail -n 80 "$runtime/plate-$rice.log" >&2 || :
            /usr/bin/python3 - "$runtime/receipts.jsonl" "$rice-new" <<PY >&2
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    rows=[json.loads(line) for line in stream]
print("Private fixture disabled receipts:", [r for r in rows
      if r["generation"] == sys.argv[2] and r["event"] in ("layout", "mode", "menu-event")][-14:])
PY
            exit 1;
        }
        [ "$enabled_after" -eq "$((enabled_before + 1))" ] || {
            echo "$rice disabled SNI navigation did not dispatch enabled action" >&2; exit 1;
        }
        assert_action_mode_once "$rice-new" clicked 10 disabled

        # A valid row may be denied by its owner. Prove the actual failed
        # provider operation and require the shell to remain responsive.
        set_fixture_mode denied
        open_fixture_menu
        sleep .2
        WAYLAND_DISPLAY=wayland-0 wtype -k Down -s 120 -k Return
        sleep .3
        assert_action_mode_once "$rice-new" clicked 10 denied
        kill -0 "$plate"

        # Empty provider snapshots must revoke all previously reachable
        # menu IDs, including stale keyboard activation across the transition.
        set_fixture_mode empty
        before_empty=$(count_receipt "$rice-new" clicked 21)
        open_fixture_menu
        sleep .2
        WAYLAND_DISPLAY=wayland-0 wtype -k Return -s 120 -k Return
        sleep .2
        after_empty=$(count_receipt "$rice-new" clicked 21)
        [ "$after_empty" -eq "$before_empty" ] || {
            echo "$rice empty menu retained stale submenu action" >&2; exit 1;
        }
        assert_no_action_for_mode "$rice-new" empty
        assert_no_item_method "$rice-new"

        # Compositor-delivered Escape cancels menu focus. Subsequent Return
        # cannot reuse a previous remote selection without a new user open.
        set_fixture_mode normal
        open_fixture_menu
        sleep .2
        before_escape=$(count_receipt "$rice-new" clicked 21)
        WAYLAND_DISPLAY=wayland-0 wtype -k Escape -s 150 -k Return -k Return
        sleep .2
        after_escape=$(count_receipt "$rice-new" clicked 21)
        [ "$after_escape" -eq "$before_escape" ] || {
            echo "$rice dismissed menu retained keyboard activation" >&2; exit 1;
        }

        # The 390ms GetLayout is an actual asynchronous loading delay.
        # Once it resolves, a fresh pointer/keyboard gesture must work again.
        set_fixture_mode slow
        open_fixture_menu
        sleep .7
        WAYLAND_DISPLAY=wayland-0 wtype -k Return -s 300 -k Return
        sleep .3
        assert_action_mode_once "$rice-new" clicked 21 slow
        set_fixture_mode normal
        recovery_before=$(count_receipt "$rice-new" clicked 21)
        open_fixture_menu
        sleep .25
        WAYLAND_DISPLAY=wayland-0 wtype -k Return -s 300 -k Return
        sleep .3
        recovery_after=$(count_receipt "$rice-new" clicked 21)
        [ "$recovery_after" -eq "$((recovery_before + 1))" ] || {
            echo "$rice menu did not recover after negative states" >&2; exit 1;
        }
        kill -0 "$plate"
        echo "SG1 real disabled/denied/empty/Escape/slow/recovery receipts PASS: $rice"

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

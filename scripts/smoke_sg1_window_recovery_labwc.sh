#!/bin/sh
# Real compositor-driven SG1 taskbar state/focus/stale-handle verification.
# Never attaches to the logged-in session or changes the host desktop.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$root/components/riceplate-wayland/target/release/riceplate-native"
clicker="$root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
for cmd in labwc dbus-run-session foot wlr-randr wtype timeout; do
    command -v "$cmd" >/dev/null || { echo "Missing SG1 dependency: $cmd" >&2; exit 1; }
done
test -x "$native" && test -x "$clicker" || {
    echo 'Build release riceplate-native and wayland_pointer_click first' >&2; exit 1;
}
for rice in chrome luna; do
    runtime=$(mktemp -d)
    chmod 0700 "$runtime"
    if [ "$rice" = luna ]; then
        cp "$root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
        chmod 0600 "$runtime/luna.json"
    fi
    if (
        export XDG_RUNTIME_DIR="$runtime"
        export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
        export RICEBOWL_DE_NESTED=1
        dbus-run-session -- sh -eu -c '
            root=$1; runtime=$2; native=$3; clicker=$4; rice=$5
            export WAYLAND_DISPLAY=wayland-0
            labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
                >"$runtime/labwc.log" 2>&1 &
            compositor=$!
            plate=; window=; keyboard=
            cleanup() {
                for pid in "$keyboard" "$window" "$plate" "$compositor"; do
                    if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || :; fi
                done
                for pid in "$keyboard" "$window" "$plate" "$compositor"; do
                    if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || :; fi
                done
            }
            trap cleanup EXIT
            tries=0
            while [ ! -S "$runtime/wayland-0" ] && [ "$tries" -lt 40 ]; do
                kill -0 "$compositor" 2>/dev/null || {
                    sed -n "1,60p" "$runtime/labwc.log" >&2; exit 1;
                }
                tries=$((tries+1)); sleep .25
            done
            test -S "$runtime/wayland-0" || { echo "No private Wayland socket" >&2; exit 1; }
            output=$(wlr-randr | sed -n "1s/[[:space:]].*//p")
            test -n "$output"
            wlr-randr --output "$output" --custom-mode 1024x768@60Hz --scale 1
            recipe=chrome; x=512
            if [ "$rice" = luna ]; then recipe="$runtime/luna.json"; x=240; fi
            RICEBOWL_DE_TRACE_WINDOWS=1 "$native" --recipe "$recipe" \
                >"$runtime/panel.log" 2>&1 &
            plate=$!
            sleep 1
            kill -0 "$plate"
            app_id=ricebowl-sg1-window-recovery
            RICEBOWL_WINDOW_RECEIPT="$runtime/typed.txt" foot \
                --app-id="$app_id" --title=SG1-Window-Focus \
                /bin/sh -c '\''IFS= read -r line || exit 1; if [ "$line" = sg1-focus-ok ]; then printf "%s" "$line" > "$RICEBOWL_WINDOW_RECEIPT"; fi; sleep 30'\'' \
                >"$runtime/foot.log" 2>&1 &
            window=$!
            state_since() {
                tail -n "+$1" "$runtime/panel.log" \
                    | grep -F "event=ready app_id=\"$app_id\"" | tail -n 1 || :
            }
            await_state() {
                first=$1; expected=$2; tries=0
                while [ "$tries" -lt 40 ]; do
                    case "$(state_since "$first")" in *"$expected"*) return 0;; esac
                    kill -0 "$window" 2>/dev/null || break
                    tries=$((tries+1)); sleep .25
                done
                echo "Missing actual compositor state: $rice / $expected" >&2
                tail -n 50 "$runtime/panel.log" >&2; return 1
            }
            await_state 1 "active=true minimized=false"
            # Verify a real compositor-confirmed round trip before the rapid case.
            begin=$(( $(wc -l < "$runtime/panel.log") + 1 ))
            "$clicker" "$x" 750 1024 768
            await_state "$begin" "minimized=true"
            begin=$(( $(wc -l < "$runtime/panel.log") + 1 ))
            "$clicker" "$x" 750 1024 768
            await_state "$begin" "active=true minimized=false"
            # Rapid opposite intentions without waiting for State/Done.
            begin=$(( $(wc -l < "$runtime/panel.log") + 1 ))
            "$clicker" "$x" 750 1024 768
            "$clicker" "$x" 750 1024 768
            tries=0
            while [ "$tries" -lt 40 ]; do
                tail -n "+$begin" "$runtime/panel.log" | grep -Fq "taskbar action=minimize app_id=\"$app_id\"" &&
                tail -n "+$begin" "$runtime/panel.log" | grep -Fq "taskbar action=restore app_id=\"$app_id\"" && break
                tries=$((tries+1)); sleep .25
            done
            [ "$tries" -lt 40 ] || { echo "Missing rapid taskbar action receipts" >&2; exit 1; }
            await_state "$begin" "active=true minimized=false"
            # The restored app must receive actual compositor keyboard input.
            (sleep .8; printf "%s" sg1-focus-ok) | timeout -k 3s 15s wtype - -k Return \
                >"$runtime/keyboard.log" 2>&1 &
            keyboard=$!
            wait "$keyboard" || { cat "$runtime/keyboard.log" >&2; exit 1; }
            keyboard=
            tries=0
            while [ ! -s "$runtime/typed.txt" ] && [ "$tries" -lt 40 ]; do
                tries=$((tries+1)); sleep .25
            done
            test "$(cat "$runtime/typed.txt" 2>/dev/null || :)" = sg1-focus-ok || {
                echo "Restored $rice window did not receive real keyboard input" >&2
                tail -n 50 "$runtime/panel.log" >&2; exit 1;
            }
            kill "$window"; wait "$window" 2>/dev/null || :; window=
            tries=0
            while ! grep -Fq "event=closed app_id=\"$app_id\"" "$runtime/panel.log"; do
                tries=$((tries+1)); [ "$tries" -lt 40 ] || {
                    echo "Closed window remained in compositor registry" >&2; exit 1;
                }
                sleep .25
            done
            kill -0 "$plate"
            echo "PASS SG1 $rice: real minimize/restore, rapid intents, keyboard focus, handle close"
        ' sh "$root" "$runtime" "$native" "$clicker" "$rice"
    ); then rc=0; else rc=$?; fi
    rm -rf -- "$runtime"
    [ "$rc" -eq 0 ] || exit "$rc"
done

#!/bin/sh
# SG7 WP7.2: longer HEADLESS resource/leak soak of riceplate-native and its
# session helpers. A headless local measurement on whatever machine runs it: it
# is NOT a hardware benchmark, not a cold-login figure and not wired into CI.
#
# For each rice, one after another, in its own disposable compositor + private
# D-Bus session (so one rice can never inherit another's state):
#   labwc (repo config) + real mako (shipped config) + swaybg (when the rice has
#   a wallpaper) + riceplate-native started with RICEBOWL_DE_NESTED=0 (the
#   full-session code path: status/audio watchers, OSD layer). The AT-SPI bridge
#   is opt-in (SOAK_ATSPI=1) because it is only on for screen-reader sessions.
# A Python sampler (scripts/soak_resource_sampler.py) reads, every
# SOAK_INTERVAL seconds, PSS (/proc/PID/smaps_rollup), RSS, utime+stime, threads
# and fds of riceplate-native, labwc, mako, swaybg, the private dbus-daemon and
# (when on) the AT-SPI helpers. Optionally (SOAK_INTERACT=1, default) a real
# driver repeats, every SOAK_INTERACT_EVERY seconds: launcher/Start menu open +
# key + Escape, calendar/clock popup, a tray popup served by the SG1 SNI
# fixture, a real notification into Mako, and a real foot window opened/closed
# (taskbar add/remove). The run timeline is
#   warmup (SOAK_WARMUP) | idle1 15% | interact 60% | idle2 25%     (of the rest)
# Idle CPU % comes only from the idle phases; slopes only from after warm-up.
#
# Environment (all optional):
#   SOAK_RICES          space list of: chrome luna heritage orbit   (chrome luna)
#   SOAK_DURATION       seconds per rice                            (600)
#   SOAK_INTERVAL       sample period in seconds                    (10)
#   SOAK_WARMUP         seconds excluded from slopes                (60)
#   SOAK_INTERACT       1 = drive interactions, 0 = pure idle       (1)
#   SOAK_INTERACT_EVERY seconds between interaction cycles          (15)
#   SOAK_ATSPI          1 = screen-reader (AT-SPI) mode             (0)
#   SOAK_CYCLE_PARTS    which interaction parts run per cycle, to isolate a
#                       suspect: controls notify window            (all three)
#   SOAK_OUT            output directory (must not exist or be empty)
#   SOAK_FAIL_ON_GROWTH 1 = exit 1 when a process is flagged GROWTH (1)
# Output per rice: <rice>.csv, <rice>.summary.json, <rice>.summary.txt,
# <rice>.meta.json; plus summary.txt for the whole run.
#
# Run unprivileged, e.g.:
#   dbus-run-session is started per rice by this script itself:
#   SOAK_DURATION=600 sh scripts/soak_riceplate_resources.sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
self="$root/scripts/soak_riceplate_resources.sh"
release="$root/components/riceplate-wayland/target/release"
native="$release/riceplate-native"
clicker="$release/examples/wayland_pointer_click"
sampler="$root/scripts/soak_resource_sampler.py"
provider="$root/scripts/fixtures/sg1_sni_provider.py"
setup="$root/scripts/sg4_imported_rices_setup.py"

: "${SOAK_RICES:=chrome luna}"
: "${SOAK_DURATION:=600}"
: "${SOAK_INTERVAL:=10}"
: "${SOAK_WARMUP:=60}"
: "${SOAK_INTERACT:=1}"
: "${SOAK_INTERACT_EVERY:=15}"
: "${SOAK_ATSPI:=0}"
: "${SOAK_FAIL_ON_GROWTH:=1}"
: "${SOAK_CYCLE_PARTS:=controls notify window}"
export SOAK_RICES SOAK_DURATION SOAK_INTERVAL SOAK_WARMUP SOAK_INTERACT SOAK_INTERACT_EVERY \
    SOAK_ATSPI SOAK_FAIL_ON_GROWTH SOAK_CYCLE_PARTS

if [ "${1:-}" != --inner ]; then
    [ "$(id -u)" -ne 0 ] || { echo "Run the soak as an unprivileged user" >&2; exit 2; }
    case $SOAK_DURATION$SOAK_INTERVAL$SOAK_WARMUP$SOAK_INTERACT_EVERY in
        *[!0-9]*|'') echo "SOAK_* durations must be whole seconds" >&2; exit 2 ;;
    esac
    [ "$SOAK_INTERVAL" -ge 1 ] && [ "$SOAK_DURATION" -ge $((SOAK_WARMUP + 4 * SOAK_INTERVAL)) ] || {
        echo "SOAK_DURATION must cover SOAK_WARMUP plus four samples" >&2; exit 2; }
    for rice in $SOAK_RICES; do
        case $rice in chrome|luna|heritage|orbit) : ;; *) echo "Unknown rice $rice" >&2; exit 2 ;; esac
    done
    for part in $SOAK_CYCLE_PARTS; do
        case $part in controls|notify|window) : ;; *) echo "Unknown SOAK_CYCLE_PARTS entry $part" >&2; exit 2 ;; esac
    done
    for command in dbus-run-session labwc mako wlr-randr wtype gdbus; do
        command -v "$command" >/dev/null || { echo "Missing $command" >&2; exit 77; }
    done
    if [ "$SOAK_INTERACT" = 1 ]; then
        for command in foot grim; do
            command -v "$command" >/dev/null || { echo "Missing $command" >&2; exit 77; }
        done
    fi
    test -x "$native" && test -x "$clicker" || {
        echo "Build riceplate-native and the wayland_pointer_click example first" >&2; exit 77; }
    /usr/bin/python3 -c 'import gi' >/dev/null 2>&1 || exit 77
    runtime=$(mktemp -d)
    chmod 0700 "$runtime"
    trap 'chmod -R u+rwx "$runtime" 2>/dev/null || :; rm -rf -- "$runtime"' EXIT
    out=${SOAK_OUT:-$(mktemp -d "${TMPDIR:-/tmp}/ricebowl-soak.XXXXXX")}
    mkdir -p "$out"
    [ -z "$(ls -A "$out")" ] || { echo "SOAK_OUT must be empty" >&2; exit 2; }
    mkdir -m 0700 "$runtime/config" "$runtime/state" "$runtime/home" "$runtime/run" \
        "$runtime/author-config" "$runtime/author-state" "$runtime/packs"
    export HOME="$runtime/home" XDG_CONFIG_HOME="$runtime/config" XDG_STATE_HOME="$runtime/state"
    export XDG_RUNTIME_DIR="$runtime/run"
    export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
    cp "$root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
    chmod 0600 "$runtime/luna.json"
    case " $SOAK_RICES " in *' heritage '*|*' orbit '*)
        # Imported through the real Creator/RicePack path (see WP4.3).
        XDG_CONFIG_HOME="$runtime/author-config" XDG_STATE_HOME="$runtime/author-state" \
            /usr/bin/python3 "$setup" author "$runtime/packs" >/dev/null
        /usr/bin/python3 "$setup" import "$runtime/packs" >"$runtime/imported.json" ;;
    esac
    export SOAK_RUNTIME="$runtime" SOAK_OUT_DIR="$out"
    echo "SOAK: headless local measurement; output in $out"
    echo "SOAK: rices=[$SOAK_RICES] duration=${SOAK_DURATION}s interval=${SOAK_INTERVAL}s" \
         "warmup=${SOAK_WARMUP}s interact=$SOAK_INTERACT every ${SOAK_INTERACT_EVERY}s atspi=$SOAK_ATSPI"
    : >"$out/summary.txt"
    status=0
    for rice in $SOAK_RICES; do
        if SOAK_RICE=$rice dbus-run-session -- sh "$self" --inner; then :; else
            echo "FAIL: soak of $rice failed" >&2; status=1; break
        fi
        {
            echo "== $rice (${SOAK_DURATION}s, headless local measurement, not a hardware benchmark)"
            cat "$out/$rice.summary.txt"
            echo
        } >>"$out/summary.txt"
        if grep -q GROWTH "$out/$rice.summary.txt" && [ "$SOAK_FAIL_ON_GROWTH" = 1 ]; then
            echo "FAIL: $rice shows monotonic memory growth (see $out/$rice.summary.txt)" >&2
            status=1
        fi
    done
    cat "$out/summary.txt"
    exit "$status"
fi

# ---------------------------------------------------------------------------
# Inner: private D-Bus session for ONE rice.
# ---------------------------------------------------------------------------
runtime=$SOAK_RUNTIME
out=$SOAK_OUT_DIR
rice=$SOAK_RICE
root_pid=$PPID
phase_file=$runtime/phase
stop_file=$runtime/stop
export WAYLAND_DISPLAY=wayland-0
W=1366 H=768
compositor= keeper= plate= mako_pid= bg_pid= sampler_pid= provider_pid= client=
cleanup() {
    for pid in "$client" "$provider_pid" "$sampler_pid" "$plate" "$bg_pid" "$mako_pid" "$keeper" "$compositor"; do
        [ -z "$pid" ] || kill "$pid" 2>/dev/null || :
    done
    for pid in "$client" "$provider_pid" "$sampler_pid" "$plate" "$bg_pid" "$mako_pid" "$keeper" "$compositor"; do
        [ -z "$pid" ] || wait "$pid" 2>/dev/null || :
    done
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
fail() { echo "FAIL [$rice]: $*" >&2; [ ! -s "$runtime/plate-$rice.log" ] || tail -n 20 "$runtime/plate-$rice.log" >&2; exit 1; }

rm -f "$phase_file" "$stop_file"
mkdir -m 0700 -p "$runtime/bin"
# Inert launchers: the soak measures RicePlate, never a real fuzzel/gio spawn.
for tool in fuzzel gio; do
    printf '#!/bin/sh\nexit 0\n' >"$runtime/bin/$tool"
    chmod 0700 "$runtime/bin/$tool"
done

labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
    >"$runtime/labwc-$rice.log" 2>&1 &
compositor=$!
n=0
while [ ! -S "$XDG_RUNTIME_DIR/wayland-0" ]; do
    n=$((n + 1)); [ "$n" -lt 80 ] || fail "no Wayland socket"
    kill -0 "$compositor" 2>/dev/null || fail "labwc died at startup"
    sleep .25
done
output=$(wlr-randr | sed -n '1s/[[:space:]].*//p')
wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1
sleep .3
wtype -k F13 -s 18000000 -k F13 >"$runtime/keeper.log" 2>&1 &
keeper=$!
sleep .4
kill -0 "$keeper" || fail "virtual keyboard did not attach"
if [ "$SOAK_ATSPI" = 1 ]; then
    /usr/bin/python3 -c 'import pyatspi; pyatspi.Registry.getDesktop(0).childCount' >/dev/null
    dbus-send --session --print-reply --reply-timeout=5000 --dest=org.a11y.Bus /org/a11y/bus \
        org.freedesktop.DBus.Properties.Set string:org.a11y.Status string:IsEnabled \
        variant:boolean:true >/dev/null
fi

case $rice in
    chrome) recipe=chrome ;;
    luna) recipe=$runtime/luna.json ;;
    heritage) recipe=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["rices"][0]["recipe_path"])' "$runtime/imported.json") ;;
    orbit) recipe=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["rices"][1]["recipe_path"])' "$runtime/imported.json") ;;
esac

# Session helpers, as the supervisor starts them: real Mako with the shipped
# config, and the wallpaper process when the rice has a wallpaper.
mako --config "$root/macrice/de/resources/mako.conf" >"$runtime/mako-$rice.log" 2>&1 &
mako_pid=$!
if command -v swaybg >/dev/null 2>&1; then
    wallpaper=$(PYTHONPATH="$root" /usr/bin/python3 - "$recipe" <<'PY' 2>/dev/null || :
import sys
from macrice.de import recipes
print(recipes.wallpaper_path(recipes.load(sys.argv[1])))
PY
)
    if [ -n "$wallpaper" ] && [ -f "$wallpaper" ]; then
        swaybg --image "$wallpaper" --mode fill >"$runtime/swaybg-$rice.log" 2>&1 &
        bg_pid=$!
    fi
fi
if [ "$SOAK_INTERACT" = 1 ] && { [ "$rice" = chrome ] || [ "$rice" = luna ]; }; then
    /usr/bin/python3 "$provider" --generation "soak-$rice" --receipts "$runtime/sni.jsonl" \
        --ready "$runtime/sni-ready-$rice" >"$runtime/sni-$rice.log" 2>&1 &
    provider_pid=$!
fi
sleep 1

atspi=0
[ "$SOAK_ATSPI" != 1 ] || atspi=1
PATH="$runtime/bin:$PATH" RICEBOWL_DE_NESTED=0 \
    RICEBOWL_DE_SCREEN_READER=$atspi "$native" --recipe "$recipe" \
    >"$runtime/plate-$rice.log" 2>&1 &
plate=$!
sleep 2
kill -0 "$plate" 2>/dev/null || fail "riceplate-native exited at startup"

echo warmup >"$phase_file"
/usr/bin/python3 "$sampler" sample --root-pid "$root_pid" --out "$out/$rice.csv" \
    --phase-file "$phase_file" --stop-file "$stop_file" --interval "$SOAK_INTERVAL" \
    >"$runtime/sampler-$rice.log" 2>&1 &
sampler_pid=$!

click() { "$clicker" "$1" "$2" "$W" "$H" >/dev/null 2>&1 || :; }
rclick() { "$clicker" --right-click "$1" "$2" "$W" "$H" >/dev/null 2>&1 || :; }
key() { wtype -k "$1" 2>/dev/null || :; }
# One real interaction cycle for the rice's own controls.
cycle_controls() {
    case $rice in
        chrome)
            rclick 1270 746; sleep .7; key Escape; sleep .4 ;;
        luna)
            click 35 748; sleep .7; key Down; sleep .2; key Down; sleep .2; key Escape; sleep .4
            click 1320 748; sleep .7; key Escape; sleep .4
            rclick 1320 748; sleep .7; key Escape; sleep .4
            rclick 1185 746; sleep .7; key Escape; sleep .4 ;;
        heritage)
            click 44 750; sleep .7; key Down; sleep .2; key Escape; sleep .4
            click 1275 750; sleep .7; key Escape; sleep .4 ;;
        orbit)
            click 312 28; sleep .7; key Down; sleep .2; key Escape; sleep .4
            click 1220 28; sleep .7; key Escape; sleep .4 ;;
    esac
}
cycle() {
    cycles=$((cycles + 1))
    for part in $SOAK_CYCLE_PARTS; do
        case $part in
            controls) cycle_controls ;;
            notify)
                # A real notification into Mako (expires on its own).
                gdbus call --session --dest org.freedesktop.Notifications \
                    --object-path /org/freedesktop/Notifications \
                    --method org.freedesktop.Notifications.Notify soak 0 "" "Soak" "cycle $cycles" \
                    '[]' '{}' 3000 >/dev/null 2>&1 || : ;;
            window)
                # A real toplevel appears in and disappears from the taskbar.
                foot --app-id=ricebowl-soak --title="soak-$cycles" sleep 30 >/dev/null 2>&1 &
                client=$!
                sleep 2.5
                kill "$client" 2>/dev/null || :
                wait "$client" 2>/dev/null || :
                client=
                sleep .8 ;;
        esac
    done
}

start=$(date +%s)
warm=$SOAK_WARMUP
rest=$((SOAK_DURATION - warm))
idle1_end=$((warm + rest * 15 / 100))
interact_end=$((idle1_end + rest * 60 / 100))
[ "$SOAK_INTERACT" = 1 ] || { idle1_end=$SOAK_DURATION; interact_end=$SOAK_DURATION; }
cycles=0
next_cycle=$warm
last_phase=
echo "SOAK [$rice]: started (warmup ${warm}s, idle1 until ${idle1_end}s, interact until ${interact_end}s)"
while :; do
    now=$(($(date +%s) - start))
    [ "$now" -lt "$SOAK_DURATION" ] || break
    kill -0 "$plate" 2>/dev/null || fail "riceplate-native died during the soak at ${now}s"
    kill -0 "$compositor" 2>/dev/null || fail "labwc died during the soak at ${now}s"
    if [ "$now" -lt "$warm" ]; then phase=warmup
    elif [ "$now" -lt "$idle1_end" ]; then phase=idle1
    elif [ "$now" -lt "$interact_end" ]; then phase=interact
    else phase=idle2; fi
    if [ "$phase" != "$last_phase" ]; then echo "$phase" >"$phase_file"; last_phase=$phase; fi
    if [ "$phase" = interact ] && [ "$now" -ge "$next_cycle" ]; then
        cycle
        next_cycle=$(($(date +%s) - start + SOAK_INTERACT_EVERY))
    else
        sleep 1
    fi
done
kill -0 "$plate" 2>/dev/null || fail "riceplate-native is not running at the end of the soak"
: >"$stop_file"
n=0
while kill -0 "$sampler_pid" 2>/dev/null && [ "$n" -lt $((SOAK_INTERVAL + 10)) ]; do
    n=$((n + 1)); sleep 1
done
wait "$sampler_pid" 2>/dev/null || :
sampler_pid=

/usr/bin/python3 "$sampler" summary --csv "$out/$rice.csv" --warmup "$warm" \
    --json "$out/$rice.summary.json" >"$out/$rice.summary.txt" || fail "no summary"
commit=$(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo unknown)
/usr/bin/python3 - "$out/$rice.meta.json" "$rice" "$cycles" "$commit" "$(labwc --version 2>&1 | head -n 1)" <<'PY'
import json, os, platform, sys, time
path, rice, cycles, commit, labwc = sys.argv[1:6]
json.dump({
    "kind": "headless local measurement; not a hardware benchmark",
    "rice": rice, "interaction_cycles": int(cycles), "commit": commit,
    "labwc": labwc, "kernel": platform.release(), "cpus": os.cpu_count(),
    "duration_s": int(os.environ["SOAK_DURATION"]), "interval_s": int(os.environ["SOAK_INTERVAL"]),
    "warmup_s": int(os.environ["SOAK_WARMUP"]), "interact": os.environ["SOAK_INTERACT"] == "1",
    "interact_every_s": int(os.environ["SOAK_INTERACT_EVERY"]),
    "cycle_parts": os.environ["SOAK_CYCLE_PARTS"].split(),
    "atspi": os.environ["SOAK_ATSPI"] == "1",
    "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}, open(path, "w"), indent=2, sort_keys=True)
PY
echo "SOAK [$rice]: done, $cycles interaction cycle(s)"

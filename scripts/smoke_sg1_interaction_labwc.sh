#!/bin/sh
# SG1 WP1.2/1.3/1.4/1.6/1.7 compositor receipts: real labwc, real RicePlate
# binary, real virtual pointer + wtype keyboard, grim pixels. Every negative
# path is genuine (permission-denied files, failing/absent providers, an
# external client that steals the keyboard). Disposable runtime only: never
# attaches to a logged-in session or touches host settings.
#
#   windows : compositor maximize/close and RicePlate restart (both rices)
#   launcher: Luna Start search busy/error/empty with a private `gio` shim
#   clock   : Luna clock menu provider absent/denied/failing + focus theft,
#             Chrome clock is read-only
#   sni     : secondary click on a Chrome (and Luna) tray item
#   files   : Luna Desktop files multi-select, permission denied, drag,
#             focus loss
# SG1I_STAGES selects a subset for development (default: all).
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$root/components/riceplate-wayland/target/release/riceplate-native"
clicker="$root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
probe="$root/components/riceplate-wayland/target/release/riceplate_focus_probe"
provider="$root/scripts/fixtures/sg1_sni_provider.py"
for command in dbus-run-session labwc wlr-randr wtype grim foot gdbus timeout ps; do
    command -v "$command" >/dev/null || { echo "Missing $command" >&2; exit 77; }
done
test -x "$native" && test -x "$clicker" && test -x "$probe" || {
    echo "Build riceplate-native, riceplate_focus_probe and wayland_pointer_click first" >&2
    exit 77
}
/usr/bin/python3 -c 'import gi; from gi.repository import Gio, GLib; from PIL import Image' || exit 77

if [ "${1:-}" != --inner ]; then
    runtime=$(mktemp -d)
    chmod 0700 "$runtime"
    # Restore write bits so the cleanup can remove read-only fixtures.
    trap 'chmod -R u+rwx "$runtime" 2>/dev/null || :; rm -rf -- "$runtime"' EXIT
    export XDG_RUNTIME_DIR="$runtime" SG1I_RUNTIME="$runtime"
    export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
    export RICEBOWL_DE_NESTED=1
    if dbus-run-session -- sh "$0" --inner; then rc=0; else rc=$?; fi
    exit "$rc"
fi

runtime=$SG1I_RUNTIME
stages=${SG1I_STAGES:-windows launcher clock sni files}
cp "$root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
chmod 0600 "$runtime/luna.json"
export XDG_CONFIG_HOME="$runtime/config"
mkdir -m 0700 "$XDG_CONFIG_HOME"

compositor= plate= keyboard_keeper= client= provider_pid= thief=
cleanup() {
    for pid in "$thief" "$provider_pid" "$client" "$plate" "$keyboard_keeper" "$compositor"; do
        [ -z "$pid" ] || kill "$pid" 2>/dev/null || :
    done
    for pid in "$thief" "$provider_pid" "$client" "$plate" "$keyboard_keeper" "$compositor"; do
        [ -z "$pid" ] || wait "$pid" 2>/dev/null || :
    done
}
trap cleanup EXIT
fail() {
    echo "FAIL: $*" >&2
    [ -z "${plate_log:-}" ] || tail -n 40 "$plate_log" >&2 || :
    # Development aid: SG1I_KEEP_DIR=<writable dir> keeps the frames and logs.
    [ -z "${SG1I_KEEP_DIR:-}" ] || cp "$runtime"/*.png "$runtime"/*.log "$SG1I_KEEP_DIR"/ 2>/dev/null || :
    exit 1
}

labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
    >"$runtime/labwc.log" 2>&1 &
compositor=$!
n=0
while [ ! -S "$runtime/wayland-0" ] && [ "$n" -lt 60 ]; do
    kill -0 "$compositor" || { cat "$runtime/labwc.log" >&2; exit 1; }
    n=$((n + 1)); sleep .2
done
[ -S "$runtime/wayland-0" ] || fail "no Wayland socket"
export WAYLAND_DISPLAY=wayland-0
output=$(wlr-randr | sed -n '1s/[[:space:]].*//p')
test -n "$output"
set_mode() { wlr-randr --output "$output" --custom-mode "$1@60Hz" --scale 1; sleep .3; }

# --- shared helpers --------------------------------------------------------
# wtype keeps one virtual keyboard per process; a lingering disconnected one
# stops layer-shell clients receiving wl_keyboard.enter (WP0.1), so attach a
# fresh self-expiring keyboard before each shell start.
renew_keyboard_seat() {
    if [ -n "$keyboard_keeper" ]; then
        kill "$keyboard_keeper" 2>/dev/null || :
        wait "$keyboard_keeper" 2>/dev/null || :
        keyboard_keeper=
    fi
    wtype -k F13 -s 1800000 -k F13 >"$runtime/keeper.log" 2>&1 &
    keyboard_keeper=$!
    sleep .4
    kill -0 "$keyboard_keeper" || fail "virtual keyboard did not attach"
}
# start_plate RECIPE LOG [VAR=value...]: real binary, windows/tray/focus traces.
start_plate() {
    recipe=$1; plate_log=$2; shift 2
    env RICEBOWL_DE_TRACE_WINDOWS=1 RICEBOWL_DE_TRACE_FOCUS=1 RICEBOWL_DE_TRACE_TRAY=1 \
        "$@" "$native" --recipe "$recipe" >"$plate_log" 2>&1 &
    plate=$!
    sleep 1
    kill -0 "$plate" || fail "RicePlate exited at start"
}
stop_plate() {
    [ -z "$plate" ] || { kill "$plate" 2>/dev/null || :; wait "$plate" 2>/dev/null || :; }
    plate=
}
# count_lines FILE PATTERN -> number (0 when file is absent)
count_lines() {
    n=$(grep -cF -- "$2" "$1" 2>/dev/null || :)
    echo "${n:-0}"
}
# wait_count FILE PATTERN MIN [TENTHS]: wait until at least MIN lines match.
wait_count() {
    tries=0
    while [ "$(count_lines "$1" "$2")" -lt "$3" ]; do
        tries=$((tries + 1))
        [ "$tries" -lt "${4:-40}" ] || return 1
        sleep .1
    done
}
# A process-private PATH of `gio`-free fixtures: PATH_SHIMS is prepended.
mkdir -m 0700 "$runtime/shims"

# =========================================================================
# WP1.2  taskbar/window actions: compositor maximize/close, RicePlate restart
# =========================================================================
win_client() {
    # A real foot window; SIGWINCH proves the compositor-side geometry.
    cat >"$runtime/win-client.sh" <<'CLIENT'
#!/bin/sh
trap 'stty size >>"$SG1I_SIZE_LOG"' WINCH
stty size >>"$SG1I_SIZE_LOG"
while :; do sleep 0.2; done
CLIENT
    chmod 0700 "$runtime/win-client.sh"
    : >"$runtime/size.log"
    SG1I_SIZE_LOG="$runtime/size.log" foot --app-id=ricebowl-sg1-int --title=SG1-Int \
        "$runtime/win-client.sh" >"$runtime/foot.log" 2>&1 &
    client=$!
}
last_size() { tail -n 1 "$runtime/size.log" 2>/dev/null || :; }
# wait_size_change OLD: wait until the last reported size differs from OLD,
# then until it is stable for 0.6 s.
wait_size_change() {
    tries=0
    while [ "$(last_size)" = "$1" ] || [ -z "$(last_size)" ]; do
        tries=$((tries + 1)); [ "$tries" -lt 50 ] || return 1; sleep .1
    done
    prev=
    while [ "$prev" != "$(last_size)" ]; do prev=$(last_size); sleep .6; done
}
wait_ready() {
    # wait_ready LOG FROM_LINE EXPECTED_TEXT
    tries=0
    while ! tail -n "+$2" "$1" | grep -F 'event=ready app_id="ricebowl-sg1-int"' \
        | tail -n 1 | grep -Fq "$3"; do
        tries=$((tries + 1)); [ "$tries" -lt 50 ] || return 1; sleep .1
    done
}
next_line() { echo $(( $(wc -l <"$1") + 1 )); }

stage_windows() {
    set_mode 1024x768
    for rice in chrome luna; do
        recipe=chrome x=512
        if [ "$rice" = luna ]; then recipe=$runtime/luna.json x=240; fi
        renew_keyboard_seat
        log=$runtime/plate-win-$rice.log
        start_plate "$recipe" "$log"
        win_client
        wait_ready "$log" 1 'active=true minimized=false' || fail "$rice: window never became active"
        wait_size_change '' || fail "$rice: window reported no size"
        initial=$(last_size)

        # Compositor-side maximize (labwc default W-a): the task survives,
        # stays active and the client geometry really grows.
        from=$(next_line "$log")
        wtype -M logo -k a -m logo
        wait_size_change "$initial" || fail "$rice: labwc did not maximize the window"
        maximized=$(last_size)
        [ "$maximized" != "$initial" ] || fail "$rice: maximize left the geometry unchanged"
        wait_ready "$log" "$from" 'active=true minimized=false' || fail "$rice: maximize lost the task state"
        grep -Fq 'event=closed' "$log" && fail "$rice: maximize removed the task"

        # Taskbar minimize + restore on a maximized window: real round trip,
        # and the maximized geometry is preserved (no spurious resize).
        from=$(next_line "$log")
        "$clicker" "$x" 750 1024 768 >/dev/null
        wait_ready "$log" "$from" 'minimized=true' || fail "$rice: taskbar did not minimize a maximized window"
        from=$(next_line "$log")
        "$clicker" "$x" 750 1024 768 >/dev/null
        wait_ready "$log" "$from" 'active=true minimized=false' || fail "$rice: taskbar did not restore a maximized window"
        sleep .5
        [ "$(last_size)" = "$maximized" ] || fail "$rice: restore changed the maximized geometry"

        # Un-maximize returns to the original size.
        wtype -M logo -k a -m logo
        wait_size_change "$maximized" || fail "$rice: labwc did not unmaximize"
        [ "$(last_size)" = "$initial" ] || fail "$rice: unmaximize did not restore the geometry"

        # Compositor-initiated close (labwc A-F4 -> xdg_toplevel.close):
        # RicePlate drops the task, the client exits, the shell lives.
        wtype -M alt -k F4 -m alt
        wait_count "$log" 'event=closed app_id="ricebowl-sg1-int"' 1 || fail "$rice: compositor close left a stale task"
        n=0
        while kill -0 "$client" 2>/dev/null && [ "$n" -lt 30 ]; do n=$((n + 1)); sleep .1; done
        ! kill -0 "$client" 2>/dev/null || fail "$rice: close request did not end the client"
        wait "$client" 2>/dev/null || :; client=
        kill -0 "$plate" || fail "$rice: RicePlate died on window close"
        echo "SG1 $rice: compositor maximize/unmaximize/close with real taskbar minimize+restore PASS"

        # Transient loss: SIGKILL RicePlate while the window is minimized.
        win_client
        wait_ready "$log" 1 'active=true minimized=false' || :
        sleep .6
        from=$(next_line "$log")
        "$clicker" "$x" 750 1024 768 >/dev/null
        wait_ready "$log" "$from" 'minimized=true' || fail "$rice: could not minimize before restart"
        kill -9 "$plate"; wait "$plate" 2>/dev/null || :; plate=
        # While the shell is gone the compositor keeps the window minimized.
        log2=$runtime/plate-win-$rice-restart.log
        renew_keyboard_seat
        start_plate "$recipe" "$log2"
        wait_ready "$log2" 1 'minimized=true' || fail "$rice: restarted shell did not read the minimized window state"
        from=$(next_line "$log2")
        "$clicker" "$x" 750 1024 768 >/dev/null
        wait_ready "$log2" "$from" 'active=true minimized=false' || fail "$rice: restarted shell could not restore the window"
        # A window that closes while the shell is down leaves no ghost.
        kill -9 "$plate"; wait "$plate" 2>/dev/null || :; plate=
        kill "$client"; wait "$client" 2>/dev/null || :; client=
        sleep .5
        log3=$runtime/plate-win-$rice-gone.log
        renew_keyboard_seat
        start_plate "$recipe" "$log3"
        sleep .8
        grep -Fq 'app_id="ricebowl-sg1-int"' "$log3" && fail "$rice: restarted shell shows a window that closed while it was down"
        # A new window with the same app id starts clean: one click minimizes,
        # no replay of the earlier intent.
        win_client
        wait_ready "$log3" 1 'active=true minimized=false' || fail "$rice: new same-id window not tracked"
        sleep .6
        from=$(next_line "$log3")
        "$clicker" "$x" 750 1024 768 >/dev/null
        wait_ready "$log3" "$from" 'minimized=true' || fail "$rice: stale intent blocked the first click"
        kill "$client"; wait "$client" 2>/dev/null || :; client=
        stop_plate
        echo "SG1 $rice: RicePlate SIGKILL/restart reads minimized state, restores, no ghost/stale intent PASS"
    done
}

# =========================================================================
# WP1.6  clock: Luna provider absent / denied / failing + keyboard theft,
#        Chrome clock is read-only
# =========================================================================
settings_shim() {
    # settings_shim MODE: ok | fail | denied | absent for `ricebowl`.
    rm -f "$runtime/shims/ricebowl"
    [ "$1" != absent ] || return 0
    cat >"$runtime/shims/ricebowl" <<'SHIM'
#!/bin/sh
{ printf 'call'; for a in "$@"; do printf ' %s' "$a"; done; printf '\n'; } >>"$SG1I_RICEBOWL_LOG"
[ ! -e "$SG1I_RICEBOWL_FAIL" ] || exit 3
exit 0
SHIM
    chmod 0700 "$runtime/shims/ricebowl"
    case $1 in
        denied) chmod 0600 "$runtime/shims/ricebowl";;
        fail) : >"$runtime/ricebowl.fail";;
        ok) rm -f "$runtime/ricebowl.fail";;
    esac
}
zombie_children() {
    # Provoke event-loop wakes so the bounded reaper may run, then list Z.
    "$clicker" --move-only 600 300 1366 768 >/dev/null; sleep 2.3
    "$clicker" --move-only 610 310 1366 768 >/dev/null; sleep .4
    ps -o stat= --ppid "$plate" | grep -c '^Z' || :
}
luna_clock_menu_open() {
    seen=$(count_lines "$plate_log" 'compositor confirmed tray popup keyboard focus')
    "$clicker" --right-click 1320 748 1366 768 >/dev/null
    wait_count "$plate_log" 'compositor confirmed tray popup keyboard focus' $((seen + 1)) 30 \
        || fail "Luna clock menu did not receive compositor keyboard focus"
}
popup_changed() {
    # popup_changed BASELINE.png NEW.png -> number of changed popup pixels
    /usr/bin/python3 - "$1" "$2" <<'PY'
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as a, Image.open(sys.argv[2]) as b:
    d = ImageChops.difference(a.convert("RGB").crop((1070, 480, 1358, 720)),
                              b.convert("RGB").crop((1070, 480, 1358, 720)))
    print(sum(max(p) > 20 for p in d.getdata()))
PY
}
stage_clock() {
    set_mode 1366x768
    export SG1I_RICEBOWL_LOG="$runtime/ricebowl.log" SG1I_RICEBOWL_FAIL="$runtime/ricebowl.fail"
    rm -f "$SG1I_RICEBOWL_LOG" "$SG1I_RICEBOWL_FAIL"
    log=$runtime/plate-clock-luna.log
    settings_shim absent
    renew_keyboard_seat
    # PATH holds only the private shim directory, so `absent` cannot fall
    # through to a real ricebowl installed on the host.
    start_plate "$runtime/luna.json" "$log" "PATH=$runtime/shims"
    grim "$runtime/clock-closed.png"
    # 1. provider unavailable: the menu action reports ENOENT, runs nothing.
    luna_clock_menu_open
    wtype -k Return
    wait_count "$log" 'cannot open Luna settings page timezone: No such file' 1 30 \
        || fail "absent settings provider was not reported"
    [ ! -e "$SG1I_RICEBOWL_LOG" ] || fail "absent provider somehow ran"
    # 2. provider denied (present but not executable).
    settings_shim denied
    luna_clock_menu_open
    wtype -k Return
    wait_count "$log" 'cannot open Luna settings page timezone: Permission denied' 1 30 \
        || fail "denied settings provider was not reported"
    [ ! -e "$SG1I_RICEBOWL_LOG" ] || fail "non-executable provider ran"
    kill -0 "$plate" || fail "RicePlate died on a denied provider"
    # No stale action: with the menu closed again, a bare Return reaches nothing.
    wtype -k Return; sleep .3
    [ ! -e "$SG1I_RICEBOWL_LOG" ] || fail "stale clock action dispatched after an error"
    # 3. provider starts but fails (exit 3): exactly one exact-argv call, the
    # shell survives and does not replay it.
    settings_shim fail
    luna_clock_menu_open
    wtype -k Return
    wait_count "$SG1I_RICEBOWL_LOG" 'call de settings --luna --page timezone' 1 30 \
        || fail "failing provider was not invoked"
    sleep .5
    [ "$(count_lines "$SG1I_RICEBOWL_LOG" 'call ')" = 1 ] || fail "failing provider was replayed"
    [ "$(zombie_children)" = 0 ] || fail "finished settings helper left a zombie child"
    # 4. focus loss: an external exclusive layer takes the keyboard while the
    # clock menu is open. The menu closes, typed keys reach only the thief.
    settings_shim ok
    renew_keyboard_seat
    luna_clock_menu_open
    grim "$runtime/clock-open.png"
    [ "$(popup_changed "$runtime/clock-closed.png" "$runtime/clock-open.png")" -gt 2000 ] \
        || fail "Luna clock menu did not open"
    "$probe" overlay exclusive >"$runtime/clock-thief.log" 2>&1 &
    thief=$!
    wait_count "$runtime/clock-thief.log" 'event=keyboard_enter' 1 50 \
        || fail "external client never took keyboard focus from the clock menu"
    sleep .3
    grim "$runtime/clock-stolen.png"
    [ "$(popup_changed "$runtime/clock-closed.png" "$runtime/clock-stolen.png")" -lt 50 ] \
        || fail "clock menu stayed open after keyboard focus loss"
    wtype -k Return -s 150 -k Return; sleep .3
    wait_count "$runtime/clock-thief.log" 'event=keyboard_press' 1 20 \
        || fail "keys typed after focus loss did not reach the new focus owner"
    [ "$(count_lines "$SG1I_RICEBOWL_LOG" 'call ')" = 1 ] || fail "keys typed into the thief reached the clock menu"
    wtype -k Escape
    n=0; while kill -0 "$thief" 2>/dev/null && [ "$n" -lt 30 ]; do n=$((n + 1)); sleep .1; done
    wait "$thief" 2>/dev/null || :; thief=
    sleep .3
    [ "$(count_lines "$SG1I_RICEBOWL_LOG" 'call ')" = 1 ] || fail "thief exit dispatched a stale clock action"
    # 5. recovery: fresh open + Return dispatches exactly once.
    renew_keyboard_seat
    luna_clock_menu_open
    wtype -k Return
    wait_count "$SG1I_RICEBOWL_LOG" 'call de settings --luna --page timezone' 2 30 \
        || fail "clock menu did not recover after focus loss"
    sleep .4
    [ "$(count_lines "$SG1I_RICEBOWL_LOG" 'call ')" = 2 ] || fail "recovery dispatched more than once"
    kill -0 "$plate" || fail "RicePlate died"
    stop_plate
    echo "SG1 luna: clock absent/denied/failing provider, no stale action, no zombie, focus theft, recovery PASS"

    # Chrome: the clock is a read-only widget. No click, left or right,
    # anywhere along the end section reaches a settings provider.
    rm -f "$SG1I_RICEBOWL_LOG"
    log=$runtime/plate-clock-chrome.log
    renew_keyboard_seat
    start_plate chrome "$log" "PATH=$runtime/shims"
    x=1100
    while [ "$x" -lt 1366 ]; do
        "$clicker" "$x" 746 1366 768 >/dev/null
        "$clicker" --right-click "$x" 746 1366 768 >/dev/null
        x=$((x + 22))
    done
    sleep .5
    [ ! -e "$SG1I_RICEBOWL_LOG" ] || fail "a Chrome end-section click dispatched a provider call"
    kill -0 "$plate" || fail "Chrome died on clock clicks"
    stop_plate
    echo "SG1 chrome: read-only clock/end section reaches no settings provider PASS"
}

# =========================================================================
# WP1.4  Luna Start search: busy / error / empty / stale action. The Chrome
# launcher (absent, crashing, busy, empty, Escape) is covered by
# smoke_riceplate_native.sh; a private `gio` shim records every launch.
# =========================================================================
stage_launcher() {
    set_mode 1366x768
    mkdir -m 0700 "$runtime/data" "$runtime/data/applications"
    export XDG_DATA_HOME="$runtime/data"
    cat >"$XDG_DATA_HOME/applications/ricebowl-sg1-int.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=RiceBowl SG1 Interaction
Keywords=sg1witness;
Exec=$runtime/never-run
Terminal=false
EOF
    chmod 0600 "$XDG_DATA_HOME/applications/ricebowl-sg1-int.desktop"
    export SG1I_GIO_LOG="$runtime/gio.log" SG1I_GIO_MODE="$runtime/gio.mode"
    rm -f "$SG1I_GIO_LOG"
    cat >"$runtime/shims/gio" <<'SHIM'
#!/bin/sh
printf 'gio %s\n' "$*" >>"$SG1I_GIO_LOG"
case $(cat "$SG1I_GIO_MODE") in
    slow) sleep 2;;
    fail) echo 'gio: injected failure' >&2; exit 1;;
esac
exit 0
SHIM
    chmod 0700 "$runtime/shims/gio"
    log=$runtime/plate-launcher-luna.log
    renew_keyboard_seat
    start_plate "$runtime/luna.json" "$log" "PATH=$runtime/shims:$PATH"
    # Only this entry is counted: an idle Start menu legitimately activates its
    # own highlighted row, which must never be the failed entry.
    gio_calls() { count_lines "$SG1I_GIO_LOG" 'ricebowl-sg1-int.desktop'; }
    search() {
        "$clicker" 35 748 1366 768 >/dev/null; sleep .3
        wtype -k slash -d 50 "$1" -s 350 -k Return
    }
    close_start() { wtype -k Escape -k Escape; sleep .2; }
    # 1. busy: a slow helper is pending; each user gesture still maps to exactly
    # one launch (no drop, no duplicate, no replay when the helper ends).
    echo slow >"$SG1I_GIO_MODE"
    search sg1witness
    wait_count "$SG1I_GIO_LOG" 'ricebowl-sg1-int.desktop' 1 30 || fail "slow launch never reached gio"
    search sg1witness
    wait_count "$SG1I_GIO_LOG" 'ricebowl-sg1-int.desktop' 2 30 || fail "second launch while the first helper was pending was dropped"
    sleep 3
    [ "$(gio_calls)" = 2 ] || fail "pending helpers replayed a launch: $(gio_calls)"
    grep -Fq 'launch failed' "$log" && fail "slow but successful helper reported as failed"
    close_start
    # 2. error: helper exits 1 -> reported, withdrawn.
    echo fail >"$SG1I_GIO_MODE"
    search sg1witness
    wait_count "$log" 'desktop application launch failed (desktop:ricebowl-sg1-int.desktop)' 1 40 \
        || fail "failing helper was not reported"
    [ "$(gio_calls)" = 3 ] || fail "failing launch dispatched $(gio_calls) gio calls"
    close_start
    # 3. empty result + Return, then an empty Start + Return: nothing launches
    # (the failed entry must not linger as a stale recent/selected action).
    search zzz-no-such-ricebowl-app
    sleep .6
    [ "$(gio_calls)" = 3 ] || fail "empty search result launched something"
    close_start
    "$clicker" 35 748 1366 768 >/dev/null; sleep .4
    wtype -k Return; sleep .6
    [ "$(gio_calls)" = 3 ] || fail "Return on an idle Start menu replayed the failed entry"
    close_start
    # 4. recovery: working helper launches once more.
    echo ok >"$SG1I_GIO_MODE"
    search sg1witness
    wait_count "$SG1I_GIO_LOG" 'ricebowl-sg1-int.desktop' 4 30 || fail "launcher did not recover after the error"
    sleep .5
    [ "$(gio_calls)" = 4 ] || fail "recovery launched more than once"
    close_start
    kill -0 "$plate" || fail "RicePlate died"
    stop_plate
    rm -f "$runtime/shims/gio"
    echo "SG1 luna: Start search busy/error/empty/stale-action/recovery with exact gio receipts PASS"
}

# =========================================================================
# WP1.7  SNI secondary click end to end (Chrome, Luna for parity): a
# secondary press on an open menu row never activates it, an invalid
# (emptied) menu never falls back to ContextMenu, a plain item's
# ContextMenu reaches the provider once and a provider error is survived.
# =========================================================================
rcount() {
    # rcount GENERATION EVENT [FIELD VALUE] -> matching receipt count
    /usr/bin/python3 - "$runtime/receipts.jsonl" "$@" <<'PY'
import json, sys
path, gen, event, *rest = sys.argv[1:]
try:
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
except FileNotFoundError:
    rows = []
want = dict(zip(rest[::2], rest[1::2]))
print(sum(1 for r in rows if r["generation"] == gen and r["event"] == event
          and all(str(r.get(k)) == v for k, v in want.items())))
PY
}
fixture_mode() {
    gdbus call --session --dest org.ricebowl.SNIFixture --object-path /Control \
        --method org.ricebowl.SNIFixtureControl.SetMode "$1" >/dev/null
}
start_provider() {
    # start_provider GENERATION [--plain]
    gen=$1; shift
    rm -f "$runtime/ready-$gen"
    /usr/bin/python3 "$provider" --generation "$gen" --receipts "$runtime/receipts.jsonl" \
        --ready "$runtime/ready-$gen" "$@" >"$runtime/provider-$gen.log" 2>&1 &
    provider_pid=$!
    wait_file "$runtime/ready-$gen" || fail "SNI provider $gen never registered"
}
stop_provider() {
    [ -z "$provider_pid" ] || { kill "$provider_pid" 2>/dev/null || :; wait "$provider_pid" 2>/dev/null || :; }
    provider_pid=
    sleep .4
}
wait_file() {
    tries=0
    while [ ! -s "$1" ]; do tries=$((tries + 1)); [ "$tries" -lt 80 ] || return 1; sleep .15; done
}
popup_region_changed() {
    # popup_region_changed BASELINE NEW -> changed pixels above the panel
    /usr/bin/python3 - "$1" "$2" <<'PY'
from PIL import Image, ImageChops
import sys
box = (1070, 470, 1358, 712)
with Image.open(sys.argv[1]) as a, Image.open(sys.argv[2]) as b:
    d = ImageChops.difference(a.convert("RGB").crop(box), b.convert("RGB").crop(box))
    print(sum(max(p) > 20 for p in d.getdata()))
PY
}
stage_sni() {
    set_mode 1366x768
    rm -f "$runtime/receipts.jsonl"
    for rice in chrome luna; do
        recipe=chrome tray_x=1270
        if [ "$rice" = luna ]; then recipe=$runtime/luna.json tray_x=1185; fi
        log=$runtime/plate-sni-$rice.log
        renew_keyboard_seat
        start_plate "$recipe" "$log"
        grim "$runtime/sni-closed-$rice.png"
        secondary() { "$clicker" --right-click "$tray_x" 746 1366 768 >/dev/null; }
        # ---- A. valid menu: secondary presses on its rows activate nothing.
        gen=$rice-menu
        start_provider "$gen"
        wait_count "$log" 'RicePlate: SNI DBusMenu snapshot ready' 1 80 || fail "$rice: no DBusMenu snapshot"
        seen=$(count_lines "$log" 'compositor confirmed tray popup keyboard focus')
        secondary
        wait_count "$log" 'compositor confirmed tray popup keyboard focus' $((seen + 1)) 40 \
            || fail "$rice: secondary click did not open the native menu"
        for y in 545 575 605; do "$clicker" --right-click 1200 "$y" 1366 768 >/dev/null; sleep .15; done
        sleep .3
        [ "$(rcount "$gen" menu-event action clicked)" = 0 ] || fail "$rice: a secondary press activated a menu row"
        [ "$(rcount "$gen" menu-event action closed)" = 0 ] || fail "$rice: a secondary press on a row dismissed the menu"
        # Positive control: the very same row coordinates, pressed with the
        # PRIMARY button, activate "Provider action" (id 10) exactly once, so
        # the secondary presses above really landed on live rows of an open menu.
        "$clicker" 1200 575 1366 768 >/dev/null
        tries=0
        while [ "$(rcount "$gen" menu-event action clicked id 10)" -lt 1 ] && [ "$tries" -lt 30 ]; do tries=$((tries + 1)); sleep .1; done
        [ "$(rcount "$gen" menu-event action clicked id 10)" = 1 ] || fail "$rice: primary press on the same row did not activate it once"
        sleep .3
        wtype -k Escape
        clicked_a=$(rcount "$gen" menu-event action clicked)
        [ "$(rcount "$gen" item)" = 0 ] || fail "$rice: secondary click fell back to a provider item method"
        # ---- B. invalid menu (provider emptied it): no popup, no fallback.
        before=$(rcount "$gen" layout mode empty)
        fixture_mode empty
        tries=0
        while [ "$(rcount "$gen" layout mode empty)" -le "$before" ] && [ "$tries" -lt 40 ]; do tries=$((tries + 1)); sleep .1; done
        sleep .3
        secondary; sleep .5
        grim "$runtime/sni-invalid-$rice.png"
        [ "$(popup_region_changed "$runtime/sni-closed-$rice.png" "$runtime/sni-invalid-$rice.png")" -lt 200 ] \
            || fail "$rice: an emptied menu still painted a popup on secondary click"
        "$clicker" "$tray_x" 746 1366 768 >/dev/null; sleep .5
        grim "$runtime/sni-invalid-left-$rice.png"
        [ "$(popup_region_changed "$runtime/sni-closed-$rice.png" "$runtime/sni-invalid-left-$rice.png")" -lt 200 ] \
            || fail "$rice: an emptied menu still painted a popup on primary click"
        [ "$(rcount "$gen" item)" = 0 ] || fail "$rice: invalid menu fell back to ContextMenu/Activate"
        [ "$(rcount "$gen" menu-event action clicked)" = "$clicked_a" ] || fail "$rice: invalid menu dispatched an action"
        kill -0 "$plate" || fail "$rice: RicePlate died"
        stop_provider
        # ---- C. plain item (no menu): ContextMenu reaches the owner once;
        # an owner error is survived; the next click works again.
        gen=$rice-plain
        start_provider "$gen" --plain
        sleep .8
        secondary
        wait_count "$runtime/receipts.jsonl" "\"generation\": \"$gen\"" 1 40 || :
        tries=0
        while [ "$(rcount "$gen" item method ContextMenu)" -lt 1 ] && [ "$tries" -lt 40 ]; do tries=$((tries + 1)); sleep .1; done
        [ "$(rcount "$gen" item method ContextMenu)" = 1 ] || fail "$rice: secondary click did not reach ContextMenu exactly once"
        [ "$(rcount "$gen" item method Activate)" = 0 ] || fail "$rice: secondary click called Activate"
        coords=$(/usr/bin/python3 - "$runtime/receipts.jsonl" "$gen" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
r = [x for x in rows if x["generation"] == sys.argv[2] and x["event"] == "item"][0]
print(r["coords"][0], r["coords"][1])
PY
)
        set -- $coords
        [ "$1" -ge 1000 ] && [ "$2" -ge 700 ] || fail "$rice: ContextMenu coordinates $coords are not at the tray icon"
        fixture_mode item-error
        sleep .3
        errors=$(count_lines "$log" 'RicePlate: SNI item error: error while calling an item method')
        secondary
        wait_count "$log" 'RicePlate: SNI item error: error while calling an item method' $((errors + 1)) 40 \
            || fail "$rice: provider ContextMenu error was not reported"
        [ "$(rcount "$gen" item method ContextMenu)" = 2 ] || fail "$rice: failing ContextMenu was replayed"
        kill -0 "$plate" || fail "$rice: RicePlate died on a provider error"
        fixture_mode normal
        sleep .3
        secondary
        tries=0
        while [ "$(rcount "$gen" item method ContextMenu)" -lt 3 ] && [ "$tries" -lt 40 ]; do tries=$((tries + 1)); sleep .1; done
        [ "$(rcount "$gen" item method ContextMenu)" = 3 ] || fail "$rice: ContextMenu did not recover after the provider error"
        sleep .4
        [ "$(rcount "$gen" item method ContextMenu)" = 3 ] || fail "$rice: recovered ContextMenu dispatched twice"
        stop_provider
        stop_plate
        echo "SG1 $rice: SNI secondary click rows/invalid-menu/ContextMenu/provider-error receipts PASS"
    done
}

# =========================================================================
# WP1.3  Luna Desktop files (Chrome has no desktop block): keyboard
# multi-select, permission-denied open / rename / drag-persist / new folder,
# keyboard focus loss and recovery, all on real native file-icon layers.
# =========================================================================
region_changed() {
    # region_changed A B X Y W H -> changed pixels in the box
    /usr/bin/python3 - "$@" <<'PY'
from PIL import Image, ImageChops
import sys
a, b, x, y, w, h = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:7])
with Image.open(a) as p, Image.open(b) as q:
    d = ImageChops.difference(p.convert("RGB").crop((x, y, x + w, y + h)),
                              q.convert("RGB").crop((x, y, x + w, y + h)))
    print(sum(max(v) > 20 for v in d.getdata()))
PY
}
stage_files() {
    [ "$(id -u)" != 0 ] || { echo "files stage needs a non-root user for permission-denied receipts" >&2; return 0; }
    set_mode 1366x768
    fh=$runtime/file-home fc=$runtime/file-config
    mkdir -m 0700 "$fh" "$fh/Desktop" "$fc" "$fc/ricebowl"
    printf '%s\n' 'XDG_DESKTOP_DIR="$HOME/Desktop"' >"$fc/user-dirs.dirs"
    for name in 00-alpha 01-bravo 02-charlie 03-secret; do
        printf '%s\n' "$name" >"$fh/Desktop/$name.txt"
    done
    chmod 0000 "$fh/Desktop/03-secret.txt"
    export SG1I_GIO_LOG="$runtime/files-gio.log" SG1I_GIO_MODE="$runtime/files-gio.mode"
    rm -f "$SG1I_GIO_LOG"; echo ok >"$SG1I_GIO_MODE"
    cat >"$runtime/shims/gio" <<'SHIM'
#!/bin/sh
printf 'gio %s\n' "$*" >>"$SG1I_GIO_LOG"
exit 0
SHIM
    chmod 0700 "$runtime/shims/gio"
    log=$runtime/plate-files.log
    renew_keyboard_seat
    start_plate "$runtime/luna.json" "$log" "HOME=$fh" "XDG_CONFIG_HOME=$fc" \
        RICEBOWL_DE_NESTED=0 RICEBOWL_DE_TRACE_FILES=1 "PATH=$runtime/shims:$PATH"
    wait_count "$log" 'RicePlate: XDG mapped' 4 50 || fail "four Desktop file layers were not mapped"
    # Icon i is the i-th mapped file layer (inventory order is by name).
    pos() { sed -n 's/.*XDG mapped x=\([0-9]*\) y=\([0-9]*\) kind=File.*/\1 \2/p' "$log" | sed -n "$(($1 + 1))p"; }
    icon_x() { set -- $(pos "$1"); echo "$1"; }
    icon_y() { set -- $(pos "$1"); echo "$1" >/dev/null; echo "$2"; }
    center_click() { "$clicker" "$(( $(icon_x "$1") + 52 ))" "$(( $(icon_y "$1") + 43 ))" 1366 768 >/dev/null; }
    away() { "$clicker" --move-only 1100 450 1366 768 >/dev/null; sleep .2; }
    icon_diff() { region_changed "$1" "$2" "$(icon_x "$3")" "$(icon_y "$3")" 104 88; }
    wait_focus() { wait_count "$log" 'compositor confirmed XDG file keyboard focus' "$1" 30; }
    focus_n() { count_lines "$log" 'compositor confirmed XDG file keyboard focus'; }
    away; grim "$runtime/files-base.png"

    # ---- 1. multi-select: pointer picks the anchor, Shift+Down extends it.
    n=$(focus_n)
    center_click 0
    wait_focus $((n + 1)) || fail "file icon click did not obtain compositor keyboard focus"
    wtype -M shift -k Down -s 150 -k Down -m shift
    sleep .4; away
    grim "$runtime/files-multi.png"
    for i in 0 1 2; do
        [ "$(icon_diff "$runtime/files-base.png" "$runtime/files-multi.png" $i)" -gt 150 ] \
            || fail "icon $i is not painted selected after Shift+Down range selection"
    done
    [ "$(icon_diff "$runtime/files-base.png" "$runtime/files-multi.png" 3)" -lt 40 ] \
        || fail "icon 3 outside the range was painted selected"
    wtype -k Escape; sleep .3
    echo "SG1 luna files: real click + Shift+Down multi-select paints exactly the 3-icon range"

    # ---- 2. permission denied on open: an unreadable file never reaches Gio.
    away
    center_click 3; sleep .15; center_click 3
    wait_count "$log" 'desktop file activation refused' 1 30 || fail "unreadable file open was not refused"
    sleep .3
    [ ! -e "$SG1I_GIO_LOG" ] || fail "unreadable file reached the opener"
    # positive control: a readable file double-click opens exactly once.
    center_click 0; sleep .15; center_click 0
    tries=0; while [ ! -s "$SG1I_GIO_LOG" ] && [ "$tries" -lt 30 ]; do tries=$((tries + 1)); sleep .1; done
    [ "$(count_lines "$SG1I_GIO_LOG" "gio open $fh/Desktop/00-alpha.txt")" = 1 ] \
        || fail "readable file double-click did not open exactly once"
    echo "SG1 luna files: chmod 000 file open refused (no opener call); readable file opens once"

    # ---- 3. drag with an unwritable position store: the icon snaps back.
    chmod 0500 "$fc/ricebowl"
    # Reference frame = the icon selected in place (a press selects it).
    center_click 2; away; grim "$runtime/files-before-drag.png"
    sx=$(( $(icon_x 2) + 52 )); sy=$(( $(icon_y 2) + 43 ))
    "$clicker" --drag-to $((sx + 173)) $((sy + 79)) "$sx" "$sy" 1366 768 >/dev/null
    wait_count "$log" 'XDG position save refused, restoring previous layout' 1 30 \
        || fail "failed position save was not reported"
    sleep .5; away; grim "$runtime/files-after-failed-drag.png"
    [ "$(region_changed "$runtime/files-before-drag.png" "$runtime/files-after-failed-drag.png" 0 0 900 700)" -lt 150 ] \
        || fail "icon did not return to its original place after the failed save"
    [ ! -e "$fc/ricebowl/native-file-positions.json" ] || fail "denied store was written"
    chmod 0700 "$fc/ricebowl"
    "$clicker" --drag-to $((sx + 173)) $((sy + 79)) "$sx" "$sy" 1366 768 >/dev/null
    tries=0; while [ ! -s "$fc/ricebowl/native-file-positions.json" ] && [ "$tries" -lt 30 ]; do tries=$((tries + 1)); sleep .1; done
    [ -s "$fc/ricebowl/native-file-positions.json" ] || fail "drag did not persist once the store was writable"
    sleep .4; away; grim "$runtime/files-after-drag.png"
    [ "$(region_changed "$runtime/files-before-drag.png" "$runtime/files-after-drag.png" 0 0 900 700)" -gt 200 ] \
        || fail "successful drag did not move the icon"
    echo "SG1 luna files: drag with denied position store restored, then persisted after recovery"

    # ---- 4. keyboard focus loss: an exclusive external client takes the
    # keyboard while an icon holds the focus lease. F2/Delete reach only it.
    away; grim "$runtime/files-idle.png"
    renew_keyboard_seat   # a stale disconnected wtype keyboard starves layer clients (WP0.1)
    n=$(focus_n); released=$(count_lines "$log" 'XDG file keyboard focus released')
    center_click 0
    wait_focus $((n + 1)) || fail "no focus lease before the theft"
    "$probe" overlay exclusive >"$runtime/files-thief.log" 2>&1 &
    thief=$!
    wait_count "$runtime/files-thief.log" 'event=keyboard_enter' 1 50 || fail "external client never took the keyboard"
    wait_count "$log" 'XDG file keyboard focus released' $((released + 1)) 30 || fail "desktop kept its focus lease after the theft"
    wtype -k F2 -s 150 -k Delete -s 150 -k Return; sleep .4
    wait_count "$runtime/files-thief.log" 'event=keyboard_press' 1 20 || fail "keys after the theft did not reach the new focus owner"
    grim "$runtime/files-stolen.png"
    [ "$(region_changed "$runtime/files-idle.png" "$runtime/files-stolen.png" 500 360 380 130)" -lt 100 ] \
        || fail "a dialog opened from keys typed into the focus thief"
    wtype -k Escape
    n2=0; while kill -0 "$thief" 2>/dev/null && [ "$n2" -lt 30 ]; do n2=$((n2 + 1)); sleep .1; done
    wait "$thief" 2>/dev/null || :; thief=
    sleep .3
    wtype -k Delete; sleep .4
    grim "$runtime/files-after-thief.png"
    [ "$(region_changed "$runtime/files-idle.png" "$runtime/files-after-thief.png" 500 360 380 130)" -lt 100 ] \
        || fail "a stale Delete opened a dialog after focus loss"
    [ "$(count_lines "$SG1I_GIO_LOG" 'gio trash')" = 0 ] || fail "stale Delete reached the trash helper"
    # recovery: a fresh click regains the lease; F2 opens Rename.
    renew_keyboard_seat
    n=$(focus_n)
    center_click 0
    wait_focus $((n + 1)) || fail "desktop did not regain keyboard focus after the theft"
    wtype -k F2; sleep .5
    grim "$runtime/files-rename-open.png"
    [ "$(region_changed "$runtime/files-idle.png" "$runtime/files-rename-open.png" 500 360 380 130)" -gt 800 ] \
        || fail "Rename dialog did not open after focus recovery"
    wtype -k Escape; sleep .4
    echo "SG1 luna files: focus theft revokes the lease, no stale F2/Delete, fresh click recovers"

    # ---- 5. rename inside a read-only Desktop: refused, visible, no change.
    away
    chmod 0500 "$fh/Desktop"
    renew_keyboard_seat
    n=$(focus_n)
    center_click 1
    wait_focus $((n + 1)) || fail "no focus lease for rename"
    wtype -k F2; sleep .5
    wtype -d 110 -k F13 -k F13 -k Home "QA-"; sleep .4
    grim "$runtime/files-rename-typed.png"
    wtype -k Return
    wait_count "$log" 'XDG confirmed action refused' 1 30 || fail "rename in a read-only Desktop was not refused"
    sleep .4
    [ -e "$fh/Desktop/01-bravo.txt" ] && [ ! -e "$fh/Desktop/QA-01-bravo.txt" ] \
        || fail "denied rename changed the Desktop"
    grim "$runtime/files-rename-denied.png"
    [ "$(region_changed "$runtime/files-idle.png" "$runtime/files-rename-denied.png" 500 360 380 130)" -gt 800 ] \
        || fail "the refusal is not visible: the Rename dialog is gone"
    # The dialog stays open and now carries the error notice ("Operation
    # failed; check permissions"): its pixels differ from the typed frame.
    [ "$(region_changed "$runtime/files-rename-typed.png" "$runtime/files-rename-denied.png" 459 268 448 232)" -gt 40 ] \
        || fail "the rename refusal left no visible notice in the dialog"
    wtype -k Escape; sleep .3
    chmod 0700 "$fh/Desktop"
    renew_keyboard_seat
    n=$(focus_n)
    center_click 1
    wait_focus $((n + 1)) || fail "no focus lease for recovery rename"
    wtype -k F2; sleep .5
    wtype -d 110 -k F13 -k F13 -k Home "QA-" -k Return
    tries=0; while [ ! -e "$fh/Desktop/QA-01-bravo.txt" ] && [ "$tries" -lt 30 ]; do tries=$((tries + 1)); sleep .1; done
    [ -e "$fh/Desktop/QA-01-bravo.txt" ] && [ ! -e "$fh/Desktop/01-bravo.txt" ] \
        || fail "rename did not recover once the Desktop was writable"
    echo "SG1 luna files: rename refused with visible dialog error in a read-only Desktop, recovers"

    # ---- 6. New Folder IPC in a read-only Desktop: refused, no phantom icon.
    sleep .8
    chmod 0500 "$fh/Desktop"
    HOME=$fh XDG_CONFIG_HOME=$fc RICEBOWL_DE_NESTED=0 "$native" --desktop-command new-folder
    wait_count "$log" 'RicePlate: cannot create Desktop folder:' 1 30 || fail "denied New Folder was not reported"
    [ ! -e "$fh/Desktop/New Folder" ] || fail "denied New Folder created a directory"
    chmod 0700 "$fh/Desktop"
    HOME=$fh XDG_CONFIG_HOME=$fc RICEBOWL_DE_NESTED=0 "$native" --desktop-command new-folder
    wait_count "$log" 'RicePlate: XDG created folder selected on native desktop' 1 40 || fail "New Folder did not recover"
    [ -d "$fh/Desktop/New Folder" ] || fail "recovered New Folder is missing"
    kill -0 "$plate" || fail "RicePlate died"
    stop_plate
    rm -f "$runtime/shims/gio"
    echo "SG1 luna files: New Folder denied in a read-only Desktop, then recovers PASS"
}

run_stage() {
    case " $stages " in *" $1 "*) "stage_$1";; esac
}
for s in windows launcher clock sni files; do run_stage "$s"; done
echo "PASS smoke_sg1_interaction_labwc ($stages)"

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
#   notices : failures that happen after their control closed (launcher, Settings
#             provider, tray provider) reach the user as a visible, AT-SPI-
#             exposed, self-clearing notice (both rices)
#   outputs : output scale change, hot-unplug/re-plug and hot-add while the Luna
#             Start menu, a tray popup, the calendar, the Run dialog and a
#             desktop context menu are open (own two-output compositor; last)
# SG1I_STAGES selects a subset for development (default: all, `outputs` last).
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
/usr/bin/python3 -c 'import gi; from gi.repository import Gio, GLib; from PIL import Image; import pyatspi' || exit 77

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
stages=${SG1I_STAGES:-windows launcher clock sni notices files outputs}
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
# The AT-SPI bridge of a shell started with RICEBOWL_DE_SCREEN_READER=1 waits
# for org.a11y.Status.IsEnabled; this disposable private bus emulates a screen
# reader turning accessibility on (never touches a host session bus).
/usr/bin/python3 -c 'import pyatspi; pyatspi.Registry.getDesktop(0).childCount' >/dev/null
dbus-send --session --print-reply --reply-timeout=5000 --dest=org.a11y.Bus /org/a11y/bus \
    org.freedesktop.DBus.Properties.Set string:org.a11y.Status string:IsEnabled \
    variant:boolean:true >/dev/null || { echo "could not enable accessibility" >&2; exit 1; }
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
# Failure notices: an operation that fails AFTER its control closed (a launcher,
# a provider helper, a tray provider) is shown on the shared transient notice
# surface (top-right overlay) and exposed as an AT-SPI alert, then clears on
# its own (or on Escape from the focused panel). Generic text only; nothing
# is replayed. Shells run as a full session (RICEBOWL_DE_NESTED=0) on an
# isolated HOME with an empty Desktop so no host file is ever inspected.
# =========================================================================
notice_probe() { timeout -k 2s 25s /usr/bin/python3 "$root/scripts/sg1_notice_probe.py" "$@"; }
# The notice is the 248x70 overlay at the top right of a 1366-wide output.
notice_changed() { region_changed "$1" "$2" 1102 16 248 70; }
notice_accent() {
    /usr/bin/python3 - "$1" <<'PY'
from PIL import Image
import sys
with Image.open(sys.argv[1]) as im:
    bar = im.convert("RGB").crop((1102, 16, 1106, 86))
    print(sum(1 for p in bar.getdata() if p == (178, 48, 46)))
PY
}
# expect_notice "Exact text" BASELINE.png: painted (error accent) AND exposed
# to AT-SPI as exactly one alert with that accessible name.
expect_notice() {
    tries=0
    while :; do
        grim "$runtime/notice-now.png"
        [ "$(notice_changed "$2" "$runtime/notice-now.png")" -gt 400 ] && break
        tries=$((tries + 1)); [ "$tries" -lt 25 ] || fail "notice '$1' was never painted"
        sleep .2
    done
    [ "$(notice_accent "$runtime/notice-now.png")" -ge 200 ] || fail "notice '$1' lacks the error accent"
    notice_probe present "$1" 6 >/dev/null || fail "notice '$1' is not exposed to AT-SPI"
}
# expect_notice_clears BASELINE.png: pixels back to the baseline AND no alert.
expect_notice_clears() {
    tries=0
    while :; do
        grim "$runtime/notice-gone.png"
        [ "$(notice_changed "$1" "$runtime/notice-gone.png")" -lt 30 ] && break
        tries=$((tries + 1)); [ "$tries" -lt 40 ] || fail "failure notice did not clear"
        sleep .25
    done
    notice_probe absent 6 >/dev/null || fail "an AT-SPI alert outlived the painted notice"
}
# expect_no_notice BASELINE.png [SECONDS]: nothing painted and no alert
# (positive control for a successful operation).
expect_no_notice() {
    sleep "${2:-1.6}"
    grim "$runtime/notice-none.png"
    [ "$(notice_changed "$1" "$runtime/notice-none.png")" -lt 30 ] || fail "a notice was painted for a successful operation"
    notice_probe absent 4 >/dev/null || fail "an alert was exposed for a successful operation"
}
notice_home() {
    nh=$runtime/notice-home nc=$runtime/notice-config
    [ -d "$nh" ] || {
        mkdir -m 0700 "$nh" "$nh/Desktop" "$nc" "$nc/ricebowl"
        printf '%s\n' 'XDG_DESKTOP_DIR="$HOME/Desktop"' >"$nc/user-dirs.dirs"
    }
}
# start_full RECIPE LOG [VAR=value...]: full session + AT-SPI bridge on an
# isolated HOME (an empty Desktop).
start_full() {
    notice_home
    recipe=$1; flog=$2; shift 2
    start_plate "$recipe" "$flog" "HOME=$nh" "XDG_CONFIG_HOME=$nc" \
        RICEBOWL_DE_NESTED=0 RICEBOWL_DE_SCREEN_READER=1 "$@"
    sleep 1.5   # the AT-SPI tree registers a moment after the first frame
}
start_search() {
    "$clicker" 35 748 1366 768 >/dev/null; sleep .3
    wtype -k slash -d 50 "$1" -s 350 -k Return
}
stage_notices() {
    set_mode 1366x768
    notice_home
    mkdir -m 0700 "$runtime/data-n" "$runtime/data-n/applications" "$runtime/emptybin"
    cat >"$runtime/data-n/applications/ricebowl-sg1-notice.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=RiceBowl SG1 Notice
Keywords=sg1notice;
Exec=$runtime/never-run-notice
Terminal=false
DESKTOP
    chmod 0600 "$runtime/data-n/applications/ricebowl-sg1-notice.desktop"
    export XDG_DATA_HOME="$runtime/data-n"
    export SG1I_GIO_LOG="$runtime/notice-gio.log" SG1I_GIO_MODE="$runtime/notice-gio.mode"
    export SG1I_RICEBOWL_LOG="$runtime/notice-ricebowl.log" SG1I_RICEBOWL_FAIL="$runtime/ricebowl.fail"
    rm -f "$SG1I_GIO_LOG" "$SG1I_RICEBOWL_LOG" "$SG1I_RICEBOWL_FAIL"
    echo ok >"$SG1I_GIO_MODE"
    cat >"$runtime/shims/gio" <<'SHIM'
#!/bin/sh
printf 'gio %s\n' "$*" >>"$SG1I_GIO_LOG"
case $(cat "$SG1I_GIO_MODE") in
    fail) echo 'gio: injected failure' >&2; exit 1;;
esac
exit 0
SHIM
    chmod 0700 "$runtime/shims/gio"
    settings_shim ok
    gio_calls() { count_lines "$SG1I_GIO_LOG" 'sg1-notice.desktop'; }

    # ---- Luna with working-but-failing helpers on a private PATH -----------
    log=$runtime/plate-notice-luna.log
    renew_keyboard_seat
    start_full "$runtime/luna.json" "$log" "PATH=$runtime/shims:$PATH"
    grim "$runtime/notice-base-luna.png"
    notice_probe absent 4 >/dev/null || fail "luna: an alert is exposed before any failure"
    # 1. App launch failure: the Start menu already closed; the helper exits 1.
    echo ok >"$SG1I_GIO_MODE"
    start_search sg1notice
    wait_count "$SG1I_GIO_LOG" 'sg1-notice.desktop' 1 30 || fail "luna: working launch never reached gio"
    expect_no_notice "$runtime/notice-base-luna.png"
    echo fail >"$SG1I_GIO_MODE"
    start_search sg1notice
    wait_count "$log" 'desktop application launch failed (desktop:ricebowl-sg1-notice.desktop)' 1 40 \
        || fail "luna: failing launch was not reported in the log"
    expect_notice 'Application: Could not start' "$runtime/notice-base-luna.png"
    # No stale action: keys after the failure replay nothing.
    wtype -k Return; sleep .5
    [ "$(gio_calls)" = 2 ] || fail "luna: a launch was replayed after the failure ($(gio_calls))"
    expect_notice_clears "$runtime/notice-base-luna.png"
    echo ok >"$SG1I_GIO_MODE"
    # 2. Settings provider (clock menu) fails after the menu closed (exit 3).
    settings_shim fail
    luna_clock_menu_open
    wtype -k Return
    wait_count "$SG1I_RICEBOWL_LOG" 'call de settings --luna --page timezone' 1 30 || fail "luna: failing settings provider not invoked"
    expect_notice 'Settings: Could not open' "$runtime/notice-base-luna.png"
    [ "$(count_lines "$SG1I_RICEBOWL_LOG" 'call ')" = 1 ] || fail "luna: failing settings provider was replayed"
    # Escape on the focused panel dismisses the notice at once (no replay).
    seen=$(count_lines "$log" 'compositor confirmed panel keyboard focus')
    "$clicker" 700 748 1366 768 >/dev/null
    wait_count "$log" 'compositor confirmed panel keyboard focus' $((seen + 1)) 30 \
        || fail "luna: the panel did not take keyboard focus"
    wtype -k Escape; sleep .6
    grim "$runtime/notice-esc.png"
    [ "$(notice_changed "$runtime/notice-base-luna.png" "$runtime/notice-esc.png")" -lt 30 ] \
        || fail "luna: Escape did not dismiss the failure notice"
    notice_probe absent 3 >/dev/null || fail "luna: the dismissed notice is still an AT-SPI alert"
    [ "$(count_lines "$SG1I_RICEBOWL_LOG" 'call ')" = 1 ] || fail "luna: Escape replayed the failed provider"
    # Recovery: a working provider shows no notice and runs once.
    settings_shim ok
    renew_keyboard_seat
    luna_clock_menu_open
    wtype -k Return
    wait_count "$SG1I_RICEBOWL_LOG" 'call de settings --luna --page timezone' 2 30 || fail "luna: settings did not recover"
    expect_no_notice "$runtime/notice-base-luna.png"
    # 3. Run dialog: a missing or non-executable program keeps the dialog open
    # with a visible notice and starts nothing; a valid one runs exactly once.
    cat >"$runtime/run-ok" <<WITNESS
#!/bin/sh
echo ran >>"$runtime/run-ok.log"
WITNESS
    chmod 0700 "$runtime/run-ok"
    printf '#!/bin/sh\necho ran >>"%s/run-denied.log"\n' "$runtime" >"$runtime/run-denied"
    chmod 0600 "$runtime/run-denied"
    rm -f "$runtime/run-ok.log" "$runtime/run-denied.log"
    renew_keyboard_seat
    "$clicker" 35 748 1366 768 >/dev/null; sleep .7
    "$clicker" 316 580 1366 768 >/dev/null; sleep .8
    grim "$runtime/notice-run-open.png"
    [ "$(region_changed "$runtime/notice-base-luna.png" "$runtime/notice-run-open.png" 459 268 448 232)" -gt 800 ] \
        || fail "luna: the Run dialog did not open"
    for target in "$runtime/no-such-ricebowl-program" "$runtime/run-denied"; do
        wtype -M ctrl -k a -m ctrl -s 120 -d 30 "$target"; sleep .4
        grim "$runtime/notice-run-typed.png"
        wtype -k Return; sleep .6
        grim "$runtime/notice-run-refused.png"
        [ "$(region_changed "$runtime/notice-run-typed.png" "$runtime/notice-run-refused.png" 459 268 448 232)" -gt 40 ] \
            || fail "luna: a missing/non-executable Run program left no visible notice"
        [ "$(region_changed "$runtime/notice-base-luna.png" "$runtime/notice-run-refused.png" 459 268 448 232)" -gt 800 ] \
            || fail "luna: the Run dialog closed although the program could not start"
    done
    [ ! -e "$runtime/run-denied.log" ] || fail "luna: a non-executable program ran"
    wtype -M ctrl -k a -m ctrl -s 120 -d 30 "$runtime/run-ok" -s 150 -k Return
    tries=0; while [ ! -s "$runtime/run-ok.log" ] && [ "$tries" -lt 30 ]; do tries=$((tries + 1)); sleep .1; done
    sleep .6
    [ "$(wc -l <"$runtime/run-ok.log" 2>/dev/null || echo 0)" = 1 ] || fail "luna: Run did not recover (exactly one run expected)"
    grim "$runtime/notice-run-done.png"
    [ "$(region_changed "$runtime/notice-base-luna.png" "$runtime/notice-run-done.png" 459 268 448 232)" -lt 100 ] \
        || fail "luna: the Run dialog stayed open after a successful run"
    kill -0 "$plate" || fail "luna: RicePlate died"
    stop_plate
    echo "SG1 luna: failed app launch and failed Settings provider show a generic pixel + AT-SPI alert notice, Escape dismisses, no replay; Run keeps its dialog with a visible notice for a missing/denied program and runs a valid one once PASS"

    # ---- Luna with providers absent (spawn error): same notice -------------
    log=$runtime/plate-notice-luna-absent.log
    renew_keyboard_seat
    start_full "$runtime/luna.json" "$log" "PATH=$runtime/emptybin"
    grim "$runtime/notice-base-luna2.png"
    luna_clock_menu_open
    wtype -k Return
    wait_count "$log" 'cannot open Luna settings page timezone: No such file' 1 30 || fail "luna: absent provider not logged"
    expect_notice 'Settings: Could not open' "$runtime/notice-base-luna2.png"
    expect_notice_clears "$runtime/notice-base-luna2.png"
    start_search sg1notice
    wait_count "$log" 'cannot launch desktop application: No such file' 1 30 || fail "luna: absent gio not logged"
    expect_notice 'Application: Could not start' "$runtime/notice-base-luna2.png"
    expect_notice_clears "$runtime/notice-base-luna2.png"
    kill -0 "$plate" || fail "luna: RicePlate died"
    stop_plate
    echo "SG1 luna: absent Settings provider and absent gio show the notice and clear PASS"

    # ---- Chrome: external launcher absent ---------------------------------
    log=$runtime/plate-notice-chrome.log
    renew_keyboard_seat
    start_full chrome "$log" "PATH=$runtime/emptybin"
    grim "$runtime/notice-base-chrome.png"
    "$clicker" 28 746 1366 768 >/dev/null
    wait_count "$log" 'cannot open application launcher: No such file' 1 30 || fail "chrome: absent launcher not logged"
    expect_notice 'Launcher: Not available' "$runtime/notice-base-chrome.png"
    expect_notice_clears "$runtime/notice-base-chrome.png"
    # Repeat click: a fresh attempt and a fresh notice (never "busy").
    "$clicker" 28 746 1366 768 >/dev/null
    expect_notice 'Launcher: Not available' "$runtime/notice-base-chrome.png"
    expect_notice_clears "$runtime/notice-base-chrome.png"
    kill -0 "$plate" || fail "chrome: RicePlate died"
    stop_plate
    echo "SG1 chrome: absent external launcher shows the notice, clears, repeat click retries PASS"

    # ---- Tray provider error (both rices) -----------------------------------
    rm -f "$runtime/receipts.jsonl"
    for rice in luna chrome; do
        recipe=chrome tray_x=1270
        if [ "$rice" = luna ]; then recipe=$runtime/luna.json tray_x=1185; fi
        log=$runtime/plate-notice-tray-$rice.log
        renew_keyboard_seat
        start_full "$recipe" "$log"
        gen=$rice-notice
        start_provider "$gen" --plain
        sleep .8
        grim "$runtime/notice-base-tray-$rice.png"
        fixture_mode item-error
        sleep .3
        errors=$(count_lines "$log" 'RicePlate: SNI item error: error while calling an item method')
        "$clicker" --right-click "$tray_x" 746 1366 768 >/dev/null
        wait_count "$log" 'RicePlate: SNI item error: error while calling an item method' $((errors + 1)) 40 \
            || fail "$rice: provider ContextMenu error was not logged"
        expect_notice 'Tray: App did not respond' "$runtime/notice-base-tray-$rice.png"
        [ "$(rcount "$gen" item method ContextMenu)" = 1 ] || fail "$rice: failing ContextMenu was replayed"
        expect_notice_clears "$runtime/notice-base-tray-$rice.png"
        fixture_mode normal
        sleep .3
        "$clicker" --right-click "$tray_x" 746 1366 768 >/dev/null
        tries=0
        while [ "$(rcount "$gen" item method ContextMenu)" -lt 2 ] && [ "$tries" -lt 40 ]; do tries=$((tries + 1)); sleep .1; done
        [ "$(rcount "$gen" item method ContextMenu)" = 2 ] || fail "$rice: tray did not recover after the provider error"
        expect_no_notice "$runtime/notice-base-tray-$rice.png"
        stop_provider
        kill -0 "$plate" || fail "$rice: RicePlate died on a provider error"
        stop_plate
        echo "SG1 $rice: tray provider error shows the notice, clears, next click recovers with no new notice PASS"
    done
    rm -f "$runtime/shims/gio" "$runtime/shims/ricebowl"
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
    # `gio trash` is recorded only (the Desktop stays unchanged); modes: ok,
    # fail (exit 1) and slow (a helper that is still running for 2.5 s).
    cat >"$runtime/shims/gio" <<'SHIM'
#!/bin/sh
printf 'gio %s\n' "$*" >>"$SG1I_GIO_LOG"
if [ "$1" = trash ]; then
    case $(cat "$SG1I_GIO_MODE") in
        fail) echo 'gio: injected failure' >&2; exit 1;;
        slow) sleep 2.5;;
    esac
fi
exit 0
SHIM
    chmod 0700 "$runtime/shims/gio"
    log=$runtime/plate-files.log
    renew_keyboard_seat
    start_plate "$runtime/luna.json" "$log" "HOME=$fh" "XDG_CONFIG_HOME=$fc" \
        RICEBOWL_DE_NESTED=0 RICEBOWL_DE_SCREEN_READER=1 RICEBOWL_DE_TRACE_FILES=1 "PATH=$runtime/shims:$PATH"
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
    ix0=$(icon_x 0) iy0=$(icon_y 0)

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

    # ---- 1b. pointer + Ctrl/Shift. A pointer press carries no modifier state
    # in Wayland: the shell learns Ctrl/Shift only as wl_keyboard.modifiers
    # while the keyboard focus lease taken by the PRECEDING click is held. So a
    # modified click works once a first click has taken the lease, and only one
    # modified click per lease (a press closes it, the next lease starts clean).
    hold_modifier() { wtype -M "$1" -s 2200 -m "$1" >/dev/null 2>&1 & modifier_pid=$!; sleep .7; }
    sel() { [ "$(icon_diff "$runtime/files-base.png" "$1" "$2")" -gt 150 ]; }
    unsel() { [ "$(icon_diff "$runtime/files-base.png" "$1" "$2")" -lt 60 ]; }
    away; renew_keyboard_seat
    n=$(focus_n); center_click 1
    wait_focus $((n + 1)) || fail "no focus lease for the Ctrl+click check"
    hold_modifier ctrl
    center_click 0; sleep .5
    wait "$modifier_pid" 2>/dev/null || :; away; grim "$runtime/files-ctrl-a.png"
    sel "$runtime/files-ctrl-a.png" 0 && sel "$runtime/files-ctrl-a.png" 1 \
        && unsel "$runtime/files-ctrl-a.png" 2 && unsel "$runtime/files-ctrl-a.png" 3 \
        || fail "pointer Ctrl+click did not add a second icon to the selection"
    # Ctrl+click on a selected icon removes it: the first (plain) click selects
    # and takes the lease, the modified click comes after the double-click window.
    renew_keyboard_seat
    n=$(focus_n); center_click 1
    wait_focus $((n + 1)) || fail "no focus lease for the toggle-off check"
    grim "$runtime/files-ctrl-b0.png"
    sel "$runtime/files-ctrl-b0.png" 1 || fail "the plain click did not select icon 1"
    sleep 1.2
    hold_modifier ctrl
    center_click 1; sleep .5
    wait "$modifier_pid" 2>/dev/null || :; away; grim "$runtime/files-ctrl-b.png"
    unsel "$runtime/files-ctrl-b.png" 1 \
        || fail "pointer Ctrl+click on a selected icon did not remove it"
    renew_keyboard_seat
    n=$(focus_n); center_click 0
    wait_focus $((n + 1)) || fail "no focus lease for the Shift+click check"
    hold_modifier shift
    center_click 2; sleep .5
    wait "$modifier_pid" 2>/dev/null || :; away; grim "$runtime/files-shift.png"
    sel "$runtime/files-shift.png" 0 && sel "$runtime/files-shift.png" 1 && sel "$runtime/files-shift.png" 2 \
        && unsel "$runtime/files-shift.png" 3 \
        || fail "pointer Shift+click did not select the 0..2 range"
    wtype -k Escape; sleep .3
    echo "SG1 luna files: pointer Ctrl+click adds/removes and Shift+click selects a range (modifiers via the lease's wl_keyboard.modifiers) PASS"

    # ---- 2. permission denied on open: an unreadable file never reaches Gio.
    away
    center_click 3; sleep .15; center_click 3
    wait_count "$log" 'desktop file activation refused' 1 30 || fail "unreadable file open was not refused"
    # The refusal is visible and announced, not only a log line.
    expect_notice 'Desktop: Could not open item' "$runtime/files-base.png"
    [ ! -e "$SG1I_GIO_LOG" ] || fail "unreadable file reached the opener"
    expect_notice_clears "$runtime/files-base.png"
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

    # ---- 4b. `gio trash` after the confirmation dialog closed. A failing
    # helper is a visible, announced notice (the dialog is gone), a second
    # confirmed operation while one is in flight is refused (never queued or
    # duplicated) and the retry works afterwards.
    trash_calls() { count_lines "$SG1I_GIO_LOG" 'gio trash'; }
    trash_dialog_open() {
        away; renew_keyboard_seat
        n=$(focus_n)
        center_click "$1"
        wait_focus $((n + 1)) || fail "no focus lease for the Trash dialog"
        wtype -k Delete; sleep .6
        grim "$runtime/files-trash-dialog.png"
        [ "$(region_changed "$runtime/files-idle.png" "$runtime/files-trash-dialog.png" 500 360 380 130)" -gt 800 ] \
            || fail "the Move to Recycle Bin confirmation did not open"
    }
    echo fail >"$SG1I_GIO_MODE"
    trash_dialog_open 0
    wtype -k Return
    wait_count "$SG1I_GIO_LOG" 'gio trash' 1 30 || fail "confirmed Trash never reached the helper"
    expect_notice 'Recycle Bin: Could not move item' "$runtime/files-base.png"
    [ -f "$fh/Desktop/00-alpha.txt" ] || fail "failed Trash lost the file"
    [ "$(region_changed "$runtime/files-idle.png" "$runtime/notice-now.png" 500 360 380 130)" -lt 100 ] \
        || fail "the confirmation dialog was still open after the helper failed"
    wtype -k Return; sleep .5
    [ "$(trash_calls)" = 1 ] || fail "a stale Return replayed the failed Trash ($(trash_calls))"
    expect_notice_clears "$runtime/files-base.png"
    echo slow >"$SG1I_GIO_MODE"
    trash_dialog_open 0
    wtype -k Return
    wait_count "$SG1I_GIO_LOG" 'gio trash' 2 30 || fail "slow Trash never reached the helper"
    trash_dialog_open 1
    wtype -k Return; sleep .7
    [ "$(trash_calls)" = 2 ] || fail "a second Trash while one was in flight reached the helper ($(trash_calls))"
    grim "$runtime/files-trash-busy.png"
    [ "$(region_changed "$runtime/files-trash-dialog.png" "$runtime/files-trash-busy.png" 459 268 448 232)" -gt 40 ] \
        || fail "the refused second Trash left no visible busy notice in its dialog"
    wtype -k Escape; sleep .4
    sleep 3
    [ "$(trash_calls)" = 2 ] || fail "the refused Trash was queued and replayed ($(trash_calls))"
    expect_no_notice "$runtime/files-base.png" .3
    echo ok >"$SG1I_GIO_MODE"
    trash_dialog_open 1
    wtype -k Return
    wait_count "$SG1I_GIO_LOG" 'gio trash' 3 30 || fail "Trash did not recover once the first helper finished"
    sleep .6
    [ "$(trash_calls)" = 3 ] || fail "recovered Trash dispatched more than once ($(trash_calls))"
    expect_no_notice "$runtime/files-base.png" .3
    echo "SG1 luna files: failed gio trash shows a generic alert notice after the dialog closed; a second Trash while one is in flight is refused (no duplicate), retry works PASS"

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
    expect_notice 'Desktop: Could not create folder' "$runtime/files-base.png"
    [ ! -e "$fh/Desktop/New Folder" ] || fail "denied New Folder created a directory"
    expect_notice_clears "$runtime/files-base.png"
    chmod 0700 "$fh/Desktop"
    HOME=$fh XDG_CONFIG_HOME=$fc RICEBOWL_DE_NESTED=0 "$native" --desktop-command new-folder
    wait_count "$log" 'RicePlate: XDG created folder selected on native desktop' 1 40 || fail "New Folder did not recover"
    [ -d "$fh/Desktop/New Folder" ] || fail "recovered New Folder is missing"
    echo "SG1 luna files: New Folder denied in a read-only Desktop (visible notice), then recovers PASS"

    # ---- 6b. busy: two New Folder requests back to back. They are served one
    # after the other on the event loop: exactly one folder per request, none
    # overwritten and none created twice.
    sleep .8
    folders() { find "$fh/Desktop" -maxdepth 1 -type d -name 'New Folder*' | wc -l; }
    [ "$(folders)" = 1 ] || fail "unexpected folders before the back-to-back requests"
    HOME=$fh XDG_CONFIG_HOME=$fc RICEBOWL_DE_NESTED=0 "$native" --desktop-command new-folder &
    first=$!
    HOME=$fh XDG_CONFIG_HOME=$fc RICEBOWL_DE_NESTED=0 "$native" --desktop-command new-folder &
    second=$!
    wait "$first" "$second" 2>/dev/null || :
    tries=0; while [ "$(folders)" -lt 3 ] && [ "$tries" -lt 40 ]; do tries=$((tries + 1)); sleep .1; done
    sleep .8
    [ "$(folders)" = 3 ] || fail "two back-to-back New Folder requests made $(( $(folders) - 1 )) folders, expected exactly 2"
    [ -d "$fh/Desktop/New Folder (2)" ] && [ -d "$fh/Desktop/New Folder (3)" ] \
        || fail "back-to-back New Folder requests did not get distinct names"
    kill -0 "$plate" || fail "RicePlate died"
    echo "SG1 luna files: two back-to-back New Folder requests make exactly two distinct folders (queued, never duplicated) PASS"

    # ---- 7. empty Desktop: renders with no file icon, the keyboard does
    # nothing (no phantom Rename/Trash/open) and a file that appears later is
    # picked up.
    stop_plate
    eh=$runtime/empty-home ec=$runtime/empty-config
    mkdir -m 0700 "$eh" "$eh/Desktop" "$ec" "$ec/ricebowl"
    printf '%s\n' 'XDG_DESKTOP_DIR="$HOME/Desktop"' >"$ec/user-dirs.dirs"
    : >"$SG1I_GIO_LOG"
    elog=$runtime/plate-files-empty.log
    renew_keyboard_seat
    start_plate "$runtime/luna.json" "$elog" "HOME=$eh" "XDG_CONFIG_HOME=$ec" \
        RICEBOWL_DE_NESTED=0 RICEBOWL_DE_SCREEN_READER=1 RICEBOWL_DE_TRACE_FILES=1 "PATH=$runtime/shims:$PATH"
    sleep 1.5
    [ "$(count_lines "$elog" 'XDG mapped')" = 0 ] || fail "an empty Desktop mapped a file icon"
    away; grim "$runtime/files-empty.png"
    [ "$(region_changed "$runtime/files-base.png" "$runtime/files-empty.png" "$ix0" "$iy0" 104 88)" -gt 150 ] \
        || fail "the empty Desktop still shows the first file icon"
    # With a keyboard lease on a recipe shortcut (the only icon left to
    # select) the file keys have no file to act on: no Rename/Trash dialog and
    # no opener or trash helper call.
    "$clicker" 75 120 1366 768 >/dev/null; sleep .8
    wtype -k F2 -s 150 -k Delete -s 150 -M ctrl -k a -m ctrl -s 150 -k Escape; sleep .6
    away; grim "$runtime/files-empty-keys.png"
    [ "$(region_changed "$runtime/files-empty.png" "$runtime/files-empty-keys.png" 440 250 500 280)" -lt 100 ] \
        || fail "keys on an empty Desktop opened a phantom dialog"
    [ ! -s "$SG1I_GIO_LOG" ] || fail "keys on an empty Desktop reached an opener or the trash helper"
    kill -0 "$plate" || fail "RicePlate died on an empty Desktop"
    printf '%s\n' late >"$eh/Desktop/10-late.txt"
    wait_count "$elog" 'XDG mapped' 1 50 || fail "a file added to an empty Desktop never appeared"
    away; grim "$runtime/files-empty-late.png"
    [ "$(region_changed "$runtime/files-empty.png" "$runtime/files-empty-late.png" 0 0 1366 705)" -gt 150 ] \
        || fail "the late file icon was not painted"
    stop_plate
    rm -f "$runtime/shims/gio"
    echo "SG1 luna files: empty Desktop renders no file icon, keys do nothing, a later file appears PASS"
}

# =========================================================================
# WP1.8  output scale change and hotplug while menus are open
# =========================================================================
stage_outputs() {
    # Own two-output compositor (the other stages use one output).
    stop_plate
    kill "$compositor" 2>/dev/null || :; wait "$compositor" 2>/dev/null || :
    rm -f "$runtime/wayland-0" "$runtime/wayland-0.lock"
    WLR_HEADLESS_OUTPUTS=2 labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
        >"$runtime/labwc-2.log" 2>&1 &
    compositor=$!
    n=0; while [ ! -S "$runtime/wayland-0" ] && [ "$n" -lt 60 ]; do n=$((n + 1)); sleep .2; done
    [ -S "$runtime/wayland-0" ] || fail "no Wayland socket for the two-output compositor"
    set -- $(wlr-randr | sed -n 's/^\([^ ][^ ]*\) .*/\1/p')
    [ "$#" = 2 ] || fail "expected two headless outputs, got $#"
    o1=$1 o2=$2
    wlr-randr --output "$o1" --custom-mode 1366x768@60Hz --scale 1 --pos 0,0 \
              --output "$o2" --custom-mode 1366x768@60Hz --scale 1 --pos 1366,0
    sleep .5
    mkdir -m 0700 "$runtime/data-o" 2>/dev/null || :
    export SG1I_GIO_LOG="$runtime/outputs-gio.log" SG1I_GIO_MODE="$runtime/outputs-gio.mode"
    rm -f "$SG1I_GIO_LOG"; echo ok >"$SG1I_GIO_MODE"
    cat >"$runtime/shims/gio" <<'SHIM'
#!/bin/sh
printf 'gio %s\n' "$*" >>"$SG1I_GIO_LOG"
exit 0
SHIM
    chmod 0700 "$runtime/shims/gio"
    log=$runtime/plate-outputs-luna.log
    renew_keyboard_seat
    start_plate "$runtime/luna.json" "$log" "PATH=$runtime/shims:$PATH"
    sleep 1
    launches() { count_lines "$SG1I_GIO_LOG" 'gio launch '; }
    # The Start button (y>=705) legitimately shows hover while the pointer rests on it.
    frame_diff() { region_changed "$1" "$2" 0 0 1366 705; }
    start_click() { "$clicker" 35 748 2732 768 >/dev/null; sleep .6; }
    # Baselines of the idle shell at both scales (menu closed).
    grim -o "$o1" "$runtime/o1-1.0.png"
    wlr-randr --output "$o1" --scale 1.5; sleep 1.2
    grim -o "$o1" "$runtime/o1-1.5.png"
    wlr-randr --output "$o1" --scale 1; sleep 1.2
    [ "$(frame_diff "$runtime/o1-1.0.png" "$(grim -o "$o1" "$runtime/o1-1.0b.png"; echo "$runtime/o1-1.0b.png")")" -lt 300 ] \
        || fail "idle shell did not return to its original frame after a scale round trip"
    # 1. Start menu open while the output scale changes: it is re-laid out
    # (never a stale-size ghost), its highlighted row keeps its meaning,
    # Escape leaves no surface, and nothing launches by itself.
    start_click
    grim -o "$o1" "$runtime/o1-menu.png"
    [ "$(frame_diff "$runtime/o1-1.0.png" "$runtime/o1-menu.png")" -gt 20000 ] || fail "Start menu did not open"
    wlr-randr --output "$o1" --scale 1.5; sleep 1.5
    grim -o "$o1" "$runtime/o1-menu-1.5.png"
    [ "$(frame_diff "$runtime/o1-1.5.png" "$runtime/o1-menu-1.5.png")" -gt 20000 ] \
        || fail "Start menu vanished or was left unpainted after the scale change"
    [ "$(launches)" = 0 ] || fail "a scale change launched something"
    wtype -k Return; sleep .6
    [ "$(launches)" = 1 ] || fail "Return after the scale change did not launch the highlighted entry once ($(launches))"
    grim -o "$o1" "$runtime/o1-after-launch.png"
    [ "$(frame_diff "$runtime/o1-1.5.png" "$runtime/o1-after-launch.png")" -lt 300 ] \
        || fail "Start menu stayed painted after its entry launched at the new scale"
    start_click
    wlr-randr --output "$o1" --scale 1; sleep 1.5
    wtype -k Escape -k Escape; sleep .5
    grim -o "$o1" "$runtime/o1-escaped.png"
    [ "$(frame_diff "$runtime/o1-1.0.png" "$runtime/o1-escaped.png")" -lt 300 ] \
        || fail "a stale Start surface remained after scale change + Escape"
    wtype -k Return; sleep .5
    [ "$(launches)" = 1 ] || fail "Return on a closed Start menu launched something"
    echo "SG1 luna: Start menu across a scale change re-lays out, keeps its highlight, leaves no ghost PASS"
    # 2. Output hot-unplug while the menu is open on it.
    start_click
    wlr-randr --output "$o1" --off; sleep 1.5
    wtype -k Return; sleep .6
    [ "$(launches)" = 1 ] || fail "Return dispatched on a menu whose output was unplugged"
    kill -0 "$plate" || fail "RicePlate died on output removal with a menu open"
    wlr-randr --output "$o1" --on --custom-mode 1366x768@60Hz --scale 1 --pos 0,0; sleep 2
    grim -o "$o1" "$runtime/o1-replugged.png"
    [ "$(frame_diff "$runtime/o1-1.0.png" "$runtime/o1-replugged.png")" -lt 400 ] \
        || fail "a ghost menu or missing panel after output re-plug"
    start_click
    wtype -k Return; sleep .6
    [ "$(launches)" = 2 ] || fail "Start menu did not recover after re-plug ($(launches))"
    echo "SG1 luna: output unplug with Start open dispatches nothing, re-plug restores a clean shell PASS"
    stop_plate
    # 3. Tray popup (real SNI provider) across a scale change and an unplug.
    for rice in luna chrome; do
        recipe=chrome tray_x=1270
        if [ "$rice" = luna ]; then recipe=$runtime/luna.json tray_x=1185; fi
        log=$runtime/plate-outputs-$rice.log
        renew_keyboard_seat
        start_plate "$recipe" "$log"
        gen=$rice-out
        start_provider "$gen"
        wait_count "$log" 'RicePlate: SNI DBusMenu snapshot ready' 1 80 || fail "$rice: no DBusMenu snapshot"
        tray_open() {
            seen=$(count_lines "$log" 'compositor confirmed tray popup keyboard focus')
            "$clicker" --right-click "$tray_x" 746 2732 768 >/dev/null
            wait_count "$log" 'compositor confirmed tray popup keyboard focus' $((seen + 1)) 40 \
                || fail "$rice: tray popup did not open"
        }
        tray_clicked() { rcount "$gen" menu-event action clicked; }
        tray_closed() { rcount "$gen" menu-event action closed; }
        # Scale change: the popup is re-laid out, not stranded; its keyboard
        # path still works and dispatches exactly one action per gesture.
        tray_open
        c0=$(tray_closed)
        wlr-randr --output "$o1" --scale 1.5; sleep 1.5
        [ "$(tray_closed)" = "$c0" ] || fail "$rice: a scale change closed a healthy popup"
        wtype -k Return -s 300 -k Return; sleep .6
        [ "$(tray_clicked)" = 1 ] || fail "$rice: popup after a scale change dispatched $(tray_clicked) actions, expected 1"
        wlr-randr --output "$o1" --scale 1; sleep 1.5
        # Unplug: the owner is told the menu closed and no key reaches it.
        renew_keyboard_seat
        tray_open
        c0=$(tray_closed)
        wlr-randr --output "$o1" --off; sleep 1.5
        [ "$(tray_closed)" -gt "$c0" ] || fail "$rice: provider was not told the menu closed on output removal"
        wtype -k Return -s 300 -k Return; sleep .6
        [ "$(tray_clicked)" = 1 ] || fail "$rice: keys after output removal reached the provider menu"
        kill -0 "$plate" || fail "$rice: RicePlate died on output removal with a popup open"
        wlr-randr --output "$o1" --on --custom-mode 1366x768@60Hz --scale 1 --pos 0,0; sleep 2
        renew_keyboard_seat
        tray_open
        wtype -k Return -s 300 -k Return; sleep .6
        [ "$(tray_clicked)" = 2 ] || fail "$rice: tray popup did not recover after re-plug ($(tray_clicked))"
        stop_provider
        stop_plate
        echo "SG1 $rice: tray popup across scale change (one action) and unplug (closed, no leak) + re-plug PASS"
    done
    # 4. Unplug an output the open Start menu is NOT on, re-plug it, and hot-add
    # one the shell has never seen. The healthy menu keeps working, the panel
    # follows the output, nothing ghosts.
    o2_panel_painted() {
        # o2_panel_painted FILE -> non-black pixels in the bottom 40 rows of o2
        grim -o "$o2" "$1"
        /usr/bin/python3 - "$1" 2>/dev/null <<'PY'
from PIL import Image
import sys
im = Image.open(sys.argv[1]).convert("RGB")
w, h = im.size
print(sum(1 for p in im.crop((0, h - 40, w, h)).getdata() if max(p) > 24))
PY
    }
    plug_o2() { wlr-randr --output "$o2" --on --custom-mode 1366x768@60Hz --scale 1 --pos 1366,0; sleep 2.2; }
    plug_o1() { wlr-randr --output "$o1" --on --custom-mode 1366x768@60Hz --scale 1 --pos 0,0; sleep 2.2; }
    log=$runtime/plate-outputs-other.log
    renew_keyboard_seat
    start_plate "$runtime/luna.json" "$log" "PATH=$runtime/shims:$PATH"
    sleep 1
    grim -o "$o1" "$runtime/o1-base-b.png"
    [ "$(o2_panel_painted "$runtime/o2-base-b.png")" -gt 5000 ] || fail "no panel on the second output"
    l0=$(launches)
    start_click
    grim -o "$o1" "$runtime/o1-menu-b.png"
    [ "$(frame_diff "$runtime/o1-base-b.png" "$runtime/o1-menu-b.png")" -gt 20000 ] || fail "Start menu did not open on the first output"
    wlr-randr --output "$o2" --off; sleep 1.6
    grim -o "$o1" "$runtime/o1-menu-b2.png"
    [ "$(frame_diff "$runtime/o1-menu-b.png" "$runtime/o1-menu-b2.png")" -lt 300 ] \
        || fail "unplugging another output disturbed the open Start menu"
    wtype -k Return; sleep .6
    [ "$(launches)" = $((l0 + 1)) ] || fail "the open Start menu stopped working after another output was unplugged ($(launches) vs $l0)"
    grim -o "$o1" "$runtime/o1-after-b.png"
    [ "$(frame_diff "$runtime/o1-base-b.png" "$runtime/o1-after-b.png")" -lt 300 ] || fail "Start menu stayed painted after launching"
    kill -0 "$plate" || fail "RicePlate died when an unrelated output was unplugged"
    plug_o2
    [ "$(o2_panel_painted "$runtime/o2-replug.png")" -gt 5000 ] || fail "no panel on the output that was plugged back"
    "$clicker" 1401 748 2732 768 >/dev/null; sleep .7
    grim -o "$o2" "$runtime/o2-menu.png"
    [ "$(frame_diff "$runtime/o2-base-b.png" "$runtime/o2-menu.png")" -gt 20000 ] || fail "Start menu did not open on the re-plugged output"
    wtype -k Return; sleep .6
    [ "$(launches)" = $((l0 + 2)) ] || fail "Start menu on the re-plugged output launched $(( $(launches) - l0 - 1 )) times"
    stop_plate
    # Hot-add: the shell starts with only o1; o2 appears afterwards.
    wlr-randr --output "$o2" --off; sleep 1.2
    renew_keyboard_seat
    start_plate "$runtime/luna.json" "$log" "PATH=$runtime/shims:$PATH"
    sleep 1
    plug_o2
    [ "$(o2_panel_painted "$runtime/o2-added.png")" -gt 5000 ] || fail "no panel on a hot-added output"
    grim -o "$o1" "$runtime/o1-after-add.png"
    [ "$(frame_diff "$runtime/o1-base-b.png" "$runtime/o1-after-add.png")" -lt 400 ] || fail "adding an output disturbed the first output"
    l0=$(launches)
    "$clicker" 1401 748 2732 768 >/dev/null; sleep .7
    grim -o "$o2" "$runtime/o2-added-menu.png"
    [ "$(frame_diff "$runtime/o2-base-b.png" "$runtime/o2-added-menu.png")" -gt 20000 ] || fail "Start menu did not open on a hot-added output"
    wtype -k Return; sleep .6
    [ "$(launches)" = $((l0 + 1)) ] || fail "Start menu on a hot-added output launched $(( $(launches) - l0 )) times"
    kill -0 "$plate" || fail "RicePlate died on output hot-add"
    stop_plate
    echo "SG1 luna: unplugging a different output leaves the open Start menu working; re-plug and hot-add get a panel and a working menu PASS"

    # 5. Calendar, desktop context menu and Run dialog across removal of the
    # output they are on: each is closed, takes no stale key and a fresh
    # gesture works after the output is back.
    cat >"$runtime/run-witness" <<WITNESS
#!/bin/sh
echo ran >>"$runtime/run-witness.log"
WITNESS
    chmod 0700 "$runtime/run-witness"
    rm -f "$runtime/run-witness.log"
    plug_o2
    renew_keyboard_seat
    start_plate "$runtime/luna.json" "$log" "PATH=$runtime/shims:$PATH"
    sleep 1
    grim -o "$o1" "$runtime/o1-base-c.png"
    grim -o "$o2" "$runtime/o2-base-c.png"
    ghost_free() { # ghost_free WHAT: the replugged output equals the idle frame
        grim -o "$o1" "$runtime/o1-replug-c.png"
        [ "$(frame_diff "$runtime/o1-base-c.png" "$runtime/o1-replug-c.png")" -lt 400 ] || fail "$1: a ghost surface or missing panel after re-plug"
    }
    # 5a. calendar
    l0=$(launches)
    "$clicker" 1320 748 2732 768 >/dev/null; sleep .8
    grim -o "$o1" "$runtime/o1-cal.png"
    [ "$(frame_diff "$runtime/o1-base-c.png" "$runtime/o1-cal.png")" -gt 5000 ] || fail "calendar did not open"
    wlr-randr --output "$o1" --off; sleep 1.5
    wtype -k Right -s 100 -k Down -s 100 -k Return; sleep .4
    plug_o1
    ghost_free calendar
    [ "$(launches)" = "$l0" ] || fail "calendar: keys after output removal launched something"
    "$clicker" 1320 748 2732 768 >/dev/null; sleep .8
    grim -o "$o1" "$runtime/o1-cal2.png"
    [ "$(frame_diff "$runtime/o1-base-c.png" "$runtime/o1-cal2.png")" -gt 5000 ] || fail "calendar did not open again after the output returned"
    wtype -k Escape; sleep .5
    ghost_free "calendar after Escape"
    echo "SG1 luna: calendar across output removal closes, takes no stale key, reopens after re-plug PASS"
    # 5b. desktop shortcut context menu
    "$clicker" --right-click 75 120 2732 768 >/dev/null; sleep .7
    grim -o "$o1" "$runtime/o1-ctx.png"
    [ "$(frame_diff "$runtime/o1-base-c.png" "$runtime/o1-ctx.png")" -gt 3000 ] || fail "desktop context menu did not open"
    g0=$(count_lines "$SG1I_GIO_LOG" 'gio ')
    wlr-randr --output "$o1" --off; sleep 1.5
    wtype -k Down -s 100 -k Return; sleep .5
    plug_o1
    ghost_free "desktop context menu"
    [ "$(count_lines "$SG1I_GIO_LOG" 'gio ')" = "$g0" ] || fail "context menu: Return after output removal ran an action"
    "$clicker" --right-click 75 120 2732 768 >/dev/null; sleep .7
    grim -o "$o1" "$runtime/o1-ctx2.png"
    [ "$(frame_diff "$runtime/o1-base-c.png" "$runtime/o1-ctx2.png")" -gt 3000 ] || fail "desktop context menu did not open after re-plug"
    wtype -k Escape; sleep .5
    # (right-click leaves the shortcut selected, so compare only the part of
    # the menu that lies beside the icon)
    grim -o "$o1" "$runtime/o1-ctx3.png"
    [ "$(region_changed "$runtime/o1-base-c.png" "$runtime/o1-ctx3.png" 200 120 100 190)" -lt 100 ] \
        || fail "desktop context menu stayed painted after Escape"
    echo "SG1 luna: desktop context menu across output removal closes, runs nothing, reopens after re-plug PASS"
    # 5c. Run dialog. labwc re-homes a layer surface that has no output of its
    # own onto a surviving output, so the dialog must then be VISIBLE there
    # (never an invisible surface that still owns the keyboard and runs what
    # is typed); Escape closes it without running anything.
    open_run() {
        renew_keyboard_seat
        start_click
        grim -o "$o1" "$runtime/o1-run-menu.png"
        [ "$(frame_diff "$runtime/o1-base-c.png" "$runtime/o1-run-menu.png")" -gt 20000 ] || fail "Start menu did not open for Run"
        "$clicker" 316 580 2732 768 >/dev/null; sleep .8
        grim -o "$o1" "$runtime/o1-run.png"
        [ "$(region_changed "$runtime/o1-base-c.png" "$runtime/o1-run.png" 459 268 448 232)" -gt 800 ] || fail "Run dialog did not open"
    }
    open_run
    wlr-randr --output "$o1" --off; sleep 1.5
    grim -o "$o2" "$runtime/o2-run.png"
    [ "$(region_changed "$runtime/o2-base-c.png" "$runtime/o2-run.png" 459 268 448 232)" -gt 800 ] \
        || fail "the Run dialog vanished from view although it can still receive typed commands"
    wtype -k Escape; sleep .6
    grim -o "$o2" "$runtime/o2-run-esc.png"
    [ "$(region_changed "$runtime/o2-base-c.png" "$runtime/o2-run-esc.png" 459 268 448 232)" -lt 100 ] \
        || fail "Escape did not close the re-homed Run dialog"
    wtype -d 30 "$runtime/run-witness" -s 150 -k Return; sleep .8
    [ ! -e "$runtime/run-witness.log" ] || fail "a command typed after the Run dialog was dismissed ran"
    plug_o1
    ghost_free "Run dialog"
    [ ! -e "$runtime/run-witness.log" ] || fail "a stale Run command ran after the re-plug"
    # recovery: a fresh Run dialog runs the command exactly once
    open_run
    wtype -d 30 "$runtime/run-witness" -s 150 -k Return
    tries=0; while [ ! -s "$runtime/run-witness.log" ] && [ "$tries" -lt 30 ]; do tries=$((tries + 1)); sleep .1; done
    sleep .5
    [ "$(wc -l <"$runtime/run-witness.log" 2>/dev/null || echo 0)" = 1 ] || fail "Run did not recover (exactly one run expected)"
    kill -0 "$plate" || fail "RicePlate died"
    stop_plate
    echo "SG1 luna: Run dialog across output removal is re-homed visibly (never invisible), Escape closes it, nothing typed after dismissal runs, a fresh dialog runs once PASS"
    rm -f "$runtime/shims/gio"
}

run_stage() {
    case " $stages " in *" $1 "*) "stage_$1";; esac
}
for s in windows launcher clock sni notices files outputs; do run_stage "$s"; done
echo "PASS smoke_sg1_interaction_labwc ($stages)"

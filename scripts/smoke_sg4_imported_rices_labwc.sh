#!/bin/sh
# SG4 WP4.3: interactive receipts for BOTH imported Creator rices (Heritage
# Composer, a bottom taskbar with a tabbed menu, and Orbit Composer, a top
# panel with a sidebar menu) on a real headless labwc with the real
# riceplate-native binary, real virtual pointer + wtype keyboard, grim pixels
# and an external AT-SPI client.
#
# Import path: the real Creator backend (`creator_workspace` drafts -> verified
# RicePack export -> `pack` read-only preflight -> locked import into a FRESH
# XDG profile, scripts/sg4_imported_rices_setup.py). Nothing is applied by the
# import. Everything below runs on the imported IDs only.
#
#   apply  : supervised nested session (`launcher.py de start --nested`): the
#            Creator live-apply transaction switches classic -> imported rice,
#            the real pointer opens that rice's launcher menu, a menu row
#            runs its action, restore returns to classic and leaves no
#            residue (no process of the imported rice, no file change in the
#            private HOME/XDG, no selection written).
#   input  : (per rice, directly started riceplate-native with the AT-SPI
#            bridge, which a nested supervisor never enables) primary launcher
#            menu by pointer, keyboard and AT-SPI doAction; menu dismissal;
#            the calendar popup; a desktop shortcut; an unavailable capability
#            (Wi-Fi/Mute with no provider, Log out outside a labwc-managed
#            session) exposing NO action; a failing helper producing the
#            visible, AT-SPI-exposed notice; a failing provider showing
#            "failed" and recovering; a 640x480 compact layout.
#
# Disposable only: private HOME/XDG/runtime and D-Bus session, a PATH holding
# only logging shims (no real nmcli/wpctl/foot/fuzzel is ever reached), never a
# logged-in session or host setting. Exit 77 = tool missing.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
self="$root/scripts/smoke_sg4_imported_rices_labwc.sh"
release="$root/components/riceplate-wayland/target/release"
native="$release/riceplate-native"
clicker="$release/examples/wayland_pointer_click"
probe="$root/scripts/sg4_atspi_probe.py"
notice="$root/scripts/sg1_notice_probe.py"
setup="$root/scripts/sg4_imported_rices_setup.py"

if [ "${1:-}" != --inner ]; then
    for command in dbus-run-session labwc wlr-randr wtype grim timeout sha256sum; do
        command -v "$command" >/dev/null || { echo "Missing $command" >&2; exit 77; }
    done
    test -x "$native" && test -x "$clicker" || {
        echo "Build riceplate-native and the wayland_pointer_click example first" >&2
        exit 77
    }
    /usr/bin/python3 -c 'import PIL, pyatspi, gi' >/dev/null 2>&1 || exit 77
    runtime=$(mktemp -d)
    chmod 0700 "$runtime"
    trap 'rm -rf -- "$runtime"' EXIT
    mkdir -m 0700 "$runtime/author-config" "$runtime/author-state" "$runtime/config" \
        "$runtime/state" "$runtime/home" "$runtime/packs" "$runtime/bin" "$runtime/prov" \
        "$runtime/run" "$runtime/shots"
    export HOME="$runtime/home"
    # 1. Author + export under one profile ...
    XDG_CONFIG_HOME="$runtime/author-config" XDG_STATE_HOME="$runtime/author-state" \
        /usr/bin/python3 "$setup" author "$runtime/packs" >"$runtime/authored.json"
    # 2. ... and import into a different, fresh profile: the session profile.
    export XDG_CONFIG_HOME="$runtime/config" XDG_STATE_HOME="$runtime/state"
    /usr/bin/python3 "$setup" import "$runtime/packs" >"$runtime/imported.json"
    export XDG_RUNTIME_DIR="$runtime/run"
    export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
    export SG4_RUNTIME="$runtime" SG4_SELF="$self"
    set +e
    timeout -k 5s "${SG4_BUDGET:-280}s" dbus-run-session -- sh "$self" --inner
    status=$?
    set -e
    # Development aid: SG4_KEEP_DIR=<writable dir> keeps the real frames/logs.
    [ -z "${SG4_KEEP_DIR:-}" ] || cp "$runtime"/shots/*.png "$runtime"/*.log "$SG4_KEEP_DIR"/ 2>/dev/null || :
    if [ "$status" -ne 0 ]; then
        echo "FAIL: SG4 imported-rices labwc smoke exited $status" >&2
        exit "$status"
    fi
    echo "PASS: SG4 imported Heritage + Orbit rices: apply/restore and interactive receipts complete"
    exit 0
fi

# ---------------------------------------------------------------------------
# Inner: private D-Bus session, private runtime.
# ---------------------------------------------------------------------------
runtime=$SG4_RUNTIME
shots=$runtime/shots
calls=$runtime/calls.log
bin=$runtime/bin
prov=$runtime/prov
: >"$calls"
compositor= plate= keyboard_keeper= session=
cleanup() {
    for pid in "$plate" "$keyboard_keeper" "$session" "$compositor"; do
        [ -z "$pid" ] || kill "$pid" 2>/dev/null || :
    done
    for pid in "$plate" "$keyboard_keeper" "$session" "$compositor"; do
        [ -z "$pid" ] || wait "$pid" 2>/dev/null || :
    done
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
rice=setup
fail() {
    echo "FAIL [$rice]: $*" >&2
    for log in plate.log session.log labwc.log; do
        [ ! -s "$runtime/$log" ] || { echo "--- $log ---" >&2; tail -n 25 "$runtime/$log" >&2; }
    done
    echo "--- calls ---" >&2; cat "$calls" >&2 || :
    exit 1
}
last_pass=$(date +%s)
pass() {
    now=$(date +%s)
    echo "PASS [$rice]: $* ($((now - last_pass))s)"
    last_pass=$now
}
json() { /usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]][int(sys.argv[3])][sys.argv[4]])' "$@"; }

# ---- private fixtures: logging shims, never the real tools -------------------
# foot/fuzzel/gio log their argv; `ricebowl` (lock) honours $runtime/ricebowl.mode.
for tool in foot fuzzel gio; do
    cat >"$bin/$tool" <<SHIM
#!/bin/sh
echo "$tool \$*" >>"$calls"
exit 0
SHIM
done
cat >"$bin/ricebowl" <<SHIM
#!/bin/sh
PATH=/usr/bin:/bin
echo "ricebowl \$*" >>"$calls"
[ "\$(cat "$runtime/ricebowl.mode" 2>/dev/null)" != fail ] || exit 3
exit 0
SHIM
echo ok >"$runtime/ricebowl.mode"
# nmcli/wpctl: state in private files, mode ok|fail (exit 1, state unchanged).
cat >"$prov/nmcli" <<SHIM
#!/bin/sh
PATH=/usr/bin:/bin
echo "nmcli \$*" >>"$calls"
case "\$*" in
    "--wait 1 radio wifi") cat "$runtime/wifi"; exit 0 ;;
    "--wait 1 -t -f STATE general") echo connected; exit 0 ;;
    "--wait 3 radio wifi on") new=enabled ;;
    "--wait 3 radio wifi off") new=disabled ;;
    *) exit 64 ;;
esac
[ "\$(cat "$runtime/provider.mode")" != fail ] || exit 1
echo "\$new" >"$runtime/wifi"
SHIM
cat >"$prov/wpctl" <<SHIM
#!/bin/sh
PATH=/usr/bin:/bin
echo "wpctl \$*" >>"$calls"
mute=\$(cat "$runtime/mute")
case "\$*" in
    "get-volume @DEFAULT_AUDIO_SINK@")
        printf 'Volume: 0.50%s\n' "\$([ "\$mute" = 1 ] && echo ' [MUTED]')"; exit 0 ;;
    "set-mute @DEFAULT_AUDIO_SINK@ toggle") ;;
    *) exit 64 ;;
esac
[ "\$(cat "$runtime/provider.mode")" != fail ] || exit 1
if [ "\$mute" = 1 ]; then echo 0; else echo 1; fi >"$runtime/mute"
SHIM
chmod 0700 "$bin"/* "$prov"/*
printf '%s\n' enabled >"$runtime/wifi"; printf '%s\n' 0 >"$runtime/mute"
printf '%s\n' ok >"$runtime/provider.mode"
with_provider() { cp "$prov/nmcli" "$prov/wpctl" "$bin/"; }
without_provider() { rm -f "$bin/nmcli" "$bin/wpctl"; }
count() { n=$(grep -cE -- "$1" "$calls" 2>/dev/null || :); echo "${n:-0}"; }
expect_count() {
    # expect_count PATTERN WANT WHAT: settle, then the exact number of receipts.
    sleep .5
    got=$(count "$1")
    [ "$got" -eq "$2" ] || fail "$3: expected $2 call(s) matching '$1', saw $got"
}
wait_count() {
    n=0
    while [ "$(count "$1")" -lt "$2" ]; do
        n=$((n + 1)); [ "$n" -lt 40 ] || fail "$3: no call matching '$1' (want $2)"
        sleep .1
    done
}

# ---- compositor, input, pixels ------------------------------------------------
click() { "$clicker" "$1" "$2" "$W" "$H" >/dev/null; }
rclick() { "$clicker" --right-click "$1" "$2" "$W" "$H" >/dev/null; }
park() { "$clicker" --move-only "$((W - 2))" "$((H / 2))" "$W" "$H" >/dev/null; sleep .25; }
region_hash() { grim -t ppm -g "$1,$2 $3x$4" - | sha256sum | cut -d' ' -f1; }
shot() { grim "$shots/$rice-$1.png"; }
# changed_pixels A.png B.png X Y W H -> pixels differing by more than 20
changed_pixels() {
    /usr/bin/python3 - "$@" <<'PY'
import sys
from PIL import Image, ImageChops
a, b = sys.argv[1:3]
x, y, w, h = map(int, sys.argv[3:7])
with Image.open(a) as ia, Image.open(b) as ib:
    box = (x, y, x + w, y + h)
    d = ImageChops.difference(ia.convert("RGB").crop(box), ib.convert("RGB").crop(box))
    print(sum(max(p) > 20 for p in d.getdata()))
PY
}
at() { /usr/bin/python3 "$probe" "$@" >/dev/null 2>"$runtime/at.err"; }
at_must() { at "$@" || fail "AT-SPI $*: $(cat "$runtime/at.err")"; }
wait_socket() {
    n=0
    while [ ! -S "$1" ] && [ "$n" -lt 80 ]; do
        n=$((n + 1)); sleep .25
        [ -z "$2" ] || kill -0 "$2" 2>/dev/null || fail "process for $1 died at startup"
    done
    [ -S "$1" ] || fail "no socket $1"
}
set_mode() {
    W=$1; H=$2
    wlr-randr --output "$output" --custom-mode "${W}x${H}@60Hz" --scale 1; sleep .5
}
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
start_compositor() {
    labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
        >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    wait_socket "$XDG_RUNTIME_DIR/wayland-0" "$compositor"
    export WAYLAND_DISPLAY=wayland-0
    output=$(wlr-randr | sed -n '1s/[[:space:]].*//p')
    test -n "$output"
    set_mode 1366 768
}
stop_compositor() {
    [ -z "$keyboard_keeper" ] || { kill "$keyboard_keeper" 2>/dev/null || :; wait "$keyboard_keeper" 2>/dev/null || :; keyboard_keeper=; }
    [ -z "$compositor" ] || { kill "$compositor" 2>/dev/null || :; wait "$compositor" 2>/dev/null || :; compositor=; }
}
# A shell started with RICEBOWL_DE_SCREEN_READER=1 waits for org.a11y.Status;
# this disposable private bus emulates a screen reader switching it on.
enable_accessibility() {
    /usr/bin/python3 -c 'import pyatspi; pyatspi.Registry.getDesktop(0).childCount' >/dev/null
    dbus-send --session --print-reply --reply-timeout=5000 --dest=org.a11y.Bus /org/a11y/bus \
        org.freedesktop.DBus.Properties.Set string:org.a11y.Status string:IsEnabled \
        variant:boolean:true >/dev/null || fail "could not enable accessibility"
}
# Digest of every file under a profile directory (content + relative name).
tree_digest() {
    (cd "$1" && find . \( -type f -o -type l \) -print0 | sort -z | xargs -0 -r sha256sum \
        | sha256sum | cut -d' ' -f1)
}
profile_digest() { echo "$(tree_digest "$HOME")/$(tree_digest "$XDG_CONFIG_HOME")/$(tree_digest "$XDG_STATE_HOME")"; }
# alive NAME: live (non-zombie) process of this user with that comm name.
alive() { ps -u "$(id -u)" -o stat=,comm= | NEEDLE=$1 awk '$1 !~ /^Z/ && $2 == ENVIRON["NEEDLE"] { f = 1 } END { exit !f }'; }
alive_cmd() { ps -u "$(id -u)" -o stat=,args= | NEEDLE=$1 awk '$1 !~ /^Z/ && index($0, ENVIRON["NEEDLE"]) { f = 1 } END { exit !f }'; }
native_for() {
    # Processes of the REAL native binary running a given recipe file.
    n=0
    for pid in $(pgrep -u "$(id -u)" -f riceplate-native 2>/dev/null || :); do
        [ "$(tr '\0' ' ' <"/proc/$pid/comm" 2>/dev/null)" = "riceplate-nativ" ] || continue
        if tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -qF -- "$1"; then n=$((n + 1)); fi
    done
    echo "$n"
}

# =========================================================================
# stage apply: supervised nested session, Creator live apply + restore
# =========================================================================
stage_apply() {
    rice=apply
    W=1366 H=768
    before=$(profile_digest)
    PATH="$bin:$release:$PATH" \
        /usr/bin/python3 "$root/launcher.py" de start --nested --panel native \
        --recipe classic >"$runtime/session.log" 2>&1 &
    session=$!
    n=0
    while [ ! -S "$XDG_RUNTIME_DIR/wayland-0" ] || [ ! -S "$XDG_RUNTIME_DIR/ricebowl-live-wayland-0.sock" ]; do
        n=$((n + 1)); [ "$n" -lt 120 ] || fail "supervised session never exposed its sockets"
        kill -0 "$session" 2>/dev/null || fail "supervised session died at startup"
        sleep .25
    done
    export WAYLAND_DISPLAY=wayland-0
    output=$(wlr-randr | sed -n '1s/[[:space:]].*//p')
    set_mode 1366 768
    renew_keyboard_seat
    sleep 1
    live() { PATH="$bin:$release:$PATH" /usr/bin/python3 "$root/launcher.py" de "$@" --json; }
    live creator-live-status >"$runtime/status.json"
    /usr/bin/python3 - "$runtime/status.json" <<'PY' || fail "supervisor did not start on classic"
import json, sys
d = json.load(open(sys.argv[1]))
assert d["ok"] and d["active"] == "classic" and d["panel"] == "native", d
assert not d["next_login_persisted"], d
PY
    shot classic
    index=0
    for index in 0 1; do
        id=$(json "$runtime/imported.json" rices "$index" id)
        sha=$(json "$runtime/imported.json" rices "$index" semantic_sha256)
        path=$(json "$runtime/imported.json" rices "$index" recipe_path)
        template=$(json "$runtime/imported.json" rices "$index" template)
        rice=apply-$template
        live creator-live-apply --recipe "$id" --expect-sha256 "$sha" --expect-active classic \
            >"$runtime/apply.json" || fail "Creator live apply of imported $id was refused"
        /usr/bin/python3 - "$runtime/apply.json" "$id" <<'PY' || fail "apply reply is not a confirmed change to $id"
import json, sys
d = json.load(open(sys.argv[1]))
assert d["ok"] and d["changed"] and d["active"] == sys.argv[2] and d["previous"] == "classic", d
assert d["panel"] == "native" and not d["next_login_persisted"], d
PY
        # A shell replaced inside one compositor session needs a fresh
        # virtual keyboard to receive wl_keyboard keymap/enter (labwc 0.7.1
        # + wtype harness behaviour, see WP0.1); real keyboards are unaffected.
        sleep .6
        renew_keyboard_seat
        sleep .6
        shot applied
        [ "$(native_for "$path")" -eq 1 ] || fail "expected exactly one riceplate-native for $path"
        strip_y=$((H - 80)); [ "$template" != orbit-composer ] || strip_y=0
        [ "$(changed_pixels "$shots/apply-classic.png" "$shots/$rice-applied.png" 0 "$strip_y" "$W" 80)" -gt 200 ] \
            || fail "$template: panel pixels equal the classic panel after apply"
        # Real pointer on the imported rice's own launcher, then its menu row.
        case $template in
            heritage-composer) lx=44 ly=750 rowx=160 rowy=597 my=428 ;;
            *) lx=312 ly=28 rowx=190 rowy=226 my=56 ;;
        esac
        click "$lx" "$ly"; sleep .7; shot menu
        [ "$(changed_pixels "$shots/$rice-applied.png" "$shots/$rice-menu.png" 0 "$my" 320 300)" -gt 2000 ] \
            || fail "$template: real pointer did not open the launcher menu"
        wtype -k Down; sleep .3
        wtype -k Escape; sleep .6; shot closed
        [ "$(changed_pixels "$shots/$rice-applied.png" "$shots/$rice-closed.png" 0 "$my" 320 300)" -lt 400 ] \
            || fail "$template: Escape left the launcher menu painted"
        before_terminal=$(count '^foot ')
        click "$lx" "$ly"; sleep .6
        click "$rowx" "$rowy"
        wait_count '^foot ' $((before_terminal + 1)) "$template: menu row pointer click"
        # Wrong-rice guard: a wrong frame hash after restore would show here.
        live creator-live-restore --expect-active "$id" >"$runtime/restore.json" \
            || fail "$template: restore refused"
        /usr/bin/python3 - "$runtime/restore.json" <<'PY' || fail "$template: restore reply is not classic"
import json, sys
d = json.load(open(sys.argv[1]))
assert d["ok"] and d["changed"] and d["active"] == "classic" and d["panel"] == "native", d
assert not d["next_login_persisted"], d
PY
        sleep .8
        [ "$(native_for "$path")" -eq 0 ] || fail "$template: imported shell survived restore"
        shot restored
        [ "$(changed_pixels "$shots/apply-classic.png" "$shots/$rice-restored.png" 0 "$((H - 60))" "$W" 60)" -lt 800 ] \
            || fail "$template: restored panel differs from the original classic panel"
        pass "$template ($id): live apply, real pointer+keyboard menu, restore to classic"
    done
    live creator-live-status >"$runtime/status.json"
    /usr/bin/python3 - "$runtime/status.json" <<'PY' || fail "final supervisor state is not classic"
import json, sys
d = json.load(open(sys.argv[1]))
assert d["ok"] and d["active"] == "classic" and not d["next_login_persisted"], d
PY
    # End the session the way a logout does (`labwc --exit`), not by killing.
    LABWC_PID=$session labwc --exit >/dev/null 2>&1 || fail "labwc --exit refused"
    n=0
    while kill -0 "$session" 2>/dev/null && [ "$n" -lt 100 ]; do n=$((n + 1)); sleep .1; done
    ! kill -0 "$session" 2>/dev/null || fail "labwc --exit did not end the session"
    wait "$session" 2>/dev/null || :
    session=
    [ -z "$keyboard_keeper" ] || { kill "$keyboard_keeper" 2>/dev/null || :; wait "$keyboard_keeper" 2>/dev/null || :; keyboard_keeper=; }
    # The session is labwc itself (exec'd by `de start`); its `de shell` child
    # supervisor ends once the compositor connection is gone.
    n=0
    while alive labwc || alive_cmd 'launcher.py de shell'; do
        n=$((n + 1)); [ "$n" -lt 300 ] || break
        sleep .1
    done
    rice=apply
    # Residue: no stray process, no changed profile file, selection untouched.
    for index in 0 1; do
        [ "$(native_for "$(json "$runtime/imported.json" rices "$index" recipe_path)")" -eq 0 ] \
            || fail "native shell of an imported rice outlived the session"
    done
    if alive labwc; then
        ps -u "$(id -u)" -o pid,args | grep -E 'labwc|launcher.py|riceplate|waybar' >&2 || :
        fail "supervised labwc outlived the session"
    fi
    if alive_cmd 'launcher.py de shell'; then
        ps -u "$(id -u)" -o pid,stat,etime,args | grep -E 'launcher.py|riceplate|waybar' >&2 || :
        fail "RiceBowl shell supervisor outlived the session"
    fi
    after=$(profile_digest)
    [ "$before" = "$after" ] || fail "session left residue in the private HOME/XDG profile"
    PYTHONPATH="$root" /usr/bin/python3 - <<'PY' || fail "saved selection is not classic"
from macrice.de import recipes
assert recipes.current_selection() == ("classic", None), recipes.current_selection()
PY
    stray=$(ls -A "$XDG_RUNTIME_DIR" | grep -E '^(ricebowl|labwc)' || :)
    [ -z "$stray" ] || fail "stray session files in the runtime dir: $stray"
    : >"$calls"
    pass "supervised session closed: no process, profile or runtime residue; selection classic"
}

# =========================================================================
# stage input: one rice at a time, directly started native shell + AT-SPI
# =========================================================================
start_plate() {
    # start_plate RECIPE: only the private shim directory is on PATH, so a
    # "missing" provider is really missing and no real tool can be reached.
    renew_keyboard_seat
    PATH="$bin" RICEBOWL_DE_NESTED=0 RICEBOWL_DE_SCREEN_READER=1 \
        "$native" --recipe "$1" >"$runtime/plate.log" 2>&1 &
    plate=$!
    sleep 1
    kill -0 "$plate" 2>/dev/null || fail "riceplate-native exited at startup"
    at_must has "push button" "Open applications" 20
    sleep .5
}
stop_plate() {
    [ -z "$plate" ] || { kill "$plate" 2>/dev/null || :; wait "$plate" 2>/dev/null || :; }
    plate=
}
open_menu() {
    click "$LX" "$LY"
    at_must has menu "$MENU" 8
    sleep .3
}
menu_closed() { at_must none menu "$MENU" 6; }
mutations() { count '^(nmcli --wait 3 radio wifi (on|off)|wpctl set-mute)'; }

stage_input() {
    index=$1
    template=$(json "$runtime/imported.json" rices "$index" template)
    path=$(json "$runtime/imported.json" rices "$index" recipe_path)
    rice=$template
    W=1366 H=768
    case $template in
        heritage-composer)
            LX=44 LY=750 MENU='Heritage Desk' MY=428 CLK='1275 750' WIFI='1138 750'
            ROW_APPS='160 555' ROW_TERM='160 597' ICON='75 120' ICON_NAME='Programs, mirrored*'
            CLX=44 CLY=462 CMY=140 HAS_MUTE=1 MUTE='1338 750' WREG='1110 736 70 28' ;;
        *)
            LX=312 LY=28 MENU='Orbit Studio' MY=56 CLK='1220 28' WIFI='460 28'
            ROW_APPS='210 184' ROW_TERM='190 226' ICON='276 188' ICON_NAME='Explore, mirrored*'
            CLX=56 CLY=28 CMY=56 HAS_MUTE=0 MUTE= WREG='410 2 120 52' ;;
    esac
    : >"$calls"; echo ok >"$runtime/ricebowl.mode"; echo ok >"$runtime/provider.mode"
    echo enabled >"$runtime/wifi"; echo 0 >"$runtime/mute"
    start_compositor
    enable_accessibility

    # ---- 1. capability with no provider is shown as unavailable, never faked
    without_provider
    start_plate "$path"
    shot base
    at_must noaction "push button" "Wi-Fi, N/A, unavailable"
    [ "$HAS_MUTE" -eq 0 ] || at_must noaction "push button" "Mute, N/A, unavailable"
    park
    wifi_before=$(region_hash 1 1 1 1)
    # shellcheck disable=SC2086
    click $WIFI; sleep .5
    [ "$HAS_MUTE" -eq 0 ] || { click $MUTE; sleep .5; }
    at_must noaction "push button" "Wi-Fi, N/A, unavailable"
    expect_count '^(nmcli|wpctl) ' 0 "unavailable provider"
    "$notice" absent 2 >/dev/null || fail "an unavailable control raised a failure notice"
    pass "no provider: Wi-Fi${MUTE:+ and Mute} are 'N/A, unavailable' with no AT-SPI action; clicks reach no provider"

    # ---- 2. primary launcher menu: pointer opens, keyboard, pointer row, AT-SPI
    open_menu
    shot menu
    [ "$(changed_pixels "$shots/$rice-base.png" "$shots/$rice-menu.png" 0 "$MY" 320 304)" -gt 2000 ] \
        || fail "launcher click did not paint the menu"
    at_must has "push button" "Applications"
    at_must focused "push button" "Applications"
    if [ "$template" = orbit-composer ]; then
        # font_scale 2 in the fixed 320 px menu cannot hold these names: the
        # painted labels must end in the shared ellipsis while the accessible
        # names stay complete (WP4.4 finding: they used to be cut silently).
        /usr/bin/python3 "$root/scripts/sg4_menu_ellipsis_check.py" \
            "$shots/$rice-base.png" "$shots/$rice-menu.png" "$MY" >"$runtime/ellipsis.log" 2>&1 \
            || fail "Orbit overflowing menu labels carry no ellipsis: $(cat "$runtime/ellipsis.log")"
        at_must has "push button" "Applications"
        at_must has "push button" "Terminal"
        pass "Orbit menu at font_scale 2: truncated labels end in an ellipsis (pixels), accessible names stay full"
    fi
    wtype -k Down
    at_must focused "push button" "Terminal" 4
    wtype -k Return
    wait_count '^foot ' 1 "keyboard Return on Terminal"
    menu_closed
    sleep .3; shot closed
    [ "$(changed_pixels "$shots/$rice-base.png" "$shots/$rice-closed.png" 0 "$MY" 320 304)" -lt 400 ] \
        || fail "menu pixels remain after the keyboard action"
    wtype -k Return; wtype -k Down
    expect_count '^foot ' 1 "keys after the menu closed"
    open_menu
    # shellcheck disable=SC2086
    click $ROW_TERM
    wait_count '^foot ' 2 "pointer click on the Terminal row"
    menu_closed
    open_menu
    at_must act "push button" "Terminal"
    wait_count '^foot ' 3 "AT-SPI doAction on Terminal"
    menu_closed
    open_menu
    wtype -k Escape
    menu_closed
    expect_count '^foot ' 3 "Escape"
    expect_count '^fuzzel' 0 "nothing opened the external launcher yet"
    open_menu
    wtype -k Return
    wait_count '^fuzzel' 1 "Return on Applications"
    menu_closed
    pass "launcher menu: pointer open, Down+Return, pointer row, AT-SPI doAction, Escape; exact helper calls"

    # ---- 3. second group + unsupported Log out + failing helper notice
    open_menu
    wtype -k Right
    at_must focused "push button" "Lock screen" 4
    at_must noaction "push button" "Log out of RiceBowl, unavailable"
    wtype -k Return
    wait_count '^ricebowl de lock$' 1 "Lock screen"
    menu_closed
    "$notice" absent 2 >/dev/null || fail "successful lock raised a notice"
    echo fail >"$runtime/ricebowl.mode"
    open_menu; wtype -k Right; wtype -k Return
    wait_count '^ricebowl de lock$' 2 "failing Lock screen"
    "$notice" present "Command: Could not run" 8 >/dev/null || fail "failing helper left no AT-SPI notice"
    shot failure
    "$notice" absent 12 >/dev/null || fail "failure notice did not clear itself"
    expect_count '^ricebowl de lock$' 2 "failed helper was replayed"
    echo ok >"$runtime/ricebowl.mode"
    open_menu; wtype -k Right; wtype -k Return
    wait_count '^ricebowl de lock$' 3 "recovered Lock screen"
    "$notice" absent 2 >/dev/null || fail "recovered helper still shows a notice"
    pass "Session group: Log out is unavailable (no action), failing lock -> visible AT-SPI notice, clears, recovers"

    # ---- 4. popup: calendar opens, navigates, dismisses
    # shellcheck disable=SC2086
    click $CLK
    at_must has dialog "Calendar *" 8
    month_a=$(/usr/bin/python3 "$probe" names dialog | head -n 1)
    at_must act "push button" "Next month"
    sleep .4
    month_b=$(/usr/bin/python3 "$probe" names dialog | head -n 1)
    [ -n "$month_a" ] && [ "$month_a" != "$month_b" ] || fail "calendar did not change month ($month_a / $month_b)"
    wtype -k Escape
    at_must none dialog "Calendar *" 6
    pass "calendar popup: pointer open, AT-SPI Next month ($month_a -> $month_b), Escape dismisses"

    # ---- 5. desktop shortcut by pointer and AT-SPI
    before=$(count '^fuzzel')
    # shellcheck disable=SC2086
    click $ICON
    wait_count '^fuzzel' $((before + 1)) "desktop shortcut pointer click"
    at_must act "push button" "$ICON_NAME"
    wait_count '^fuzzel' $((before + 2)) "desktop shortcut AT-SPI doAction"
    pass "desktop shortcut runs its bound action by pointer and by AT-SPI"
    stop_plate

    # ---- 6. a failing provider is reported as failed, retried, recovered
    with_provider
    start_plate "$path"
    at_must has "push button" "Wi-Fi, On, ready" 10
    park; h_ready=$(region_hash $WREG)
    echo fail >"$runtime/provider.mode"
    # shellcheck disable=SC2086
    click $WIFI
    wait_count '^nmcli --wait 3 radio wifi off$' 1 "Wi-Fi toggle"
    at_must has "push button" "Wi-Fi, On, failed" 8
    park; h_failed=$(region_hash $WREG)
    [ "$h_failed" != "$h_ready" ] || fail "the failed Wi-Fi caption is not painted differently from ready"
    expect_count '^nmcli --wait 3 radio wifi (on|off)$' 1 "failed Wi-Fi toggle was replayed"
    [ "$(cat "$runtime/wifi")" = enabled ] || fail "failed provider changed its own state"
    echo ok >"$runtime/provider.mode"
    # shellcheck disable=SC2086
    click $WIFI
    wait_count '^nmcli --wait 3 radio wifi (on|off)$' 2 "Wi-Fi retry"
    at_must has "push button" "Wi-Fi, Off, ready" 8
    park; h_off=$(region_hash $WREG)
    [ "$h_off" != "$h_ready" ] && [ "$h_off" != "$h_failed" ] \
        || fail "the verified Off state is not painted differently from On/Failed"
    at_must act "push button" "Wi-Fi, Off, ready"
    wait_count '^nmcli --wait 3 radio wifi on$' 1 "Wi-Fi AT-SPI toggle back"
    at_must has "push button" "Wi-Fi, On, ready" 8
    if [ "$HAS_MUTE" -eq 1 ]; then
        echo fail >"$runtime/provider.mode"
        # shellcheck disable=SC2086
        click $MUTE
        wait_count '^wpctl set-mute' 1 "Mute"
        at_must has "push button" "Mute, On, failed" 8
        echo ok >"$runtime/provider.mode"
        # shellcheck disable=SC2086
        click $MUTE
        wait_count '^wpctl set-mute' 2 "Mute retry"
        at_must has "push button" "Mute, Muted, ready" 8
    fi
    pass "provider failure: exact single attempt, 'failed' state, retry works, AT-SPI doAction toggles back"
    stop_plate

    # ---- 7. smaller screen: compact layout keeps the launcher reachable
    without_provider
    set_mode 640 480
    start_plate "$path"
    at_must none "push button" "Wi-Fi, *" 6
    [ "$HAS_MUTE" -eq 0 ] || at_must none "push button" "Mute, *" 3
    # Each recipe's own compact layout: Heritage keeps the clock, Orbit swaps
    # it for the audio status component.
    if [ "$HAS_MUTE" -eq 1 ]; then
        at_must has "push button" "Clock *" 4
    else
        at_must none "push button" "Clock *" 3
        at_must has "status bar" "Audio: *" 4
    fi
    shot compact-base
    click "$CLX" "$CLY"
    at_must has menu "$MENU" 8
    sleep .3
    shot compact-menu
    /usr/bin/python3 - "$shots/$rice-compact-base.png" "$shots/$rice-compact-menu.png" <<'PY' || fail "compact menu is not fully painted inside the 640x480 output"
import sys
from PIL import Image, ImageChops
a, b = (Image.open(p).convert("RGB") for p in sys.argv[1:3])
assert a.size == b.size == (640, 480), (a.size, b.size)
box = ImageChops.difference(a, b).point(lambda v: 255 if v > 20 else 0).convert("L").getbbox()
assert box is not None, "no menu pixels"
assert box[0] >= 0 and box[2] <= 640 and box[1] >= 0 and box[3] <= 480, box
assert box[2] - box[0] >= 250 and box[3] - box[1] >= 200, box
PY
    before=$(count '^foot ')
    wtype -k Down; at_must focused "push button" "Terminal" 4
    wtype -k Return
    wait_count '^foot ' $((before + 1)) "compact keyboard action"
    menu_closed
    pass "640x480: recipe compact layout hides Wi-Fi${MUTE:+/Mute}, launcher menu opens inside the output, Down+Return runs Terminal"
    stop_plate
    stop_compositor
    [ "$(native_for "$path")" -eq 0 ] || fail "native shell outlived the stage"
}

stage_apply
echo "SG4 stage apply complete"
for index in 0 1; do
    stage_input "$index"
done
echo "SG4 stage input complete"

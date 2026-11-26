#!/bin/sh
# SG1 top gap 1: native RicePlate status/quick controls against a REAL headless
# labwc compositor, with REAL compositor input (virtual pointer + wtype) and
# private PATH shims for the exact provider tools RicePlate invokes
# (nmcli, wpctl; see components/riceplate-wayland/src/system_status.rs).
#
# Rices that expose controls (determined from the recipes and src/main.rs):
#   luna   XP Luna `xp-luna-columns`: network and volume tray icons open the
#          native status menu (Turn Wi-Fi on/off, Mute, Volume Down/Up).
#          The battery icon is a read-only Power Meter menu with no mutation.
#   v7     schema-v7 `type: control` panel buttons (the recipe fixture
#          tests/fixtures/riceplate-controls-v7.json): Wi-Fi, Mute, Vol -, Vol +.
#   chrome only shows read-only network/audio/battery labels; it exposes NO
#          mutating control. It is asserted inert (no provider call at all).
#
# For every control the smoke asserts, from process-private argv receipts:
#   success       exact argv, exactly one mutation, visible state changes
#                 (pointer on both rices; wtype keys on both for Wi-Fi and mute)
#   error         non-zero exit: exactly one attempt, NO replay, state unchanged,
#                 failure visible (v7 caption "Failed", Luna volume OSD)
#   fake success  exit 0 without a state change is shown as failed, not applied
#   slow/pending  repeat and cross-control clicks while pending are refused (no
#                 second mutation); v7 shows the Wait caption while pending
#   hung          (Wi-Fi) provider killed at the 4 s bound, no late mutation
#   unavailable   tool missing mid-session: no mutation, that capability is
#                 disabled (N/A), repeat clicks reach no provider, the other
#                 capability keeps working
#   recovery      a restored tool is NOT trusted until RicePlate re-reads it
#                 (next completed control); then a click applies exactly once
# Battery is read-only everywhere (Luna Power Meter menu only has "Power
# Options...", which launches settings, never a hardware mutation).
# Not asserted here: total outage (both tools missing) recovery needs the 30 s
# idle status heartbeat, which is too slow for this smoke.
# The visible state is a pixel hash of the real compositor output. A hash is
# only compared with another hash of the SAME surface, never with a mockup.
#
# Nothing here touches the real system: private XDG_* and HOME, a PATH that
# contains only the private shims, no real nmcli/wpctl/pactl is ever invoked.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
self="$root/scripts/smoke_sg1_status_labwc.sh"
native="$root/components/riceplate-wayland/target/release/riceplate-native"
clicker="$root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"

if [ "${1:-}" != --inner ]; then
    for command in dbus-run-session labwc wlr-randr wtype grim sha256sum; do
        command -v "$command" >/dev/null || { echo "Missing $command" >&2; exit 77; }
    done
    test -x "$native" && test -x "$clicker" || {
        echo "Build native release binary and wayland_pointer_click example first" >&2
        exit 77
    }
    runtime=$(mktemp -d)
    chmod 0700 "$runtime"
    trap 'rm -rf -- "$runtime"' EXIT
    cp "$root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
    cp "$root/tests/fixtures/riceplate-controls-v7.json" "$runtime/v7.json"
    chmod 0600 "$runtime/luna.json" "$runtime/v7.json"
    mkdir -m 0700 "$runtime/home" "$runtime/data" "$runtime/cache" "$runtime/bin" "$runtime/state"
    export XDG_RUNTIME_DIR="$runtime"
    export XDG_CONFIG_HOME="$runtime"
    export XDG_DATA_HOME="$runtime/data"
    export XDG_CACHE_HOME="$runtime/cache"
    export HOME="$runtime/home"
    export WLR_BACKENDS=headless
    export WLR_HEADLESS_OUTPUTS=1
    export WLR_RENDERER=pixman
    export RICEBOWL_DE_NESTED=1
    export SG1_RUNTIME="$runtime"
    set +e
    timeout -k 5s "${SG1_STATUS_BUDGET:-190}s" dbus-run-session -- sh "$self" --inner
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
        echo "FAIL: SG1 status/quick-control labwc smoke exited $status" >&2
        exit "$status"
    fi
    echo "PASS: SG1 status/quick-control labwc smoke complete"
    exit 0
fi

# ---------------------------------------------------------------------------
# Inner: runs inside a private D-Bus session with the private runtime exported.
# ---------------------------------------------------------------------------
runtime=$SG1_RUNTIME
state="$runtime/state"
receipts="$state/receipts"
shots=${SG1_STATUS_SHOTS:-}
export SG1_STATE_DIR="$state"
plate= keyboard_keeper= compositor=
rice=

cleanup() {
    [ -z "$plate" ] || { kill "$plate" 2>/dev/null || :; wait "$plate" 2>/dev/null || :; }
    [ -z "$keyboard_keeper" ] || { kill "$keyboard_keeper" 2>/dev/null || :; wait "$keyboard_keeper" 2>/dev/null || :; }
    [ -z "$compositor" ] || { kill "$compositor" 2>/dev/null || :; wait "$compositor" 2>/dev/null || :; }
}
trap cleanup EXIT
trap "exit 143" HUP INT TERM

fail() {
    echo "FAIL [$rice]: $*" >&2
    tail -n 25 "$runtime/plate-$rice.log" 2>/dev/null >&2 || :
    echo "--- receipts ---" >&2
    cat "$receipts" 2>/dev/null >&2 || :
    exit 1
}
last_pass=$(date +%s)
pass() {
    now=$(date +%s)
    echo "PASS [$rice]: $* ($((now - last_pass))s)"
    last_pass=$now
}

# ---- private provider shims ------------------------------------------------
# Both shims log their complete argv BEFORE doing anything, keep their state in
# private files and honour $state/mode:
#   ok     apply the mutation          fail   exit 1, no state change
#   noop   exit 0, NO state change     slow   sleep 2 s, then apply
#   hang   sleep 9 s (killed at the 4 s RicePlate bound; never applies)
install_shims() {
    cat >"$runtime/bin/nmcli" <<'SG1_NMCLI'
#!/bin/sh
PATH=/usr/bin:/bin
d=$SG1_STATE_DIR
echo "nmcli $*" >>"$d/receipts"
case "$*" in
    "--wait 1 radio wifi") cat "$d/wifi"; exit 0 ;;
    "--wait 1 -t -f STATE general") echo connected; exit 0 ;;
    "--wait 3 radio wifi on") new=enabled ;;
    "--wait 3 radio wifi off") new=disabled ;;
    *) exit 64 ;;
esac
case "$(cat "$d/mode")" in
    fail) exit 1 ;;
    noop) exit 0 ;;
    slow) sleep 2 ;;
    hang) sleep 9; exit 0 ;;
esac
echo "$new" >"$d/wifi"
SG1_NMCLI
    cat >"$runtime/bin/wpctl" <<'SG1_WPCTL'
#!/bin/sh
PATH=/usr/bin:/bin
d=$SG1_STATE_DIR
echo "wpctl $*" >>"$d/receipts"
vol=$(cat "$d/volume")
mute=$(cat "$d/mute")
case "$*" in
    "get-volume @DEFAULT_AUDIO_SINK@")
        printf 'Volume: %d.%02d%s\n' $((vol / 100)) $((vol % 100)) "$([ "$mute" = 1 ] && echo ' [MUTED]')"
        exit 0 ;;
    "set-mute @DEFAULT_AUDIO_SINK@ toggle") op=mute ;;
    "set-volume @DEFAULT_AUDIO_SINK@ 5%+ --limit 1.0") op=up ;;
    "set-volume @DEFAULT_AUDIO_SINK@ 5%-") op=down ;;
    *) exit 64 ;;
esac
case "$(cat "$d/mode")" in
    fail) exit 1 ;;
    noop) exit 0 ;;
    slow) sleep 2 ;;
    hang) sleep 9; exit 0 ;;
esac
case $op in
    mute) if [ "$mute" = 1 ]; then echo 0; else echo 1; fi >"$d/mute" ;;
    up) echo $((vol + 5)) >"$d/volume" ;;
    down) echo $((vol - 5)) >"$d/volume" ;;
esac
SG1_WPCTL
    chmod 0700 "$runtime/bin/nmcli" "$runtime/bin/wpctl"
}
remove_shims() { rm -f -- "$runtime/bin/nmcli" "$runtime/bin/wpctl"; }
reset_provider() {
    install_shims
    printf '%s\n' enabled >"$state/wifi"
    printf '%s\n' 50 >"$state/volume"
    printf '%s\n' 0 >"$state/mute"
    printf '%s\n' ok >"$state/mode"
    : >"$receipts"
}
set_mode() { printf '%s\n' "$1" >"$state/mode"; }

# ---- receipt assertions ----------------------------------------------------
# Mutations are exactly the argv RicePlate may use to change hardware state.
MUTATION='^(nmcli --wait 3 radio wifi (on|off)|wpctl set-(mute|volume) .*)$'
mutations() { grep -Ec "$MUTATION" "$receipts" || :; }
mutation_lines() { grep -E "$MUTATION" "$receipts" || :; }
settle() { sleep "${1:-.8}"; }
# Wait (bounded) for $1 mutations, then give a replay time to show up.
expect_mutations() {
    want=$1
    what=$2
    n=0
    while [ "$(mutations)" -lt "$want" ] && [ "$n" -lt 60 ]; do
        n=$((n + 1))
        sleep .1
    done
    settle 1
    got=$(mutations)
    [ "$got" -eq "$want" ] || fail "$what: expected $want provider mutation(s), saw $got"
}
# Exact argv of the LAST mutation line.
expect_last_mutation() {
    last=$(mutation_lines | tail -n 1)
    [ "$last" = "$1" ] || fail "$2: expected argv '$1', saw '$last'"
}
# Provider's own state, set by the shim only when it really applied.
expect_provider() {
    for pair in "$@"; do
        file=${pair%%=*}
        want=${pair#*=}
        have=$(cat "$state/$file")
        [ "$have" = "$want" ] || fail "provider $file expected '$want' saw '$have'"
    done
}

# ---- compositor, screenshots, input -----------------------------------------
shot() { [ -z "$shots" ] || WAYLAND_DISPLAY=wayland-0 grim "$shots/$rice-$1.png"; }
# Hash of a region of the real compositor output (x y w h).
region_hash() {
    WAYLAND_DISPLAY=wayland-0 grim -t ppm -g "$1,$2 $3x$4" - | sha256sum | cut -d' ' -f1
}
click() { WAYLAND_DISPLAY=wayland-0 "$clicker" "$1" "$2" 1366 768 >/dev/null; }
keys() { WAYLAND_DISPLAY=wayland-0 wtype "$@"; }

start_compositor() {
    labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
        >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    n=0
    while [ ! -S "$runtime/wayland-0" ] && [ "$n" -lt 60 ]; do
        kill -0 "$compositor" 2>/dev/null || { cat "$runtime/labwc.log" >&2; exit 1; }
        n=$((n + 1))
        sleep .2
    done
    [ -S "$runtime/wayland-0" ] || { cat "$runtime/labwc.log" >&2; exit 1; }
    output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
    test -n "$output"
    WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1
}

# Fresh virtual keyboard per rice (see smoke_sg1_sni_labwc.sh): a wtype keyboard
# is a seat-bound object that must not outlive the RicePlate it served.
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
    kill -0 "$keyboard_keeper" || { cat "$runtime/keyboard-$rice.log" >&2; exit 1; }
}

# Only the private shim directory is on RicePlate's PATH: a "missing tool" is
# really missing and the real /usr/bin/wpctl can never be reached.
start_plate() {
    recipe=$1
    PATH="$runtime/bin" WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$recipe" \
        >"$runtime/plate-$rice.log" 2>&1 &
    plate=$!
    n=0
    # The worker reads status once at startup; wait for that receipt (or, when
    # the tools are intentionally missing, for the surface to settle).
    while [ "$n" -lt 30 ]; do
        kill -0 "$plate" 2>/dev/null || fail "RicePlate exited at startup"
        if [ -s "$receipts" ] || [ ! -x "$runtime/bin/nmcli" ]; then break; fi
        n=$((n + 1))
        sleep .1
    done
    sleep 1
}
stop_plate() {
    [ -z "$plate" ] || { kill "$plate" 2>/dev/null || :; wait "$plate" 2>/dev/null || :; }
    plate=
}

# ---- per-rice control driver -------------------------------------------------
# v7: direct panel buttons at y=22 (top panel, 44 px).
# luna: a tray icon at y=748 opens the native status menu; rows are then clicked
#       (pointer) or selected/activated with real keys (wtype).
press() {
    case "$rice:$1" in
        v7:wifi) click 1053 22 ;;
        v7:mute) click 1113 22 ;;
        v7:down) click 1173 22 ;;
        v7:up) click 1238 22 ;;
        luna:wifi) click 1055 748; settle .35; click 1200 570 ;;
        luna:mute) click 1083 748; settle .35; click 1200 570 ;;
        luna:down) click 1083 748; settle .35; click 1200 602 ;;
        luna:up) click 1083 748; settle .35; click 1200 632 ;;
        *) fail "unknown press $rice:$1" ;;
    esac
}
# Keyboard activation. Luna: pointer opens the menu, wtype selects/activates the
# row (first enabled row is preselected). v7: the control last clicked keeps
# the keyboard focus, so Return re-invokes it (used only right after a press).
press_keys() {
    case "$rice:$1" in
        v7:*) keys -k Return ;;
        luna:wifi) click 1055 748; settle .35; keys -k Return ;;
        luna:mute) click 1083 748; settle .35; keys -k Return ;;
        luna:down) click 1083 748; settle .35; keys -k Down -k Return ;;
        luna:up) click 1083 748; settle .35; keys -k Down -k Down -k Return ;;
        *) fail "unknown press_keys $rice:$1" ;;
    esac
}
park() { WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 683 400 1366 768 >/dev/null; settle .3; }

# Visible state of one control as a hash of the real compositor output.
#   v7:   the control's own panel button caption (pointer parked first; the
#         region is inset so the focus ring never enters the hash).
#   luna: the native status menu rows (opened with a click, closed with Escape).
vis() {
    case "$rice:$1" in
        v7:wifi) park; region_hash 1029 7 50 30 ;;
        v7:mute) park; region_hash 1093 7 43 30 ;;
        v7:down) park; region_hash 1147 7 53 30 ;;
        v7:up) park; region_hash 1211 7 53 30 ;;
        luna:wifi|luna:mute|luna:down|luna:up)
            case $1 in wifi) icon=1055 ;; *) icon=1083 ;; esac
            click "$icon" 748; settle .5
            hash=$(region_hash 1078 520 272 160)
            keys -k Escape; settle .3
            printf '%s\n' "$hash" ;;
    esac
}
# Only the visible state that carries information for that rice/control:
# v7 captions and the Luna Wi-Fi menu. Luna audio failures show as the OSD.
ui() {
    case "$rice:$1" in
        v7:*|luna:wifi) vis "$1" ;;
        *) : ;;
    esac
}
# Luna audio failures/successes also raise the RicePop volume OSD (1.8 s).
osd_hash() { region_hash 1102 16 248 68; }

# ---- scenario helpers -----------------------------------------------------
argv_for() {
    case $1 in
        wifi)
            if [ "$(cat "$state/wifi")" = enabled ]; then echo 'nmcli --wait 3 radio wifi off'
            else echo 'nmcli --wait 3 radio wifi on'; fi ;;
        mute) echo 'wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle' ;;
        up) echo 'wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+ --limit 1.0' ;;
        down) echo 'wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-' ;;
    esac
}
wait_mutation() {
    n=0
    while [ "$(mutations)" -le "$1" ] && [ "$n" -lt 60 ]; do
        n=$((n + 1))
        sleep .1
    done
}
wait_provider_change() {
    first=$(cat "$state/$1")
    n=0
    while [ "$(cat "$state/$1")" = "$first" ] && [ "$n" -lt 80 ]; do
        n=$((n + 1))
        sleep .1
    done
}
# One real input gesture; exactly ONE provider mutation with the exact argv.
# The volume OSD only lives 1.8 s, so it is captured as soon as the mutation
# was observed (osd_now), before the replay-guard settle time.
attempt() {
    control=$1
    how=$2
    tag=$3
    before=$(mutations)
    argv=$(argv_for "$control")
    "$how" "$control"
    wait_mutation "$before"
    sleep .25
    osd_now=$(osd_hash)
    settle .6
    got=$(mutations)
    [ "$got" -eq $((before + 1)) ] || fail "$tag: expected $((before + 1)) provider mutation(s), saw $got"
    expect_last_mutation "$argv" "$tag"
}
# A click that must reach NO provider at all (disabled/unavailable/busy control).
inert() {
    lines=$(wc -l <"$receipts")
    "$1" "$2"
    settle .8
    [ "$(wc -l <"$receipts")" -eq "$lines" ] || fail "$3: click on a disabled control reached a provider"
}
changed() { [ "$1" != "$2" ] || fail "$3: visible state did not change"; }
same() { [ "$1" = "$2" ] || fail "$3: visible state changed without a provider change"; }
no_replay() {
    count=$(mutations)
    sleep "${2:-1.5}"
    [ "$(mutations)" -eq "$count" ] || fail "$1: provider mutation replayed without input"
}
# Only the visible state that is cheap and meaningful to capture:
# v7 captions (any control) and the Luna menus (Wi-Fi and mute).
ui() {
    case "$rice:$1" in
        v7:*|luna:wifi|luna:mute) vis "$1" ;;
        *) : ;;
    esac
}
# After a failed or ineffective click:
#   v7    the control's own caption shows "Failed" (differs from the prior one);
#   luna  a failed volume change raises the volume OSD ("Change failed");
#         a failed Wi-Fi change has no failure indicator because the status
#         menu closes, so the honest evidence is "the visible state did not move".
# The first failure presentation of each control is remembered in fail_<control>.
assert_failed_visible() {
    control=$1
    tag=$2
    prior=$3
    case "$rice:$control" in
        v7:*) now=$(vis "$control"); changed "$now" "$prior" "$tag (Failed caption expected)" ;;
        luna:wifi) now=$(vis wifi); same "$now" "$prior" "$tag" ;;
        luna:*) now=$osd_now; changed "$now" "$base_osd" "$tag (OSD 'Change failed' expected)" ;;
    esac
    eval "fail_$control=\$now"
}
# A repeated failure must look identical to the first one (same caption/OSD).
assert_same_failure() {
    control=$1
    tag=$2
    case "$rice:$control" in
        v7:*) now=$(vis "$control"); eval "expected=\$fail_$control" ;;
        luna:wifi) now=$(vis wifi); expected=$3 ;;
        luna:*) now=$osd_now; eval "expected=\$fail_$control" ;;
    esac
    [ "$now" = "$expected" ] || fail "$tag: failure presentation differs from the plain error"
}

# ---- scenarios ---------------------------------------------------------------
success_phase() {
    vw0=$(vis wifi)
    attempt wifi press "success wifi off (pointer)"
    expect_provider wifi=disabled
    changed "$(vis wifi)" "$vw0" "success wifi off"
    attempt wifi press_keys "success wifi on (keyboard)"
    expect_provider wifi=enabled
    pass "Wi-Fi toggle: pointer off then keyboard on; exact nmcli argv, one mutation each, visible state follows"

    vu0=$(ui up)
    attempt up press "success volume up"
    expect_provider volume=55
    [ "$rice" != v7 ] || changed "$(vis up)" "$vu0" "success volume up"
    attempt down press "success volume down"
    expect_provider volume=50
    vm0=$(ui mute)
    attempt mute press "success mute"
    expect_provider mute=1
    changed "$(vis mute)" "$vm0" "success mute"
    attempt mute press_keys "success unmute (keyboard)"
    expect_provider mute=0
    pass "volume +/- and mute: exact wpctl argv, one mutation each, visible state follows"
}

error_phase() {
    # Error: the provider exits non-zero. Exactly one attempt per click, no
    # replay, no state change, failure visible, and a later click recovers.
    set_mode fail
    prior=$(vis wifi)
    attempt wifi press "error wifi"
    expect_provider wifi=enabled
    assert_failed_visible wifi "error wifi" "$prior"
    no_replay "error wifi" 2
    set_mode ok
    attempt wifi press "recovery wifi"
    expect_provider wifi=disabled
    changed "$(vis wifi)" "$fail_wifi" "recovery wifi"
    pass "Wi-Fi error: one attempt, no replay, state unchanged, failure shown; next click recovers"

    for control in up down; do
        volume_before=$(cat "$state/volume")
        set_mode fail
        prior=$(ui "$control")
        attempt "$control" press "error $control"
        expect_provider "volume=$volume_before"
        assert_failed_visible "$control" "error $control" "$prior"
        set_mode ok
        attempt "$control" press "recovery $control"
        if [ "$control" = up ]; then expect_provider volume=55; else expect_provider volume=50; fi
        pass "volume $control error: one attempt, volume unchanged, failure shown; next click recovers"
    done
    prior=$(ui mute)
    set_mode fail
    attempt mute press "error mute"
    expect_provider mute=0
    assert_failed_visible mute "error mute" "$prior"
    no_replay "error mute" 1.5
    set_mode ok
    attempt mute press "recovery mute"
    expect_provider mute=1
    attempt mute press "unmute"
    expect_provider mute=0
    pass "mute error: one attempt, no replay, mute unchanged, failure shown; next click recovers"
}

noop_phase() {
    # Fake success: exit status 0 but the provider did not change. RicePlate
    # must read the state back and refuse to present that as applied.
    set_mode noop
    for control in wifi up; do
        snapshot=$(cat "$state/wifi" "$state/mute" "$state/volume")
        prior=$(ui "$control")
        attempt "$control" press "no-op $control"
        [ "$(cat "$state/wifi" "$state/mute" "$state/volume")" = "$snapshot" ] || fail "no-op shim changed state"
        assert_same_failure "$control" "no-op $control (exit 0, no state change)" "$prior"
    done
    set_mode ok
    pass "exit 0 without a state change is shown as failed, never as applied"
}

slow_phase() {
    # Pending: the provider is slow (2 s). While it works, a second click on
    # the SAME control and a click on ANOTHER control must be refused by the
    # zero-capacity control queue: no extra mutation, no queued burst.
    set_mode slow
    prior=$(ui wifi)
    before=$(mutations)
    argv=$(argv_for wifi)
    mute_before=$(cat "$state/mute")
    press wifi
    wait_mutation "$before"
    if [ "$rice" = v7 ]; then
        sleep .2
        pending=$(vis wifi)
        changed "$pending" "$prior" "pending Wi-Fi (Wait caption expected)"
    fi
    press wifi
    press mute
    wait_provider_change wifi
    settle 1
    [ "$(mutations)" -eq $((before + 1)) ] || fail "pending Wi-Fi: a second/other click produced an extra mutation"
    expect_last_mutation "$argv" "pending wifi"
    expect_provider "mute=$mute_before"
    [ "$rice" != v7 ] || changed "$(vis wifi)" "$pending" "completed Wi-Fi vs pending"
    pass "pending Wi-Fi (slow nmcli): repeat + cross-control clicks refused, exactly one mutation, completes once"

    before=$(mutations)
    argv=$(argv_for up)
    volume_before=$(cat "$state/volume")
    press up
    wait_mutation "$before"
    press up
    press down
    wait_provider_change volume
    settle 1
    [ "$(mutations)" -eq $((before + 1)) ] || fail "pending volume: a second/other click produced an extra mutation"
    expect_last_mutation "$argv" "pending volume up"
    expect_provider "volume=$((volume_before + 5))"
    pass "pending volume (slow wpctl): repeat + cross-control clicks refused, exactly one mutation"
    set_mode ok
}

hang_phase() {
    # Hung provider: RicePlate bounds every provider process at 4 s and kills
    # it. The shim only mutates AFTER its 9 s sleep, so a kill means no change:
    # exactly one attempt, no late mutation, failure shown, recovery.
    set_mode hang
    before=$(mutations)
    argv=$(argv_for wifi)
    wifi_now=$(cat "$state/wifi")
    press wifi
    wait_mutation "$before"
    sleep .5
    press wifi
    sleep 4.5
    [ "$(mutations)" -eq $((before + 1)) ] || fail "hung Wi-Fi: second click or the bound replayed the mutation"
    expect_last_mutation "$argv" "hung wifi"
    expect_provider "wifi=$wifi_now"
    [ "$rice" != v7 ] || same "$(vis wifi)" "$fail_wifi" "hung Wi-Fi must look like the error caption"
    set_mode ok
    attempt wifi press "recovery after hung wifi"
    [ "$(cat "$state/wifi")" != "$wifi_now" ] || fail "Wi-Fi did not recover after the hung provider"
    pass "hung nmcli killed at the 4 s bound: one attempt, no late/replayed mutation, failure shown; next click recovers"
}

unavailable_phase() {
    # A tool disappears while RicePlate still believes it is available. The
    # worker re-reads the state before every control: a missing tool means
    # Unavailable, never an optimistic success. No mutation is possible, only
    # that capability is disabled (the other keeps working), further clicks are
    # inert, and a restored tool is NOT trusted until RicePlate re-reads it.
    # The re-read happens on the next completed control (or the 30 s idle
    # heartbeat); here a working control provides it, so the test never sleeps.
    # --- Wi-Fi tool (nmcli) missing; audio keeps working.
    prior_w=$(vis wifi)
    rm -f -- "$runtime/bin/nmcli"
    muts=$(mutations)
    press wifi
    settle 1
    gone_w=$(vis wifi)
    changed "$gone_w" "$prior_w" "Wi-Fi with nmcli missing (N/A / disabled expected)"
    [ "$(mutations)" -eq "$muts" ] || fail "missing nmcli: a mutation was recorded"
    inert press wifi "unavailable Wi-Fi"
    same "$(vis wifi)" "$gone_w" "second click on unavailable Wi-Fi"
    attempt up press "audio while nmcli is missing"
    pass "nmcli missing: no mutation, Wi-Fi disabled (N/A), repeat clicks inert, audio unaffected"
    install_shims
    inert press wifi "restored nmcli not yet re-read"
    attempt down press "audio completion re-reads nmcli"
    changed "$(vis wifi)" "$gone_w" "Wi-Fi after nmcli returned and was re-read"
    attempt wifi press "recovery after nmcli returned"
    pass "nmcli returned: stale N/A stays inert (no fake enable) until re-read, then one click applies exactly one mutation"

    # --- audio tool (wpctl) missing; Wi-Fi keeps working.
    prior_m=$(vis mute)
    rm -f -- "$runtime/bin/wpctl"
    muts=$(mutations)
    press mute
    settle 1
    gone_m=$(vis mute)
    changed "$gone_m" "$prior_m" "mute with wpctl missing (N/A / disabled expected)"
    [ "$(mutations)" -eq "$muts" ] || fail "missing wpctl: a mutation was recorded"
    inert press up "unavailable volume"
    attempt wifi press "Wi-Fi while wpctl is missing"
    pass "wpctl missing: no mutation, audio controls disabled (N/A), repeat clicks inert, Wi-Fi unaffected"
    install_shims
    inert press mute "restored wpctl not yet re-read"
    attempt wifi press "Wi-Fi completion re-reads wpctl"
    attempt mute press "recovery after wpctl returned"
    pass "wpctl returned: re-read by the next completed control, then one click applies exactly one mutation"
}

battery_phase() {
    # Battery is read-only: the Luna Power Meter menu opens (visible), but a
    # click, a Return on its first row ("Power Options..." only launches the
    # settings app, which is absent from PATH here) and Escape never reach
    # nmcli/wpctl, and the menu closes again.
    park
    closed=$(region_hash 1078 520 272 160)
    lines=$(wc -l <"$receipts")
    click 1115 748
    settle .6
    changed "$(region_hash 1078 520 272 160)" "$closed" "battery Power Meter menu did not open"
    keys -k Escape
    settle .4
    same "$(region_hash 1078 520 272 160)" "$closed" "Power Meter menu did not close"
    [ "$(wc -l <"$receipts")" -eq "$lines" ] || fail "battery indicator reached a provider"
    pass "battery is read-only: Power Meter menu opens/closes, no provider call, no mutation"
}

run_rice() {
    rice=$1
    recipe=$2
    renew_keyboard_seat
    reset_provider
    start_plate "$recipe"
    park
    [ "$(mutations)" -eq 0 ] || fail "startup status sampling mutated hardware"
    grep -qx 'nmcli --wait 1 radio wifi' "$receipts" || fail "no initial Wi-Fi read"
    grep -qx 'wpctl get-volume @DEFAULT_AUDIO_SINK@' "$receipts" || fail "no initial volume read"
    base_osd=$(osd_hash)
    shot 00-start
    success_phase
    error_phase
    noop_phase
    slow_phase
    hang_phase
    [ "$rice" != luna ] || battery_phase
    unavailable_phase
    shot 99-end
    stop_plate
}

chrome_phase() {
    # Chrome (macrice/de/resources/recipes/chrome.json) shows network, audio and
    # battery as read-only labels. It exposes NO mutating control, so clicks
    # on them must not reach any provider and must not change anything.
    rice=chrome
    renew_keyboard_seat
    reset_provider
    start_plate chrome
    park
    status_hash() { region_hash 975 735 175 22; }
    shown=$(status_hash)
    cp "$receipts" "$receipts.chrome"
    for x in 997 1061 1125; do click "$x" 745; settle .3; done
    keys -k Return -k space
    park
    settle .4
    same "$(status_hash)" "$shown" "Chrome read-only indicators"
    cmp -s "$receipts" "$receipts.chrome" || fail "Chrome indicator click reached a provider"
    [ "$(mutations)" -eq 0 ] || fail "Chrome mutated hardware"
    pass "Chrome network/audio/battery are read-only: clicks and keys cause no provider call and no change"
    stop_plate
    rm -f -- "$runtime/bin/nmcli" "$runtime/bin/wpctl"
    : >"$receipts"
    start_plate chrome
    park
    missing=$(status_hash)
    changed "$missing" "$shown" "Chrome labels with nmcli/wpctl missing (N/A expected)"
    for x in 997 1061 1125; do click "$x" 745; settle .3; done
    park
    same "$(status_hash)" "$missing" "Chrome unavailable indicators"
    [ ! -s "$receipts" ] || fail "Chrome clicked a missing provider"
    pass "Chrome with providers missing shows N/A and stays inert"
    stop_plate
}

# ---------------------------------------------------------------------------
start_compositor
for rice in luna v7; do
    case $rice in luna) recipe=$runtime/luna.json ;; v7) recipe=$runtime/v7.json ;; esac
    run_rice "$rice" "$recipe"
done
chrome_phase

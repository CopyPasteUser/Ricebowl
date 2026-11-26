#!/bin/sh
# SG5: real labwc keyboard delivery + external AT-SPI Run editor semantics.
# The Python client can only query the public accessibility bus; no private
# Rust entrypoints or synthetic AccessKit model are accepted as evidence.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$root/components/riceplate-wayland/target/release/riceplate-native"
ime="$root/components/riceplate-wayland/target/release/examples/wayland_ime_v2_client"
clicker="$root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
probe_bin="$root/components/riceplate-wayland/target/release/riceplate_focus_probe"
test -x "$probe_bin" || { echo "Build the focus probe fixture first" >&2; exit 1; }
test -x "$clicker" || { echo "Build Wayland pointer fixture first" >&2; exit 1; }
test -x "$ime" || { echo "Build the external v2 IME fixture first" >&2; exit 1; }
test -x "$native" || { echo 'Build native RicePlate first' >&2; exit 1; }
runtime=$(mktemp -d -t ricebowl-sg5-atspi-XXXXXXXX)
chmod 0700 "$runtime"
trap 'rm -rf -- "$runtime"' EXIT
mkdir -m 0700 "$runtime/config"
export XDG_RUNTIME_DIR="$runtime" XDG_CONFIG_HOME="$runtime/config"
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=0 RICEBOWL_DE_SCREEN_READER=1
export RICEBOWL_DE_TRACE_FILES=1 RICEBOWL_DE_TRACE_MENU=1
export PATH="$root/components/riceplate-wayland/target/release:$PATH"
# Own the entire XDG Desktop for the Rename fixture; never inspect the runner
# or the user's actual home directory.
mkdir -m 0700 "$runtime/file-home" "$runtime/file-home/Desktop"
printf '%s\n' 'XDG_DESKTOP_DIR="$HOME/Desktop"' > "$runtime/config/user-dirs.dirs"
printf '%s\n' 'SG5 isolated fixture' > "$runtime/file-home/Desktop/00-sg5.txt"
export HOME="$runtime/file-home"

# Native recipe ownership contract: never launch directly from a world-readable
# checkout. Keep all runtime inputs in a private disposable directory.
cp "$root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
chmod 0600 "$runtime/luna.json"

python3 - "$root" "$runtime" <<'PY'
from pathlib import Path
import sys
root, runtime = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
from macrice.de import luna_hotkeys, recipes, session
rice = recipes.parse((root / "examples/wayland/xp-luna-columns.json").read_bytes())
config = session._custom_labwc_config(rice, str(runtime), native_luna_hotkeys=True)
assert luna_hotkeys.commands((config / "rc.xml").read_text())["W-r"] == \
    "riceplate-native --desktop-command run"
(runtime / "config-path").write_text(str(config))
PY

dbus-run-session -- sh -eu -c '
    root=$1; runtime=$2; native=$3; ime=$4; clicker=$5; probe_bin=$6
    export WAYLAND_DISPLAY=wayland-0
    labwc --config-dir "$(cat "$runtime/config-path")" >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    plate=; imepid=; keyboard_keeper=; copy_owner=; invalid_owner=; launcher=
    cleanup() {
        for pid in "$launcher" "$invalid_owner" "$copy_owner" "$imepid" "$keyboard_keeper" "$plate" "$compositor"; do
            if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || :; fi
        done
        for pid in "$launcher" "$invalid_owner" "$copy_owner" "$imepid" "$keyboard_keeper" "$plate" "$compositor"; do
            if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || :; fi
        done
    }
    trap cleanup EXIT

    count=0
    while [ "$count" -lt 50 ] && [ ! -S "$runtime/wayland-0" ]; do
        kill -0 "$compositor" 2>/dev/null || {
            sed -n "1,100p" "$runtime/labwc.log" >&2; exit 1;
        }
        count=$((count + 1)); sleep 0.2
    done
    test -S "$runtime/wayland-0" || { echo "labwc socket missing" >&2; exit 1; }

    # A real desktop has a keyboard continuously attached to the wl_seat.
    # One-shot wtype hotkey/text probes otherwise remove keyboard capability
    # between events and can silently revoke the Run layer focus before the
    # AT-SPI snapshot, creating a false negative (focused=False). Keep an
    # inert F13 keyboard on the same disposable labwc seat for the full test.
    wtype -k F13 -s 1800000 -k F13 >"$runtime/keyboard-keeper.log" 2>&1 &
    keyboard_keeper=$!
    sleep 0.3
    kill -0 "$keyboard_keeper" 2>/dev/null || {
        echo "Disposable keyboard keeper failed before Run focus" >&2
        cat "$runtime/keyboard-keeper.log" >&2
        exit 1
    }
    output=$(wlr-randr | sed -n "1s/[[:space:]].*//p")
    test -n "$output"
    wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1

    # Real desktops have an AT-SPI registry before applications register;
    # make this disposable session obey the same ordering.
    /usr/bin/python3 -c "import pyatspi; pyatspi.Registry.getDesktop(0).childCount" >/dev/null

    # The AccessKit Unix adapter waits for org.a11y.Status.IsEnabled. A
    # disposable headless DBus session defaults to false even with pyatspi
    # installed: explicitly emulate a screen reader enabling accessibility.
    # This setting exists ONLY on the private dbus-run-session bus.
    # Await the Properties.Set D-Bus reply before querying from a second
    # connection: fire-and-forget can race the following Get on headless CI.
    dbus-send --session --print-reply --reply-timeout=5000 \
        --dest=org.a11y.Bus /org/a11y/bus \
        org.freedesktop.DBus.Properties.Set \
        string:org.a11y.Status string:IsEnabled variant:boolean:true
    a11y_status=$(gdbus call --session --dest org.a11y.Bus \
        --object-path /org/a11y/bus \
        --method org.freedesktop.DBus.Properties.Get \
        org.a11y.Status IsEnabled)
    case "$a11y_status" in
        *true*) : ;;
        *) echo "Headless accessibility status not enabled: $a11y_status" >&2; exit 1 ;;
    esac

    "$native" --recipe "$runtime/luna.json" \
        >"$runtime/native.log" 2>&1 &
    plate=$!
    count=0
    while [ "$count" -lt 50 ] && [ ! -S "$runtime/riceplate-luna-desktop.sock" ]; do
        kill -0 "$plate" 2>/dev/null || {
            sed -n "1,100p" "$runtime/native.log" >&2; exit 1;
        }
        count=$((count + 1)); sleep 0.2
    done
    test -S "$runtime/riceplate-luna-desktop.sock" || exit 1
    probe() {
        if timeout -k 2s 14s /usr/bin/python3 "$root/scripts/smoke_riceplate_atspi_client.py" "$@"; then
            return 0
        fi
        echo "RicePlate diagnostics after missing AT-SPI text node:" >&2
        sed -n "1,100p" "$runtime/native.log" >&2
        sed -n "1,60p" "$runtime/labwc.log" >&2
        return 1
    }

    start_menu_ime() {
        name=$1
        timeout -k 2s 18s "$ime" "$runtime/$name-preedit-observed" >"$runtime/$name-ime.log" 2>&1 &
        imepid=$!
    }

    check_menu_ime() {
        name=$1
        label=$2
        if ! probe --name "$label" --text "にほんご" --caret 4; then
            cat "$runtime/$name-ime.log" >&2
            if [ "${RICEBOWL_SG5_PROTOCOL_TRACE:-0}" = 1 ]; then
                grep -E "text_input_v3|input_method_v2" "$runtime/native.log" | tail -n 80 >&2
            fi
            return 1
        fi
        : >"$runtime/$name-preedit-observed"
        wait "$imepid" || { cat "$runtime/$name-ime.log" >&2; exit 1; }
        imepid=
        grep -Fq "PASS: real IME v2 -> labwc -> text-input-v3 preedit/commit/delete" "$runtime/$name-ime.log"
        probe --name "$label" --text "日本界" --caret 3
        wtype -k Escape
        probe --name "$label" --absent
        echo "SG5: real menu IME preedit/commit/delete and AT-SPI teardown for $name PASS"
    }

    # SG5: Wayland Start menu text really reaches AccessKit/AT-SPI.
    # Groups have no editable query; Escape must revoke the transient run.
    "$clicker" 35 748 1366 768
    probe --name "Search applications and actions" --absent
    wtype -k slash
    probe --name "Search applications and actions" --text "" --caret 0
    wtype "lib/abc"
    probe --name "Search applications and actions" --text "lib/abc" --caret 7
    wtype -M ctrl -k x -m ctrl
    probe --name "Search applications and actions" --text "lib/abc" --caret 7
    wtype -k BackSpace
    probe --name "Search applications and actions" --text "lib/ab" --caret 6
    wtype -k Escape
    probe --name "Search applications and actions" --absent
    start_menu_ime search
    wtype -k slash
    check_menu_ime search "Search applications and actions"
    wtype -k Escape
    kill -0 "$plate"
    echo "SG5: real Start search keyboard/AT-SPI focus/text/teardown PASS"

    # All Programs is a separate native editable view; an accessible Search
    # node does not prove that its filter has the same compositor behavior.
    # Use the exact on-screen menu geometry from the native labwc trace,
    # not an obsolete hard-coded bitmap or a synthetic Rust model.
    # Re-enter the launcher from a neutral point so stale pointer focus from
    # the preceding Escape does not silently lose the opener click.
    "$clicker" --move-only 600 400 1366 768
    sleep 0.15
    "$clicker" 35 748 1366 768
    probe --name "Filter installed apps" --absent
    menu_size=$(sed -n "s/.*menu trace show Some(((\\([0-9][0-9]*\\), \\([0-9][0-9]*\\)), true)).*/\\1 \\2/p" \
        "$runtime/native.log" | tail -n 1)
    [ "$menu_size" = "480 456" ] || {
        echo "SG5: 1366x768 native Luna menu geometry unverified: $menu_size" >&2
        exit 1
    }
    set -- $menu_size
    menu_w=$1
    menu_h=$2
    # Exact same logical hitbox (60,256) as the native E2E fixture.
    "$clicker" "$((60 * menu_w / 320))" \
        "$((768 - 40 - menu_h + 256 * menu_h / 304))" 1366 768
    probe --name "Filter installed apps" --text "" --caret 0
    wtype "abc"
    probe --name "Filter installed apps" --text "abc" --caret 3
    wtype -k BackSpace
    probe --name "Filter installed apps" --text "ab" --caret 2
    wtype -k Escape
    probe --name "Filter installed apps" --absent
    start_menu_ime programs
    "$clicker" "$((60 * menu_w / 320))" \
        "$((768 - 40 - menu_h + 256 * menu_h / 304))" 1366 768
    check_menu_ime programs "Filter installed apps"
    wtype -k Escape
    kill -0 "$plate"
    echo "SG5: real All Programs filter keyboard/AT-SPI focus/text/teardown PASS"

    wtype -M logo -k r -m logo
    probe --text "" --caret 0
    wtype "AB"
    probe --text "AB" --caret 2
    wtype -k Left
    probe --text "AB" --caret 1
    wtype -k BackSpace
    probe --text "B" --caret 0
    wtype -M ctrl -k a -m ctrl
    probe --text "B" --caret 1 --selection 0 1
    wtype "Z"
    probe --text "Z" --caret 1
    wtype -k BackSpace
    probe --text "" --caret 0
    wtype -k Escape
    probe --absent
    # Cross-process clipboard verification, not a fake in-process paste.
    # The external wl-copy process is an actual Wayland selection owner.
    command -v wl-copy >/dev/null
    command -v wl-paste >/dev/null
    fixture="A👩‍💻é🇩🇪"
    wl-copy --foreground --type "text/plain;charset=utf-8" "$fixture" \
        >"$runtime/clipboard-owner.log" 2>&1 &
    copy_owner=$!
    sleep 0.3
    kill -0 "$copy_owner" || { echo "External Wayland clipboard source died" >&2; exit 1; }
    wtype -M logo -k r -m logo
    probe --text "" --caret 0
    wtype -M ctrl -k v -m ctrl
    # AT-SPI indices are Unicode scalar offsets, while native cursor and
    # selection remain grapheme-safe across ZWJ, accents and flags.
    probe --text "$fixture" --caret 8
    wtype -M ctrl -k a -m ctrl
    probe --text "$fixture" --caret 8 --selection 0 8
    wtype -M ctrl -k c -m ctrl
    received=$(timeout 4s wl-paste --no-newline --type "text/plain;charset=utf-8")
    test "$received" = "$fixture" || {
        echo "SG5: native Ctrl+C not served over Wayland selection" >&2; exit 1;
    }
    wtype -M ctrl -k x -m ctrl
    probe --text "" --caret 0
    received=$(timeout 4s wl-paste --no-newline --type "text/plain;charset=utf-8")
    test "$received" = "$fixture" || {
        echo "SG5: native Ctrl+X lost clipboard ownership" >&2; exit 1;
    }
    wtype -M ctrl -k v -m ctrl
    probe --text "$fixture" --caret 8

    # A malformed external selection must not partially overwrite Run.
    invalid=$(printf "bad\ninput")
    wl-copy --foreground --type "text/plain;charset=utf-8" "$invalid" \
        >"$runtime/clipboard-invalid-owner.log" 2>&1 &
    invalid_owner=$!
    sleep 0.25
    wtype -M ctrl -k a -m ctrl
    probe --text "$fixture" --caret 8 --selection 0 8
    wtype -M ctrl -k v -m ctrl
    probe --text "$fixture" --caret 8 --selection 0 8
    if grep -F "$fixture" "$runtime/native.log" >/dev/null; then
        echo "SG5: clipboard text was logged" >&2; exit 1;
    fi
    wtype -k Escape
    probe --absent
    echo "SG5: real wl-copy -> Run paste, Run copy/cut -> wl-paste, Unicode and invalid text PASS"
    # SG5 missing-font matrix with a real compositor and accessible client.
    # The Run editor face (bundled Latin Liberation Sans) has no Devanagari,
    # CJK or Hangul glyphs. The editor must (a) keep the real text in the
    # public AT-SPI tree and (b) paint exactly one visible replacement per
    # grapheme: its pixels must equal a run of literal "?" and differ from the
    # empty field. This proves visible replacement, NOT script coverage.
    command -v grim >/dev/null
    shot() { sleep 0.4; grim -g "577,359 306x32" "$runtime/$1.png"; }
    pixels() { /usr/bin/python3 "$root/scripts/sg5_png_compare.py" "$1" "$2" "$3"; }
    wtype -M logo -k r -m logo
    probe --text "" --caret 0
    shot empty
    wtype -k Escape
    probe --absent
    check_missing_font() {
        tag=$1; text=$2; chars=$3; replacement=$4
        wtype -M logo -k r -m logo
        probe --text "" --caret 0
        wtype "$text"
        probe --text "$text" --caret "$chars"
        shot "$tag-script"
        wtype -k Escape
        probe --absent
        wtype -M logo -k r -m logo
        probe --text "" --caret 0
        wtype "$replacement"
        probe --text "$replacement" --caret "${#replacement}"
        shot "$tag-question"
        wtype -k Escape
        probe --absent
        pixels "$runtime/$tag-script.png" "$runtime/$tag-question.png" same || {
            echo "SG5: $tag missing glyphs were not painted as one replacement per grapheme" >&2
            exit 1
        }
        pixels "$runtime/$tag-script.png" "$runtime/empty.png" different || {
            echo "SG5: $tag missing glyphs painted nothing (invisible text)" >&2
            exit 1
        }
    }
    check_missing_font hindi "हिन्दी" 6 "??"
    check_missing_font cjk "日本語" 3 "???"
    check_missing_font hangul "한국어" 3 "???"
    kill -0 "$plate"
    echo "SG5: missing-font Hindi/CJK/Hangul: AT-SPI keeps real text, replacement pixels visible, no coverage claimed PASS"
    # Register a separate input-method-v2 producer *before* re-focusing Run.
    # Its preedit, commit and byte deletion must traverse labwc to the
    # unmodified text-input-v3 application and return as surrounding text.
    timeout -k 2s 16s "$ime" >"$runtime/ime.log" 2>&1 &
    imepid=$!
    sleep 0.3
    wtype -M logo -k r -m logo
    if ! wait "$imepid"; then
        echo "External IME v2 -> text-input-v3 transaction failed:" >&2
        sed -n "1,100p" "$runtime/ime.log" >&2
        sed -n "1,90p" "$runtime/native.log" >&2
        exit 1
    fi
    imepid=
    probe --text "日本界" --caret 3
    wtype -k Escape
    probe --absent
    kill -0 "$plate"
    # Rename must be a real, compositor-opened editable AT-SPI surface,
    # not a synthetic AccessKit tree node or a Rust-only unit test. The
    # XDG Desktop file belongs exclusively to the disposable HOME.
    count=0
    position=
    while [ "$count" -lt 40 ]; do
        position=$(sed -n "s/.*XDG mapped x=\([0-9][0-9]*\) y=\([0-9][0-9]*\) kind=File.*/\1 \2/p" \
            "$runtime/native.log" | head -n 1)
        [ -n "$position" ] && break
        kill -0 "$plate" || exit 1
        count=$((count + 1)); sleep 0.2
    done
    test -n "$position" || {
        echo "SG5: isolated XDG file surface not mapped" >&2
        sed -n "1,90p" "$runtime/native.log" >&2
        exit 1
    }
    set -- $position
    file_x=$(($1 + 52))
    file_y=$(($2 + 43))
    open_file_context() {
        # Real secondary click on the Desktop file. Count log lines so a second
        # open never reuses the first openings context receipt.
        before=$(grep -c "XDG context opened kind=File" "$runtime/native.log" || :)
        "$clicker" --right-click "$file_x" "$file_y" 1366 768
        count=0
        origin=
        while [ "$count" -lt 30 ]; do
            now=$(grep -c "XDG context opened kind=File" "$runtime/native.log" || :)
            if [ "$now" -gt "$before" ]; then
                origin=$(sed -n "s/.*XDG context opened kind=File x=\([0-9][0-9]*\) y=\([0-9][0-9]*\).*/\1 \2/p" \
                    "$runtime/native.log" | tail -n 1)
                [ -n "$origin" ] && break
            fi
            count=$((count + 1)); sleep 0.2
        done
        test -n "$origin" || {
            echo "SG5: Wayland secondary click did not open XDG file context" >&2
            exit 1
        }
        set -- $origin
        menu_x=$1; menu_y=$2
    }
    open_rename() {
        # Real secondary click, then the real pointer click on the Rename item.
        open_file_context
        "$clicker" "$((menu_x + 24))" "$((menu_y + 111))" 1366 768
    }
    open_rename_atspi() {
        # Same context menu, but the Rename item is invoked through the public
        # AT-SPI action interface (doAction) instead of a pointer click.
        open_file_context
        probe --do-action "Rename  (F2)" --role menu-item
    }
    wait_marker() {
        count=0
        while [ "$count" -lt 150 ] && [ ! -e "$runtime/rename-cycle/$1" ]; do
            kill -0 "$imepid" 2>/dev/null || {
                echo "SG5: Rename IME client ended before marker $1" >&2
                cat "$runtime/rename-ime.log" >&2
                exit 1
            }
            count=$((count + 1)); sleep 0.1
        done
        test -e "$runtime/rename-cycle/$1" || {
            echo "SG5: Rename IME marker $1 missing" >&2
            cat "$runtime/rename-ime.log" "$runtime/rename-focus-probe.log" >&2 2>/dev/null || :
            kill -0 "$launcher" 2>/dev/null && echo "launcher still running" >&2
            tail -n 20 "$runtime/labwc.log" >&2
            exit 1
        }
    }
    wait_log() {
        count=0
        while [ "$count" -lt 100 ] && ! grep -Fq "$2" "$runtime/$1"; do
            count=$((count + 1)); sleep 0.1
        done
        grep -Fq "$2" "$runtime/$1" || fail_rename_ime "receipt missing in $1: $2"
    }
    wait_trace() { wait_log native.log "$1"; }
    fail_rename_ime() {
        echo "SG5: Rename IME focus cycle failed: $1" >&2
        cat "$runtime/rename-ime.log" "$runtime/rename-focus-probe.log" >&2 2>/dev/null || :
        grep -E "text_input_v3|input_method_v2|Luna Run/Help|Luna dialog IME" "$runtime/native.log" | tail -n 40 >&2 || :
        exit 1
    }

    # SG5 Rename IME: the external input-method-v2 producer is registered
    # before the dialog exists, exactly like the Run fixture. Preedit, commit
    # and a 3-byte UTF-8 deletion must traverse labwc into the unmodified
    # text-input-v3 Rename consumer; then a real compositor focus change
    # (a second exclusive layer client, fuzzel) must leave and re-enter it.
    mkdir -m 0700 "$runtime/rename-cycle"
    timeout -k 2s 40s "$ime" --base "00-sg5.txt" --focus-cycle "$runtime/rename-cycle" \
        "$runtime/rename-cycle/preedit-observed" >"$runtime/rename-ime.log" 2>&1 &
    imepid=$!
    sleep 0.3
    open_rename
    probe --name "File name" --text "00-sg5.txt" --caret 10 || fail_rename_ime "initial text"
    # The accessible text is the committed text only; the compositor-relayed
    # preedit is proven by the native receipt (sizes only, never the text).
    wait_trace "Luna dialog IME done preedit_chars=4 chars=10 caret=10"
    probe --name "File name" --text "00-sg5.txt" --caret 10 || fail_rename_ime "preedit leaked into text"
    : >"$runtime/rename-cycle/preedit-observed"
    wait_marker preedit-active
    wait_trace "Luna dialog IME done preedit_chars=3 chars=13 caret=13"
    probe --name "File name" --text "00-sg5.txt日本界" --caret 13 || fail_rename_ime "commit/delete/second preedit"
    # Leave: the focus probe is a second, separate Wayland client holding an
    # Exclusive-keyboard Overlay layer surface. labwc must move keyboard (and
    # therefore text-input) focus to it; the Rename dialog is retained but
    # unfocused and the IME must see a real deactivate.
    "$probe_bin" overlay exclusive >"$runtime/rename-focus-probe.log" 2>&1 &
    launcher=$!
    wait_marker left
    wait_log rename-focus-probe.log "event=keyboard_enter"
    kill -0 "$launcher" 2>/dev/null || fail_rename_ime "focus-taking launcher died"
    kill -0 "$plate"
    wait_trace "Luna dialog IME leave dropped_preedit=true"
    wait_trace "Luna Run/Help keyboard leave, dialog retained"
    # Re-enter: the probe exits on Escape (delivered by labwc to it, not to
    # Rename); labwc then returns exclusive focus to the Rename dialog.
    wtype -k Escape
    wait "$launcher" || fail_rename_ime "focus probe did not exit cleanly"
    launcher=
    wait_log rename-focus-probe.log "event=keyboard_press count=1"
    wait_marker reentered
    probe --name "File name" --text "00-sg5.txt日本界" --caret 13 || fail_rename_ime "text after re-enter"
    : >"$runtime/rename-cycle/verified"
    if ! wait "$imepid"; then
        fail_rename_ime "IME client failed"
    fi
    imepid=
    grep -Fq "PASS: real IME v2 -> labwc -> text-input-v3 preedit/commit/delete" "$runtime/rename-ime.log"
    grep -Fq "PASS: real IME v2 focus leave/re-enter" "$runtime/rename-ime.log"
    probe --name "File name" --text "00-sg5.txt日本界文" --caret 14
    wtype -k Escape
    probe --name "File name" --absent
    test -f "$runtime/file-home/Desktop/00-sg5.txt"
    test "$(ls -A "$runtime/file-home/Desktop")" = "00-sg5.txt"
    kill -0 "$plate"
    echo "SG5: real Rename IME preedit/commit/delete, focus leave/re-enter and cancel PASS"

    open_rename
    probe --name "File name" --text "00-sg5.txt" --caret 10
    wtype -k Home
    probe --name "File name" --text "00-sg5.txt" --caret 0
    wtype -M ctrl -k a -m ctrl
    probe --name "File name" --text "00-sg5.txt" --caret 10 --selection 0 10
    wtype -M ctrl -k c -m ctrl
    received=$(timeout 4s wl-paste --no-newline --type "text/plain;charset=utf-8")
    test "$received" = "00-sg5.txt" || {
        echo "SG5: Rename selection not published through Wayland" >&2; exit 1;
    }
    wtype -M ctrl -k x -m ctrl
    probe --name "File name" --text "" --caret 0
    wtype -M ctrl -k v -m ctrl
    probe --name "File name" --text "00-sg5.txt" --caret 10
    wtype -M ctrl -k a -m ctrl
    probe --name "File name" --text "00-sg5.txt" --caret 10 --selection 0 10
    wtype "Z"
    probe --name "File name" --text "Z" --caret 1
    wtype -k Escape
    probe --name "File name" --absent
    test -f "$runtime/file-home/Desktop/00-sg5.txt"
    test ! -e "$runtime/file-home/Desktop/Z"
    kill -0 "$plate"
    echo "SG5: real Wayland pointer -> XDG Rename AT-SPI edit/selection/cancel PASS"

    # SG5 AT-SPI action invocation: every transition below is driven through
    # the public accessibility action interface (doAction), never a pointer or
    # keyboard shortcut. The filesystem is the receipt, not a UI claim.
    desk="$runtime/file-home/Desktop"
    # Rename -> unchanged name is refused: the dialog stays open, nothing moves.
    open_rename_atspi
    probe --name "File name" --text "00-sg5.txt" --caret 10
    probe --do-action "Rename" --role button
    probe --name "File name" --text "00-sg5.txt" --caret 10
    test "$(ls -A "$desk")" = "00-sg5.txt"
    # Rename -> Cancel via action: dialog closes, file NOT renamed.
    wtype -M ctrl -k a -m ctrl
    wtype "renamed.txt"
    probe --name "File name" --text "renamed.txt" --caret 11
    probe --do-action "Cancel" --role button
    probe --name "File name" --absent
    test "$(ls -A "$desk")" = "00-sg5.txt"
    # Run dialog: Cancel via action does not execute, OK via action does.
    wtype -M logo -k r -m logo
    probe --text "" --caret 0
    cancelled="touch $runtime/run-cancelled-marker"
    wtype "$cancelled"
    probe --text "$cancelled" --caret "${#cancelled}"
    probe --do-action "Cancel" --role button
    probe --absent
    wtype -M logo -k r -m logo
    probe --text "" --caret 0
    wtype "touch $runtime/run-ok-marker"
    probe --do-action "OK" --role button
    probe --absent
    count=0
    while [ "$count" -lt 30 ] && [ ! -e "$runtime/run-ok-marker" ]; do
        count=$((count + 1)); sleep 0.1
    done
    test -e "$runtime/run-ok-marker"
    test ! -e "$runtime/run-cancelled-marker"
    # Rename -> new name -> action confirm: the file is really renamed.
    open_rename_atspi
    probe --name "File name" --text "00-sg5.txt" --caret 10
    wtype -M ctrl -k a -m ctrl
    wtype "renamed.txt"
    probe --name "File name" --text "renamed.txt" --caret 11
    probe --do-action "Rename" --role button
    probe --name "File name" --absent
    test "$(ls -A "$desk")" = "renamed.txt"
    test "$(cat "$desk/renamed.txt")" = "SG5 isolated fixture"
    kill -0 "$plate"
    echo "SG5: AT-SPI doAction Rename menu item, Rename/Cancel/OK buttons, refused/cancelled/confirmed transitions PASS"
    echo "SG5: real labwc keyboard, external input-method-v2 and AT-SPI lifecycle PASS"
' sh "$root" "$runtime" "$native" "$ime" "$clicker" "$probe_bin"

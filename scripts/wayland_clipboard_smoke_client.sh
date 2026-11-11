#!/bin/sh
# Runs ONLY as a child of a disposable headless labwc compositor in CI.
# DISPLAY and WAYLAND_DISPLAY come from that compositor, not the host desktop.
set -eu

runtime=$1
source_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
test -n "${DISPLAY:-}" || { echo "Missing compositor-provided X11 DISPLAY" >&2; exit 1; }
test -n "${WAYLAND_DISPLAY:-}" || { echo "Missing compositor-provided WAYLAND_DISPLAY" >&2; exit 1; }

wayland_owner=
x11_owner=
x11_window=
clip_monitor=
cleanup() {
    if [ -n "$clip_monitor" ]; then kill "$clip_monitor" 2>/dev/null || :; wait "$clip_monitor" 2>/dev/null || :; fi
    if [ -n "$wayland_owner" ]; then kill "$wayland_owner" 2>/dev/null || :; wait "$wayland_owner" 2>/dev/null || :; fi
    if [ -n "$x11_owner" ]; then kill "$x11_owner" 2>/dev/null || :; wait "$x11_owner" 2>/dev/null || :; fi
    if [ -n "$x11_window" ]; then kill "$x11_window" 2>/dev/null || :; wait "$x11_window" 2>/dev/null || :; fi
}
finish() {
    status=$?
    cleanup
    if [ "$status" -ne 0 ]; then printf '%s\n' FAILED >"$runtime/clipboard-failed"; fi
}
trap finish EXIT

wait_for_clipboard() {
    reader=$1
    expected=$2
    count=0
    while [ "$count" -lt 20 ]; do
        if [ "$reader" = x11 ]; then
            actual=$(timeout 1s xclip -selection clipboard -out 2>/dev/null || :)
        else
            actual=$(timeout 1s wl-paste --no-newline 2>/dev/null || :)
        fi
        if [ "$actual" = "$expected" ]; then return 0; fi
        sleep 0.2
        count=$((count + 1))
    done
    echo "Clipboard $reader did not receive expected synthetic text (last received: '$actual')" >&2
    return 1
}

# wlroots restricts X11 clipboard reads to a focused XWayland client. A
# clipboard-only xclip process is not an active window, so it cannot prove
# interoperability on its own. Exercise the real compositor focus path with
# an actual mapped legacy client before acquiring the selection.
xterm -class RiceBowlClipboardSmoke -title RiceBowl-Clipboard-Smoke \
    -e sh -c 'touch "$1"; sleep 40' sh "$runtime/xterm-ready" \
    >"$runtime/xterm.log" 2>&1 &
x11_window=$!
count=0
while [ ! -f "$runtime/xterm-ready" ] && [ "$count" -lt 40 ]; do
    kill -0 "$x11_window" 2>/dev/null || { echo 'XWayland test window exited early' >&2; exit 1; }
    sleep 0.25
    count=$((count + 1))
done
test -f "$runtime/xterm-ready" || { echo 'XWayland test window did not start' >&2; exit 1; }
sleep 0.3

# Keep the Wayland owner alive: unlike a clipboard manager, labwc does not
# persist copied content after the source exits.
wl-copy --foreground --type text/plain 'ricebowl-wayland-to-x11-42' \
    >"$runtime/wl-copy.log" 2>&1 &
wayland_owner=$!
wait_for_clipboard wayland 'ricebowl-wayland-to-x11-42'
wait_for_clipboard x11 'ricebowl-wayland-to-x11-42'
echo 'Wayland clipboard reached XWayland'

printf '%s' 'ricebowl-x11-to-wayland-73' >"$runtime/x11-text"
xclip -quiet -selection clipboard -in "$runtime/x11-text" \
    >"$runtime/xclip.log" 2>&1 &
x11_owner=$!
wait_for_clipboard wayland 'ricebowl-x11-to-wayland-73'
echo 'XWayland clipboard reached native Wayland'

# Reuse this *same real labwc session* for RiceClip's opt-in text watcher.
# All text below is fixed synthetic CI data and never comes from the host.
# This checks data-control watch/receiver/Unix socket/selection restoration,
# beyond the mocked socket tests run by the ordinary Python test workflow.
clip_cli() {
    /usr/bin/python3 -B "$source_root/launcher.py" de clip "$@"
}
clip_cli --clip-op watch --json >"$runtime/riceclip-watch.log" 2>&1 &
clip_monitor=$!
count=0
while [ "$count" -lt 50 ]; do
    if clip_cli --clip-op status --json >"$runtime/riceclip-status.json" 2>/dev/null; then
        break
    fi
    kill -0 "$clip_monitor" 2>/dev/null || {
        echo 'RiceClip watcher exited before accepting requests' >&2
        sed -n '1,35p' "$runtime/riceclip-watch.log" >&2
        exit 1
    }
    sleep 0.1
    count=$((count + 1))
done
test "$count" -lt 50 || { echo 'RiceClip never created its private runtime socket' >&2; exit 1; }
clip_cli --clip-op clear --json >/dev/null

clip_text='riceclip-Luna-über-Wayland-✓'
wl-copy --type 'text/plain;charset=utf-8' "$clip_text"
count=0
while [ "$count" -lt 50 ]; do
    if clip_cli --clip-op list --json >"$runtime/riceclip-list.json" &&
        grep -Fq '"preview": "riceclip-Luna-über-Wayland-✓"' "$runtime/riceclip-list.json"; then
        break
    fi
    sleep 0.1
    count=$((count + 1))
done
test "$count" -lt 50 || {
    echo 'RiceClip did not receive synthetic Wayland text event' >&2
    sed -n '1,35p' "$runtime/riceclip-watch.log" >&2
    exit 1
}
clip_cli --clip-op copy --clip-index 0 --json >"$runtime/riceclip-copy.json"
wait_for_clipboard wayland "$clip_text"
clip_cli --clip-op clear --json >/dev/null
clip_cli --clip-op status --json >"$runtime/riceclip-status.json"
grep -Fq '"count": 0' "$runtime/riceclip-status.json"
kill "$clip_monitor"
wait "$clip_monitor" 2>/dev/null || :
clip_monitor=
if clip_cli --clip-op status --json >/dev/null 2>&1; then
    echo 'RiceClip retained a live socket after its watcher exited' >&2
    exit 1
fi
echo 'RiceClip bounded text watch, private IPC, copy-back and teardown passed in labwc'
printf '%s\n' OK >"$runtime/clipboard-ok"

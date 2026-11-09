#!/bin/sh
# Runs ONLY as a child of a disposable headless labwc compositor in CI.
# DISPLAY and WAYLAND_DISPLAY come from that compositor, not the host desktop.
set -eu

runtime=$1
test -n "${DISPLAY:-}" || { echo "Missing compositor-provided X11 DISPLAY" >&2; exit 1; }
test -n "${WAYLAND_DISPLAY:-}" || { echo "Missing compositor-provided WAYLAND_DISPLAY" >&2; exit 1; }

wayland_owner=
x11_owner=
cleanup() {
    if [ -n "$wayland_owner" ]; then kill "$wayland_owner" 2>/dev/null || :; wait "$wayland_owner" 2>/dev/null || :; fi
    if [ -n "$x11_owner" ]; then kill "$x11_owner" 2>/dev/null || :; wait "$x11_owner" 2>/dev/null || :; fi
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
    echo "Clipboard $reader did not receive expected synthetic text" >&2
    return 1
}

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
printf '%s\n' OK >"$runtime/clipboard-ok"

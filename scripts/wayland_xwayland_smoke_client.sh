#!/bin/sh
# Started exclusively by disposable headless labwc in CI. Inherits its real
# DISPLAY/XAUTHORITY so the test exercises the compositor-managed XWayland.
set -eu

runtime=$1
test -n "${DISPLAY:-}" || { echo "labwc did not export XWayland DISPLAY" >&2; exit 1; }
count=0
while [ ! -f "$runtime/launch-client" ] && [ "$count" -lt 100 ]; do
    sleep 0.1
    count=$((count + 1))
done
test -f "$runtime/launch-client" || exit 1
printf '%s\n' "$$" >"$runtime/client.pid"
# The X11 client writes a receipt only after *real terminal input* delivered
# through the compositor's Wayland seat and XWayland. The outer smoke verifies
# that this isn't just a taskbar/screenshot-only XWayland test. Set both
# WM_CLASS fields so labwc versions reporting either field agree on the ID.
export RICEBOWL_XWAYLAND_RECEIPT="$runtime/xwayland-typed.txt"
exec xterm -name RiceBowlXwaylandSmoke -class RiceBowlXwaylandSmoke -title RiceBowl-Legacy-Smoke \
    -geometry 80x24+200+130 -e /bin/sh -c '
    stty -echo
    IFS= read -r received || exit 1
    [ "$received" = "ricebowl-xwayland-ok" ] || exit 2
    printf "%s\n" "$received" > "$RICEBOWL_XWAYLAND_RECEIPT"
    sleep 30
'

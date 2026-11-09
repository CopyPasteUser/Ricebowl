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
exec xterm -class RiceBowlXwaylandSmoke -title RiceBowl-Legacy-Smoke \
    -e /bin/sh -c 'sleep 30'

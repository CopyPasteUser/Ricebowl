#!/bin/sh
# Called by labwc --startup to inherit its real XWayland DISPLAY/XAUTHORITY.
set -eu
runtime=$1
test -n "${DISPLAY:-}" || { echo 'Missing labwc XWayland DISPLAY' >&2; exit 1; }
count=0
while [ ! -f "$runtime/launch-client" ] && [ "$count" -lt 100 ]; do
    sleep 0.1
    count=$((count + 1))
done
test -f "$runtime/launch-client" || exit 1
printf '%s\n' "$$" >"$runtime/client.pid"
exec xterm -class RiceBowlLunaChrome -title 'RiceBowl Luna - Window Chrome' \
    -geometry 76x18+420+190 -fa DejaVuSansMono -fs 11 \
    -bg '#fffdf1' -fg '#193c67' \
    -e /bin/sh -c 'printf "RiceBowl Luna - real XWayland window\nPrivate labwc chrome and reversible rice switching\n"; exec sleep 30'

#!/bin/sh
# Spawned only from the test compositor after the Wayland socket exists.
set -eu
root=$1
runtime=$2
finish() {
    status=$?
    if [ "$status" -ne 0 ]; then
        printf 'FAILED\n' >"$runtime/portals-failed"
    fi
}
trap finish EXIT
test -n "${WAYLAND_DISPLAY:-}" || {
    echo "No compositor-provided WAYLAND_DISPLAY" >&2; exit 1;
}
dbus-update-activation-environment \
    WAYLAND_DISPLAY XDG_RUNTIME_DIR XDG_CONFIG_HOME \
    XDG_CURRENT_DESKTOP XDG_SESSION_TYPE XDG_SESSION_DESKTOP
timeout -k 2s 18s /usr/bin/python3 "$root/scripts/check_wayland_portals.py" \
    --timeout 12
timeout -k 2s 45s /usr/bin/python3 "$root/scripts/wayland_portal_capture_smoke.py"
printf 'OK\n' >"$runtime/portals-ok"

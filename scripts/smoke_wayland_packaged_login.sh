#!/bin/sh
# CI-only: boot the INSTALLED Wayland login wrapper, not the source checkout.
# Must run inside the throwaway Ubuntu package-install container.
set -eu
if [ "${RICEBOWL_PACKAGED_CI:-}" != 1 ] || [ ! -f /.dockerenv ] || [ "$(id -u)" != 0 ]; then
    echo 'Refusing to run packaged login smoke outside its disposable root container' >&2
    exit 2
fi
for tool in runuser dbus-run-session labwc grim wayland-info pgrep; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "Packaged login smoke missing $tool" >&2; exit 1;
    }
done
test -x /usr/bin/ricebowl-wayland-session
test -x /usr/bin/ricebowl-wayland-app
test -x /usr/bin/riceplate-native

useradd -m -u 22003 -s /bin/sh ricebowl-smoke
runtime=$(mktemp -d -t ricebowl-installed-XXXXXXXX)
chmod 0700 "$runtime"
chown ricebowl-smoke:ricebowl-smoke "$runtime"
trap 'rm -rf -- "$runtime"' EXIT

# The only writable desktop state is under this private, throwaway runtime.
# No host display, user home or XFCE configuration is mounted into Docker.
runuser -u ricebowl-smoke -- env \
    HOME=/home/ricebowl-smoke \
    XDG_RUNTIME_DIR="$runtime" \
    XDG_CONFIG_HOME="$runtime/config" \
    XDG_DATA_HOME="$runtime/data" \
    XDG_CACHE_HOME="$runtime/cache" \
    XDG_SESSION_TYPE=wayland \
    WLR_BACKENDS=headless \
    WLR_HEADLESS_OUTPUTS=1 \
    WLR_RENDERER=pixman \
    dbus-run-session -- sh -eu -c '
    runtime=$1
    session=
    cleanup() {
        if [ -n "$session" ]; then
            kill "$session" 2>/dev/null || :
            wait "$session" 2>/dev/null || :
        fi
    }
    trap cleanup EXIT

    /usr/bin/ricebowl-wayland-app de check --json >"$runtime/preflight.json"
    /usr/bin/python3 -c '\''
import json, sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
assert report["login_prerequisites_ready"], report
assert report["native_login_prerequisites_ready"], report
assert report["standalone_de_ready"] is False
'\'' "$runtime/preflight.json"

    # Runs the actual .desktop Exec target without a display manager. The
    # wrapper selects the packaged app, then labwc starts native RicePlate.
    /usr/bin/ricebowl-wayland-session --native >"$runtime/session.log" 2>&1 &
    session=$!
    ready=0
    attempt=0
    while [ "$attempt" -lt 80 ]; do
        kill -0 "$session" 2>/dev/null || break
        if [ -S "$runtime/wayland-0" ] && \
            WAYLAND_DISPLAY=wayland-0 timeout 2s wayland-info >/dev/null 2>&1; then
            ready=1
            break
        fi
        attempt=$((attempt + 1))
        sleep 0.25
    done
    if [ "$ready" -ne 1 ]; then
        echo "Packaged labwc login did not expose a working Wayland socket" >&2
        sed -n "1,70p" "$runtime/session.log" >&2
        exit 1
    fi

    ready=0
    attempt=0
    while [ "$attempt" -lt 40 ]; do
        kill -0 "$session" 2>/dev/null || break
        if pgrep -u "$(id -u)" -f "^/usr/bin/riceplate-native([[:space:]]|$)" >/dev/null && \
            pgrep -u "$(id -u)" -x swayidle >/dev/null; then
            ready=1
            break
        fi
        attempt=$((attempt + 1))
        sleep 0.25
    done
    if [ "$ready" -ne 1 ]; then
        echo "Packaged native RicePlate or protected idle guard failed to start" >&2
        sed -n "1,100p" "$runtime/session.log" >&2
        exit 1
    fi
    WAYLAND_DISPLAY=wayland-0 timeout 8s grim "$runtime/native.png"
    /usr/bin/python3 -c '\''
import struct, sys
from pathlib import Path
data = Path(sys.argv[1]).read_bytes()
assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 512
width, height = struct.unpack(">II", data[16:24])
assert width >= 640 and height >= 480, (width, height)
'\'' "$runtime/native.png"
    echo "PASS: installed native RicePlate, labwc, swayidle and real Wayland framebuffer"
' sh "$runtime"

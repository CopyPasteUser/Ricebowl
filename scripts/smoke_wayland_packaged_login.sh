#!/bin/sh
# CI-only: boot the INSTALLED Wayland login wrapper, not the source checkout.
# Must run inside the throwaway Ubuntu package-install container.
set -eu
if [ "${RICEBOWL_PACKAGED_CI:-}" != 1 ] || [ ! -f /.dockerenv ] || [ "$(id -u)" != 0 ]; then
    echo 'Refusing to run packaged login smoke outside its disposable root container' >&2
    exit 2
fi
for tool in runuser dbus-run-session labwc grim wayland-info pgrep ps; do
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
    # CI headless timing only: monotonic clock from launch to observable
    # socket and actual PNG. Never treat this as greeter/login hardware timing.
    now_ns() { /usr/bin/python3 -c "import time; print(time.monotonic_ns())"; }
    started_ns=$(now_ns)
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

    socket_ns=$(now_ns)
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
    visible_ns=$(now_ns)
    echo "HEADLESS_SOCKET_READY_MS=$(( (socket_ns - started_ns) / 1000000 ))"
    echo "HEADLESS_VISIBLE_NATIVE_MS=$(( (visible_ns - started_ns) / 1000000 ))"
    echo "HEADLESS_MEASUREMENT_SCOPE=disposable-ubuntu-labwc-not-physical-login"
    echo "PASS: installed native RicePlate, labwc, swayidle and real Wayland framebuffer"

    # Crash the installed Rust panel, not a source-tree test double. A real
    # login must retain its compositor and recover the user-visible panel.
    native_pid=$(pgrep -u "$(id -u)" -f "^/usr/bin/riceplate-native([[:space:]]|$)")
    case "$native_pid" in
        ""|*[!0-9]*) echo "Expected exactly one private native panel" >&2; exit 1 ;;
    esac
    kill -KILL "$native_pid"
    recovered=0
    attempt=0
    while [ "$attempt" -lt 60 ]; do
        if ! kill -0 "$session" 2>/dev/null; then break; fi
        if pgrep -u "$(id -u)" -x waybar >/dev/null 2>&1; then
            recovered=1
            break
        fi
        attempt=$((attempt + 1))
        sleep 0.25
    done
    if [ "$recovered" -ne 1 ]; then
        echo "Installed native panel crash did not recover with Waybar" >&2
        sed -n "1,110p" "$runtime/session.log" >&2
        exit 1
    fi
    WAYLAND_DISPLAY=wayland-0 timeout 3s wayland-info >/dev/null
    WAYLAND_DISPLAY=wayland-0 timeout 8s grim "$runtime/rescued.png"
    test -s "$runtime/rescued.png"
    echo "PASS: installed native panel crash recovered with live Waybar"

    # The idle/lock guard is security-critical. Its failure must close the
    # entire session, not leave an unlocked compositor or revive a panel.
    idle_pid=$(pgrep -u "$(id -u)" -x swayidle)
    case "$idle_pid" in
        ""|*[!0-9]*) echo "Expected exactly one private lock guard" >&2; exit 1 ;;
    esac
    kill -KILL "$idle_pid"
    stopped=0
    attempt=0
    while [ "$attempt" -lt 80 ]; do
        state=$(ps -o stat= -p "$session" 2>/dev/null || :)
        case "$state" in
            ""|Z*)
                if ! WAYLAND_DISPLAY=wayland-0 timeout 2s wayland-info >/dev/null 2>&1 && \
                   ! pgrep -u "$(id -u)" -x waybar >/dev/null 2>&1; then
                    stopped=1
                    break
                fi ;;
        esac
        attempt=$((attempt + 1))
        sleep 0.25
    done
    if [ "$stopped" -ne 1 ] || \
       ! grep -Fq "idle/lock watcher exited; stopping unprotected Wayland session" \
           "$runtime/session.log"; then
        echo "Lock guard failure did not fail closed" >&2
        sed -n "1,110p" "$runtime/session.log" >&2
        exit 1
    fi
    wait "$session" || :
    session=
    echo "PASS: lock guard failure closed the installed session safely"

    # A failed login must not poison the next opt-in login in the same user
    # runtime. Reuse the installed entrypoint and require a fresh screenshot.
    /usr/bin/ricebowl-wayland-session --native >"$runtime/relogin.log" 2>&1 &
    session=$!
    ready=0
    attempt=0
    while [ "$attempt" -lt 80 ]; do
        kill -0 "$session" 2>/dev/null || break
        if [ -S "$runtime/wayland-0" ] && \
           WAYLAND_DISPLAY=wayland-0 timeout 2s wayland-info >/dev/null 2>&1 && \
           pgrep -u "$(id -u)" -f "^/usr/bin/riceplate-native([[:space:]]|$)" >/dev/null && \
           pgrep -u "$(id -u)" -x swayidle >/dev/null; then
            ready=1
            break
        fi
        attempt=$((attempt + 1))
        sleep 0.25
    done
    if [ "$ready" -ne 1 ]; then
        echo "Fresh installed login failed after protected session shutdown" >&2
        sed -n "1,100p" "$runtime/relogin.log" >&2
        exit 1
    fi
    WAYLAND_DISPLAY=wayland-0 timeout 8s grim "$runtime/relogin.png"
    /usr/bin/python3 -c '\''
import struct, sys
from pathlib import Path
for name in sys.argv[1:]:
    data = Path(name).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 512, name
    width, height = struct.unpack(">II", data[16:24])
    assert width >= 640 and height >= 480, (name, width, height)
'\'' "$runtime/rescued.png" "$runtime/relogin.png"
    echo "PASS: new native login works after forced fail-closed shutdown"

    # A damaged user selection or RiceSpice preferences must never prevent
    # launching the *installed* native session. Neither file may be repaired
    # implicitly: keep both for owner inspection while using safe defaults.
    kill "$session" 2>/dev/null || :
    wait "$session" 2>/dev/null || :
    session=
    mkdir -p "$runtime/config/ricebowl/recipes"
    chmod 0700 "$runtime/config" "$runtime/config/ricebowl" \
        "$runtime/config/ricebowl/recipes"
    selection="$runtime/config/ricebowl/recipes/.active-recipe"
    preferences="$runtime/config/ricebowl/ricespice.json"
    printf "%s\n" "{broken-selection" >"$selection"
    printf "%s\n" "{broken-preferences" >"$preferences"
    chmod 0600 "$selection" "$preferences"
    sha256sum "$selection" "$preferences" >"$runtime/corrupt-before.sha256"

    /usr/bin/ricebowl-wayland-session --native >"$runtime/corrupt-login.log" 2>&1 &
    session=$!
    ready=0
    attempt=0
    while [ "$attempt" -lt 80 ]; do
        kill -0 "$session" 2>/dev/null || break
        if [ -S "$runtime/wayland-0" ] && \
           WAYLAND_DISPLAY=wayland-0 timeout 2s wayland-info >/dev/null 2>&1 && \
           pgrep -u "$(id -u)" -f "^/usr/bin/riceplate-native([[:space:]]|$)" >/dev/null && \
           pgrep -u "$(id -u)" -x swayidle >/dev/null; then
            ready=1
            break
        fi
        attempt=$((attempt + 1))
        sleep 0.25
    done
    if [ "$ready" -ne 1 ]; then
        echo "Installed login failed to recover from damaged private preferences" >&2
        sed -n "1,100p" "$runtime/corrupt-login.log" >&2
        exit 1
    fi
    grep -Fq "RiceBowl: ignoring invalid saved recipe selection:" \
        "$runtime/corrupt-login.log"
    grep -Fq "RiceBowl: ignoring unsafe RiceSpice preferences:" \
        "$runtime/corrupt-login.log"
    native_pid=$(pgrep -u "$(id -u)" -f "^/usr/bin/riceplate-native([[:space:]]|$)")
    case "$native_pid" in
        ""|*[!0-9]*) echo "Expected exactly one native fallback panel" >&2; exit 1 ;;
    esac
    if tr "\\000" "\n" <"/proc/$native_pid/environ" | \
       grep -q "^RICEBOWL_DE_RECIPE="; then
        echo "Corrupted selection was unexpectedly passed to native RicePlate" >&2
        exit 1
    fi
    WAYLAND_DISPLAY=wayland-0 timeout 8s grim "$runtime/corrupt-fallback.png"
    test -s "$runtime/corrupt-fallback.png"
    sha256sum -c --status "$runtime/corrupt-before.sha256"
    echo "PASS: corrupt private selection and RiceSpice preferences fall back without data loss"
' sh "$runtime"

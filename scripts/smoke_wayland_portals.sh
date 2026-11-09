#!/bin/sh
# Exercise actual portal D-Bus requests against an isolated headless labwc.
# No host session, user clipboard, global portal configuration or screen pixels
# outside the disposable CI compositor are accessed.
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
for dependency in labwc pipewire dbus-run-session dbus-update-activation-environment; do
    command -v "$dependency" >/dev/null || { echo "Missing portal test dependency: $dependency" >&2; exit 1; }
done
backend_executable=$(command -v xdg-desktop-portal-wlr || :)
if [ -z "$backend_executable" ] && [ -x /usr/libexec/xdg-desktop-portal-wlr ]; then
    backend_executable=/usr/libexec/xdg-desktop-portal-wlr
fi
test -n "$backend_executable" || { echo 'Missing wlr portal backend executable' >&2; exit 1; }
runtime=$(mktemp -d)
chmod 0700 "$runtime"
cleanup_runtime() {
    if command -v mountpoint >/dev/null 2>&1 && mountpoint -q "$runtime/doc"; then
        if command -v fusermount3 >/dev/null 2>&1; then
            fusermount3 -uz "$runtime/doc" 2>/dev/null || :
        fi
    fi
    if ! rm -r -- "$runtime" 2>/dev/null; then
        echo 'CI note: portal left a busy disposable document mount' >&2
    fi
}
trap cleanup_runtime EXIT
mkdir -p "$runtime/config/xdg-desktop-portal" "$runtime/config/xdg-desktop-portal-wlr"
cp "$root/packaging/wayland/ricebowl-portals.conf" \
    "$runtime/config/xdg-desktop-portal/ricebowl-portals.conf"
# Never put this unattended chooser setting into the installed RiceBowl DE.
printf '[screencast]\nchooser_type=none\nmax_fps=15\n' \
    >"$runtime/config/xdg-desktop-portal-wlr/config"

export XDG_RUNTIME_DIR="$runtime"
export XDG_CONFIG_HOME="$runtime/config"
export XDG_CURRENT_DESKTOP=RiceBowl:labwc:wlroots
export XDG_SESSION_DESKTOP=ricebowl
export XDG_SESSION_TYPE=wayland
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=1
export WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=1

dbus-run-session -- sh -eu -c '
    root=$1
    runtime=$2
    backend_executable=$3
    labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
        >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    pipewire >"$runtime/pipewire.log" 2>&1 &
    pw=$!
    backend=
    cleanup() {
        if [ -n "$backend" ]; then
            kill "$backend" 2>/dev/null || :
            wait "$backend" 2>/dev/null || :
        fi
        kill "$compositor" "$pw" 2>/dev/null || :
        wait "$compositor" 2>/dev/null || :
        wait "$pw" 2>/dev/null || :
    }
    trap cleanup EXIT

    count=0
    while { [ ! -S "$runtime/wayland-0" ] || [ ! -S "$runtime/pipewire-0" ]; } \
            && [ "$count" -lt 60 ]; do
        if ! kill -0 "$compositor" 2>/dev/null || ! kill -0 "$pw" 2>/dev/null; then
            echo "Portal test compositor or PipeWire exited" >&2
            break
        fi
        sleep 0.25
        count=$((count + 1))
    done
    if [ ! -S "$runtime/wayland-0" ] || [ ! -S "$runtime/pipewire-0" ]; then
        sed -n "1,45p" "$runtime/labwc.log" >&2
        sed -n "1,45p" "$runtime/pipewire.log" >&2
        exit 1
    fi
    export WAYLAND_DISPLAY=wayland-0
    # The private D-Bus daemon must activate xdp, GTK and wlr with the *new*
    # compositor socket and desktop selection, never the parent login values.
    dbus-update-activation-environment WAYLAND_DISPLAY XDG_RUNTIME_DIR \
        XDG_CONFIG_HOME XDG_CURRENT_DESKTOP XDG_SESSION_TYPE XDG_SESSION_DESKTOP
    # Temporary verbose backend is identical to D-Bus auto activation but
    # records its actual session object registration path on failure.
    "$backend_executable" -l DEBUG >"$runtime/xdpw.log" 2>&1 &
    backend=$!
    sleep 0.25
    kill -0 "$backend" 2>/dev/null || {
        echo "Diagnostic portal backend exited before request" >&2
        sed -n "1,70p" "$runtime/xdpw.log" >&2
        exit 1
    }
    if ! timeout -k 3s 35s /usr/bin/python3 \
            "$root/scripts/check_wayland_portals.py"; then
        echo "Wayland portal runtime acceptance failed" >&2
        sed -n "1,55p" "$runtime/labwc.log" >&2
        sed -n "1,45p" "$runtime/pipewire.log" >&2
        sed -n "1,100p" "$runtime/xdpw.log" >&2
        exit 1
    fi
' sh "$root" "$runtime" "$backend_executable"

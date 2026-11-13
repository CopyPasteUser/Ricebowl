#!/bin/sh
# Disposable labwc + private D-Bus acceptance. Never uses the live desktop.
set -eu
# The normal lane preserves the explicit pixman ScreenCast limitation.
# Strict mode is intentionally separate and fails unless GLES2 is selected.
renderer=${RICEBOWL_PORTAL_RENDERER:-pixman}
strict=${RICEBOWL_PORTAL_STRICT_CI:-0}
case "$renderer" in
    pixman|gles2) ;;
    *) echo "Unsupported isolated portal renderer: $renderer" >&2; exit 2 ;;
esac
case "$strict" in
    0) ;;
    1)
        [ "$renderer" = gles2 ] || {
            echo "Strict portal capture requires the GLES2 renderer" >&2; exit 2;
        } ;;
    *) echo "Invalid strict portal CI flag" >&2; exit 2 ;;
esac
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
for binary in labwc pipewire dbus-run-session dbus-update-activation-environment gdbus timeout; do
    command -v "$binary" >/dev/null 2>&1 || {
        echo "Portal smoke missing dependency: $binary" >&2; exit 1;
    }
done
runtime=$(mktemp -d)
chmod 0700 "$runtime"
cleanup() {
    # The document portal may mount its own FUSE directory asynchronously.
    if command -v mountpoint >/dev/null 2>&1 && mountpoint -q "$runtime/doc"; then
        if command -v fusermount3 >/dev/null 2>&1; then
            fusermount3 -uz "$runtime/doc" 2>/dev/null || :
        elif command -v fusermount >/dev/null 2>&1; then
            fusermount -uz "$runtime/doc" 2>/dev/null || :
        fi
    fi
    rm -rf -- "$runtime" 2>/dev/null || :
}
trap cleanup EXIT
mkdir -m 0700 "$runtime/config"
mkdir -m 0700 "$runtime/config/xdg-desktop-portal"
cp "$root/packaging/wayland/ricebowl-portals.conf" \
    "$runtime/config/xdg-desktop-portal/ricebowl-portals.conf"
# CI only: suppress interactive monitor selection for a disposable headless
# compositor. The installed package never receives this chooser override.
mkdir -m 0700 "$runtime/config/xdg-desktop-portal-wlr" "$runtime/cache" "$runtime/tmp"
printf '[screencast]\nchooser_type=none\n' \
    >"$runtime/config/xdg-desktop-portal-wlr/config"
: >"$runtime/.ricebowl-portal-ci"
export XDG_RUNTIME_DIR="$runtime"
export PIPEWIRE_RUNTIME_DIR="$runtime"
export XDG_CONFIG_HOME="$runtime/config"
export XDG_CACHE_HOME="$runtime/cache"
export TMPDIR="$runtime/tmp"
export XDG_CURRENT_DESKTOP=RiceBowl:labwc:wlroots
export XDG_SESSION_DESKTOP=ricebowl
export XDG_SESSION_TYPE=wayland
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=1
export WLR_RENDERER="$renderer"
export RICEBOWL_PORTAL_STRICT_CI="$strict"
export LABWC_UPDATE_ACTIVATION_ENV=0
export RICEBOWL_DE_NESTED=1
export RICEBOWL_PORTAL_CAPTURE_CI=1

# The compositor provides the WAYLAND_DISPLAY socket; the client imports it
# into this *private* D-Bus daemon before activation of xdg-desktop-portal.
dbus-run-session -- sh -eu -c '
    root=$1
    runtime=$2
    compositor=
    pipewire_pid=
    cleanup_children() {
        if [ -n "$compositor" ]; then
            kill "$compositor" 2>/dev/null || :
            wait "$compositor" 2>/dev/null || :
        fi
        if [ -n "$pipewire_pid" ]; then
            kill "$pipewire_pid" 2>/dev/null || :
            wait "$pipewire_pid" 2>/dev/null || :
        fi
    }
    trap cleanup_children EXIT
    # xdg-desktop-portal-wlr fails its D-Bus activation if there is no real
    # PipeWire core in this isolated user runtime. Start a private instance,
    # not the runner/user default session service.
    pipewire >"$runtime/pipewire.log" 2>&1 &
    pipewire_pid=$!
    attempt=0
    while [ ! -S "$runtime/pipewire-0" ] && [ "$attempt" -lt 40 ]; do
        if ! kill -0 "$pipewire_pid" 2>/dev/null; then break; fi
        attempt=$((attempt + 1))
        sleep 0.2
    done
    if [ ! -S "$runtime/pipewire-0" ]; then
        echo "Isolated PipeWire core failed to open its runtime socket" >&2
        sed -n "1,50p" "$runtime/pipewire.log" >&2
        exit 1
    fi
    labwc --config-dir "$root/macrice/de/resources/labwc" \
        --startup "sh \"$root/scripts/wayland_portals_smoke_client.sh\" \"$root\" \"$runtime\" >\"$runtime/client.log\" 2>&1" \
        >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    attempt=0
    while [ ! -f "$runtime/portals-ok" ] && [ ! -f "$runtime/portals-failed" ] \
          && [ "$attempt" -lt 260 ]; do
        kill -0 "$compositor" 2>/dev/null || break
        attempt=$((attempt + 1))
        sleep 0.25
    done
    if [ ! -f "$runtime/portals-ok" ]; then
        echo "Portal runtime acceptance did not complete" >&2
        for log in client.log labwc.log pipewire.log; do
            if [ -f "$runtime/$log" ]; then
                sed -n "1,55p" "$runtime/$log" >&2
            fi
        done
        exit 1
    fi
    echo "RiceBowl portal interfaces and capture requests passed in isolated labwc"
' sh "$root" "$runtime"

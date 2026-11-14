#!/bin/sh
# Disposable labwc + private D-Bus acceptance. Never uses the live desktop.
set -eu
# Strict mode must not degrade to the usual pixman capability smoke.
renderer=${RICEBOWL_PORTAL_RENDERER:-pixman}
strict=${RICEBOWL_PORTAL_STRICT_CI:-0}
backend=${RICEBOWL_PORTAL_BACKEND:-wlr}
case "$backend" in wlr|generic) ;; *)
    echo "PORTAL_SETUP_FAIL: unsupported backend: $backend" >&2; exit 2 ;;
esac
case "$renderer" in pixman|gles2) ;; *)
    echo "PORTAL_SETUP_FAIL: unsupported renderer: $renderer" >&2; exit 2 ;;
esac
case "$strict" in 0|1) ;; *)
    echo "PORTAL_SETUP_FAIL: strict flag must be 0 or 1" >&2; exit 2 ;;
esac
if [ "$backend" = generic ] && [ "$strict" != 1 ]; then
    echo "PORTAL_SETUP_FAIL: generic backend reserved for strict isolated CI" >&2
    exit 2
fi
if [ "$strict" = 1 ] && [ "$backend" = generic ]; then
    [ "$renderer" = pixman ] || {
        echo "PORTAL_STRICT_BLOCKED: generic SHM backend requires pixman" >&2
        exit 3
    }
    command -v wireplumber >/dev/null 2>&1 || {
        echo "PORTAL_SETUP_FAIL: missing private PipeWire session manager: wireplumber" >&2
        exit 2
    }
    [ -x /usr/libexec/xdg-desktop-portal-generic ] || {
        echo "PORTAL_SETUP_FAIL: pinned generic portal binary missing" >&2
        exit 2
    }
fi
if [ "$strict" = 1 ] && [ "$backend" = wlr ]; then
    [ "$renderer" = gles2 ] || {
        echo "PORTAL_STRICT_BLOCKED: wlr backend requires gles2 (no pixman fallback)" >&2
        exit 3
    }
    # wlroots 0.17 needs a DRM render FD even with Mesa llvmpipe.
    # Never create devices or load host kernel modules in this script.
    render_node=
    for node in /dev/dri/renderD*; do
        if [ -c "$node" ] && [ -r "$node" ] && [ -w "$node" ]; then
            render_node=$node
            break
        fi
    done
    [ -n "$render_node" ] || {
        echo "PORTAL_STRICT_BLOCKED: no accessible DRM render node (/dev/dri/renderD*); isolated GLES2 cannot start" >&2
        exit 3
    }
    export WLR_RENDER_DRM_DEVICE="$render_node"
    export WLR_RENDERER_ALLOW_SOFTWARE=1
    echo "PORTAL_STRICT_PREREQ_OK: DRM render node available: $render_node"
fi
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
for binary in labwc pipewire dbus-run-session dbus-update-activation-environment gdbus timeout setsid grim; do
    command -v "$binary" >/dev/null 2>&1 || {
        echo "PORTAL_SETUP_FAIL: missing dependency: $binary" >&2; exit 1;
    }
done
runtime=$(mktemp -d /tmp/ricebowl-portals.XXXXXXXX)
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
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
mkdir -m 0700 "$runtime/config"
mkdir -m 0700 "$runtime/config/xdg-desktop-portal"
cp "$root/packaging/wayland/ricebowl-portals.conf" \
    "$runtime/config/xdg-desktop-portal/ricebowl-portals.conf"
if [ "$backend" = generic ]; then
    # Disposable CI selection only. Installed RiceBowl always keeps wlr.
    cat >"$runtime/config/xdg-desktop-portal/ricebowl-portals.conf" <<'PORTALS'
[preferred]
default=gtk
org.freedesktop.impl.portal.ScreenCast=generic
org.freedesktop.impl.portal.Screenshot=wlr
PORTALS
    cat >"$runtime/ci-source-picker" <<'PICKER'
#!/bin/sh
# Only the first headless test output; never install this consent bypass.
set -eu
awk -F '\t' 'NR == 1 && NF >= 3 && $1 != "" {print $1; good=1; exit} END {if (!good) exit 1}'
PICKER
    chmod 0700 "$runtime/ci-source-picker"
fi
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
export RICEBOWL_PORTAL_BACKEND="$backend"
export LABWC_UPDATE_ACTIVATION_ENV=0
export RICEBOWL_DE_NESTED=1
export RICEBOWL_PORTAL_CAPTURE_CI=1

# The compositor provides the WAYLAND_DISPLAY socket; the client imports it
# into this *private* D-Bus daemon before activation of xdg-desktop-portal.
dbus-run-session -- sh -eu -c '
    root=$1
    runtime=$2
    compositor=
    client=
    pipewire_pid=
    wireplumber_pid=
    generic_pid=
    painter_pid=
    cleanup_children() {
        # Client owns a distinct session/process group; terminate it and
        # all of its timeout/Python descendants on compositor failures.
        if [ -n "$client" ]; then
            kill -TERM "-$client" 2>/dev/null || :
            wait "$client" 2>/dev/null || :
        fi
        if [ -n "$painter_pid" ]; then
            kill "$painter_pid" 2>/dev/null || :
            wait "$painter_pid" 2>/dev/null || :
        fi
        if [ -n "$generic_pid" ]; then
            kill "$generic_pid" 2>/dev/null || :
            wait "$generic_pid" 2>/dev/null || :
        fi
        if [ -n "$compositor" ]; then
            kill "$compositor" 2>/dev/null || :
            wait "$compositor" 2>/dev/null || :
        fi
        if [ -n "$wireplumber_pid" ]; then
            kill "$wireplumber_pid" 2>/dev/null || :
            wait "$wireplumber_pid" 2>/dev/null || :
        fi
        if [ -n "$pipewire_pid" ]; then
            kill "$pipewire_pid" 2>/dev/null || :
            wait "$pipewire_pid" 2>/dev/null || :
        fi
    }
    trap cleanup_children EXIT
    # Bind the private bus identity to the private runtime before clients start.
    # This prevents an accidentally inherited live user bus from being accepted.
    printf "%s\\n" "$DBUS_SESSION_BUS_ADDRESS" >"$runtime/.ricebowl-portal-dbus"
    chmod 0600 "$runtime/.ricebowl-portal-dbus"
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
    if [ "$RICEBOWL_PORTAL_BACKEND" = generic ]; then
        # The bare PipeWire core cannot policy-link a portal source with a
        # GStreamer client; without a private session manager the producer
        # loops indefinitely with "No buffer available from PipeWire stream".
        wireplumber >"$runtime/wireplumber.log" 2>&1 &
        wireplumber_pid=$!
        sleep 1
        kill -0 "$wireplumber_pid" 2>/dev/null || {
            echo "PORTAL_SETUP_FAIL: private WirePlumber session manager exited" >&2
            tail -n 65 "$runtime/wireplumber.log" >&2
            exit 1
        }
    fi
    # The compositor and client are sibling processes owned by this wrapper.
    # Avoid labwc --startup orphaning the client when the compositor crashes.
    labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
        >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    display=
    attempt=0
    while [ -z "$display" ] && [ "$attempt" -lt 60 ]; do
        kill -0 "$compositor" 2>/dev/null || break
        for candidate in "$runtime"/wayland-*; do
            if [ -S "$candidate" ]; then
                display=${candidate##*/}
                break
            fi
        done
        [ -n "$display" ] && break
        attempt=$((attempt + 1))
        sleep 0.2
    done
    if [ -z "$display" ]; then
        echo "PORTAL_SETUP_FAIL: labwc never created an isolated Wayland socket" >&2
        sed -n "1,80p" "$runtime/labwc.log" >&2
        exit 1
    fi
    export WAYLAND_DISPLAY="$display"
    if [ "$RICEBOWL_PORTAL_BACKEND" = generic ]; then
        XDP_GENERIC_SOURCE_PICKER="$runtime/ci-source-picker" \
            /usr/libexec/xdg-desktop-portal-generic >"$runtime/generic.log" 2>&1 &
        generic_pid=$!
        sleep 1
        if ! kill -0 "$generic_pid" 2>/dev/null; then
            echo "PORTAL_SETUP_FAIL: SHM portal backend exited before capture" >&2
            sed -n "1,70p" "$runtime/generic.log" >&2
            exit 1
        fi
        # A real animated Wayland surface keeps producing compositor damage.
        # A static empty headless output can return Stream Start without a
        # single PipeWire buffer; never manufacture video in the receiver.
        GDK_BACKEND=wayland /usr/bin/python3 "$root/scripts/wayland_portal_frame_painter.py" \
            >"$runtime/painter.log" 2>&1 &
        painter_pid=$!
        sleep 0.5
        if ! kill -0 "$painter_pid" 2>/dev/null; then
            echo "PORTAL_SETUP_FAIL: real Wayland frame painter exited" >&2
            sed -n "1,70p" "$runtime/painter.log" >&2
            exit 1
        fi
    fi
    setsid sh "$root/scripts/wayland_portals_smoke_client.sh" "$root" "$runtime" \
        >"$runtime/client.log" 2>&1 &
    client=$!
    attempt=0
    max_attempts=260
    if [ "$RICEBOWL_PORTAL_STRICT_CI" = 1 ]; then max_attempts=520; fi
    while [ ! -f "$runtime/portals-ok" ] && [ ! -f "$runtime/portals-failed" ] \
          && [ "$attempt" -lt "$max_attempts" ]; do
        kill -0 "$compositor" 2>/dev/null || break
        attempt=$((attempt + 1))
        sleep 0.25
    done
    if [ ! -f "$runtime/portals-ok" ] || [ -f "$runtime/portals-failed" ]; then
        echo "Portal runtime acceptance did not complete" >&2
        for log in client.log labwc.log pipewire.log wireplumber.log painter.log generic.log; do
            if [ -f "$runtime/$log" ]; then
                tail -n 100 "$runtime/$log" >&2
            fi
        done
        exit 1
    fi
    # A receipt written immediately before client termination is not
    # successful until the process actually exits with status 0.
    wait "$client" || {
        echo "PORTAL_CAPTURE_FAIL: client exited unsuccessfully" >&2
        sed -n "1,110p" "$runtime/client.log" >&2
        exit 1
    }
    client=
    if [ "$RICEBOWL_PORTAL_STRICT_CI" = 1 ]; then
        # Independent shell gate: the client must prove it sampled a frame.
        grep -q "^PORTAL_FRAME_OK:" "$runtime/client.log" || {
            echo "PORTAL_STRICT_FAIL: actual video frame was not verified" >&2
            sed -n "1,110p" "$runtime/client.log" >&2
            exit 1
        }
        grep -q "^PORTAL_STRICT_OK:" "$runtime/client.log" || {
            echo "PORTAL_STRICT_FAIL: missing strict acceptance receipt" >&2
            exit 1
        }
    fi
    sed -n "1,100p" "$runtime/client.log"
    echo "RiceBowl isolated portal smoke completed (renderer=$WLR_RENDERER, backend=$RICEBOWL_PORTAL_BACKEND, strict=$RICEBOWL_PORTAL_STRICT_CI)"
' sh "$root" "$runtime"

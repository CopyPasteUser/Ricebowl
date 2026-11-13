#!/bin/sh
# Isolated, unprivileged native labwc capture of genuine GTK Luna system UI.
# Never changes the host login session, user XDG configuration, or rice.
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
output=${1:?Provide an absolute empty output directory}
case "$output" in
    /*) : ;;
    *) echo "Output directory must be absolute" >&2; exit 2 ;;
esac
if [ "$(id -u)" -eq 0 ]; then
    echo "Do not run a graphical CI capture as root" >&2
    exit 2
fi
runtime=$(mktemp -d -t ricebowl-luna-system-XXXXXXXX)
chmod 0700 "$runtime"
cleanup() { rm -rf -- "$runtime"; }
trap cleanup EXIT
mkdir -m 700 "$runtime/config" "$runtime/state" "$runtime/home"
export XDG_RUNTIME_DIR="$runtime"
export XDG_CONFIG_HOME="$runtime/config"
export XDG_STATE_HOME="$runtime/state"
export HOME="$runtime/home"
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=1
export WLR_RENDERER=pixman
export XDG_SESSION_TYPE=wayland
export GDK_BACKEND=wayland
export RICEBOWL_DE_NESTED=1

dbus-run-session -- sh -eu -c '
    root=$1
    runtime=$2
    output=$3
    labwc --config-dir "$root/macrice/de/resources/labwc" --startup true \
        >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    trap "kill $compositor 2>/dev/null || :; wait $compositor 2>/dev/null || :" EXIT
    count=0
    while [ "$count" -lt 80 ]; do
        if ! kill -0 "$compositor" 2>/dev/null; then
            echo "labwc exited before the native GTK test session started" >&2
            sed -n "1,80p" "$runtime/labwc.log" >&2
            exit 1
        fi
        [ ! -S "$runtime/wayland-0" ] || break
        count=$((count + 1))
        sleep 0.25
    done
    if [ ! -S "$runtime/wayland-0" ]; then
        echo "labwc never exposed a Wayland socket" >&2
        sed -n "1,80p" "$runtime/labwc.log" >&2
        exit 1
    fi
    export WAYLAND_DISPLAY=wayland-0
    /usr/bin/python3 "$root/scripts/capture_luna_labwc.py" --output-dir "$output"
' sh "$root" "$runtime" "$output"

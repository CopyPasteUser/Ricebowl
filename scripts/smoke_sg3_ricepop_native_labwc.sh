#!/bin/sh
# SG3 (WP3.1/3.2): the real native RicePop inbox of the Luna panel against a
# real Mako host, driven by a real labwc keyboard (wtype) and a real pointer,
# observed through the public AT-SPI bus and the notification D-Bus. No
# notification owner is added: the ONE host is the Mako started below, with the
# shipped RiceBowl configuration, exactly as the session supervisor would.
#
# Disposable: private labwc, private D-Bus, private HOME/XDG, private PATH shim
# for the `ricebowl` CLI. Never touches a login session or a user's files.
#
# Mako comes from PATH: the source-locked 1.11 build in smoke_real_mako_111.sh,
# or the distribution Mako (1.8) when run directly.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$root/components/riceplate-wayland/target/release/riceplate-native"
clicker="$root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
test -x "$clicker" || { echo "Build Wayland pointer fixture first" >&2; exit 1; }
test -x "$native" || { echo 'Build native RicePlate first' >&2; exit 1; }
for tool in labwc wtype mako makoctl busctl gdbus grim wlr-randr; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "Required tool missing from PATH: $tool" >&2; exit 2; }
done
/usr/bin/python3 -c "import pyatspi, PIL" >/dev/null 2>&1 || {
    echo "python3-pyatspi and python3-pil are required" >&2; exit 2; }

runtime=$(mktemp -d -t ricebowl-sg3-native-XXXXXXXX)
chmod 0700 "$runtime"
trap 'rm -rf -- "$runtime"' EXIT
mkdir -m 0700 "$runtime/config" "$runtime/home" "$runtime/bin"
export XDG_RUNTIME_DIR="$runtime" XDG_CONFIG_HOME="$runtime/config"
export HOME="$runtime/home"
unset XDG_DATA_HOME XDG_STATE_HOME XDG_CACHE_HOME
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=0 RICEBOWL_DE_SCREEN_READER=1
export XDG_SESSION_DESKTOP=ricebowl XDG_SESSION_TYPE=wayland
export RICEBOWL_DE_TRACE_MENU=1
# The native panel shells out to `ricebowl de ...` exactly as installed.
cat >"$runtime/bin/ricebowl" <<EOF
#!/bin/sh
exec /usr/bin/python3 "$root/launcher.py" "\$@"
EOF
chmod 0755 "$runtime/bin/ricebowl"
export PATH="$runtime/bin:$root/components/riceplate-wayland/target/release:$PATH"

cp "$root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
chmod 0600 "$runtime/luna.json"
/usr/bin/python3 - "$root" "$runtime" <<'PY'
from pathlib import Path
import sys
root, runtime = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
from macrice.de import recipes, session
rice = recipes.parse((root / "examples/wayland/xp-luna-columns.json").read_bytes())
config = session._custom_labwc_config(rice, str(runtime), native_luna_hotkeys=True)
(runtime / "config-path").write_text(str(config))
PY

dbus-run-session -- sh -eu -c '
    root=$1; runtime=$2; native=$3; clicker=$4
    export WAYLAND_DISPLAY=wayland-0
    labwc --config-dir "$(cat "$runtime/config-path")" >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    plate=; keyboard_keeper=
    cleanup() {
        for pid in "$keyboard_keeper" "$plate" "$compositor"; do
            if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || :; fi
        done
        for pid in "$keyboard_keeper" "$plate" "$compositor"; do
            if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || :; fi
        done
    }
    trap cleanup EXIT
    count=0
    while [ "$count" -lt 50 ] && [ ! -S "$runtime/wayland-0" ]; do
        kill -0 "$compositor" 2>/dev/null || { sed -n "1,100p" "$runtime/labwc.log" >&2; exit 1; }
        count=$((count + 1)); sleep 0.2
    done
    test -S "$runtime/wayland-0" || { echo "labwc socket missing" >&2; exit 1; }
    # A real desktop keeps a keyboard on the seat; see smoke_luna_atspi.sh.
    wtype -k F13 -s 1800000 -k F13 >"$runtime/keyboard-keeper.log" 2>&1 &
    keyboard_keeper=$!
    sleep 0.3
    kill -0 "$keyboard_keeper" 2>/dev/null || { cat "$runtime/keyboard-keeper.log" >&2; exit 1; }
    output=$(wlr-randr | sed -n "1s/[[:space:]].*//p")
    wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1
    /usr/bin/python3 -c "import pyatspi; pyatspi.Registry.getDesktop(0).childCount" >/dev/null
    dbus-send --session --print-reply --reply-timeout=5000 \
        --dest=org.a11y.Bus /org/a11y/bus \
        org.freedesktop.DBus.Properties.Set \
        string:org.a11y.Status string:IsEnabled variant:boolean:true >/dev/null

    "$native" --recipe "$runtime/luna.json" >"$runtime/native.log" 2>&1 &
    plate=$!
    count=0
    while [ "$count" -lt 50 ] && [ ! -S "$runtime/riceplate-luna-desktop.sock" ]; do
        kill -0 "$plate" 2>/dev/null || { sed -n "1,100p" "$runtime/native.log" >&2; exit 1; }
        count=$((count + 1)); sleep 0.2
    done
    test -S "$runtime/riceplate-luna-desktop.sock" || exit 1

    # The driver owns the scenario; it gets the PIDs it may kill/restart.
    SG3_NATIVE_PID=$plate SG3_RUNTIME=$runtime SG3_ROOT=$root \
    SG3_CLICKER=$clicker SG3_MAKO_CONFIG="$root/macrice/de/resources/mako.conf" \
        /usr/bin/python3 "${SG3_DRIVER:-$root/scripts/smoke_sg3_ricepop_native_driver.py}"
' sh "$root" "$runtime" "$native" "$clicker"

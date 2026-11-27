#!/bin/sh
# SG2 WP2.4: GUI pass over every RiceSpice settings page under a real, disposable
# headless labwc, showing the denied, busy and unavailable states visibly.
#
# The real `macrice.de.settings.launch()` GTK3 window (GDK_BACKEND=wayland) is run
# once per page with only the system-service boundary replaced by the repository's
# fake providers (tests/test_de_settings_gui_controls.py, test_de_sg2_gap_gui.py).
# Per page the driver proves, with the accessibility tree (text/role/SHOWING of the
# status widget, presence and SENSITIVE state of the control), real compositor
# pointer clicks and a grim crop of the status widget that is inked and different
# in every state: baseline, denied, busy (write held in flight, then a refused
# second click), released, and unavailable (provider missing, control withheld).
# Fake providers only: this is GUI evidence, not real polkit/NetworkManager/BlueZ
# acceptance. Confirmation dialogs are answered by the fixture because a modal
# Dialog.run() freezes AT-SPI; the real dialogs are exercised by the Creator smokes.
#
# Disposable only: private HOME/XDG/runtime and D-Bus session. Exit 77 = tool missing.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
release="$root/components/riceplate-wayland/target/release"
clicker="$release/examples/wayland_pointer_click"
for command in dbus-run-session labwc wlr-randr grim wtype timeout; do
    command -v "$command" >/dev/null 2>&1 || { echo "Missing $command" >&2; exit 77; }
done
test -x "$clicker" || { echo "Build the wayland_pointer_click example first" >&2; exit 77; }
/usr/bin/python3 -c 'import PIL, pyatspi, gi' >/dev/null 2>&1 || exit 77
[ "$(id -u)" -ne 0 ] || { echo "Do not run the RiceSpice GUI smoke as root" >&2; exit 2; }

runtime=$(mktemp -d -t ricebowl-sg2-gui-XXXXXXXX)
chmod 0700 "$runtime"
trap 'rm -rf -- "$runtime"' EXIT
mkdir -m 0700 "$runtime/run" "$runtime/shots" "$runtime/home" "$runtime/config" \
    "$runtime/state" "$runtime/data"
# One labwc config for the whole run: the stock RiceBowl one plus a rule that
# puts every window at 0,0 without server decoration, so a widget's AT-SPI
# window coordinates map onto output pixels deterministically.
cp -r "$root/macrice/de/resources/labwc" "$runtime/labwc-config"
RUNTIME=$runtime /usr/bin/python3 - <<'PY'
import os
path = os.environ["RUNTIME"] + "/labwc-config/rc.xml"
text = open(path, encoding="utf-8").read()
rule = ('<windowRules><windowRule identifier="*" serverDecoration="no">'
        '<action name="MoveTo" x="0" y="0"/></windowRule></windowRules>')
assert "</labwc_config>" in text
open(path, "w", encoding="utf-8").write(text.replace("</labwc_config>", rule + "</labwc_config>"))
PY
export XDG_RUNTIME_DIR="$runtime/run"
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export GDK_BACKEND=wayland XDG_SESSION_TYPE=wayland RICEBOWL_DE_NESTED=1
export HOME="$runtime/home" XDG_CONFIG_HOME="$runtime/config" XDG_STATE_HOME="$runtime/state" XDG_DATA_HOME="$runtime/data"
export SG2G_RUNTIME="$runtime" SG2G_ROOT="$root" SG2G_CLICKER="$clicker"
export PATH="$release:$PATH"

set +e
timeout -k 5s "${SG2G_BUDGET:-420}s" dbus-run-session -- sh -eu -c '
    root=$1; runtime=$2
    export WAYLAND_DISPLAY=wayland-0
    labwc --config-dir "$runtime/labwc-config" --startup true >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    keeper=
    cleanup() {
        for pid in "$keeper" "$compositor"; do
            if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || :; fi
        done
        for pid in "$keeper" "$compositor"; do
            if [ -n "$pid" ]; then wait "$pid" 2>/dev/null || :; fi
        done
    }
    trap cleanup EXIT
    n=0
    while [ "$n" -lt 60 ] && [ ! -S "$XDG_RUNTIME_DIR/wayland-0" ]; do
        kill -0 "$compositor" 2>/dev/null || { sed -n "1,60p" "$runtime/labwc.log" >&2; exit 1; }
        n=$((n + 1)); sleep 0.2
    done
    test -S "$XDG_RUNTIME_DIR/wayland-0" || { echo "labwc socket missing" >&2; exit 1; }
    wtype -k F13 -s 1800000 -k F13 >"$runtime/keeper.log" 2>&1 &
    keeper=$!
    output=$(wlr-randr | sed -n "1s/[[:space:]].*//p")
    wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1
    /usr/bin/python3 -c "import pyatspi; pyatspi.Registry.getDesktop(0).childCount" >/dev/null
    /usr/bin/python3 "${SG2G_DRIVER:-$root/scripts/sg2_settings_gui_driver.py}"
' sh "$root" "$runtime"
status=$?
set -e
if [ -n "${SG2G_KEEP_DIR:-}" ]; then
    cp "$runtime"/shots/*.png "$runtime"/*.log "$SG2G_KEEP_DIR"/ 2>/dev/null || :
fi
[ "$status" -eq 0 ] || { echo "FAIL: SG2 RiceSpice GUI smoke exited $status" >&2; exit "$status"; }
echo "PASS: SG2 real GTK RiceSpice pages: denied, busy and unavailable states under labwc"

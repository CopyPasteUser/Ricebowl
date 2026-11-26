#!/bin/sh
# SG4 WP4.2: real GTK Rice Creator click-through of Export RicePack -> Import
# RicePack under a disposable headless labwc.
#
# The real `launcher.py creator` window (GDK_BACKEND=wayland) is driven in two
# fresh profiles: an AUTHOR profile creates a Heritage Composer draft and exports
# it through the real "Export RicePack..." file chooser and review dialog; a
# separate, empty IMPORT profile opens the real "Import RicePack..." chooser on
# that file, confirms the import dialog and previews the result. Two malformed
# archives are imported first and must show an honest error with no change.
#
# Input: the buttons that OPEN a modal chooser/dialog are pressed with real
# compositor pointer events (wayland_pointer_click); inside the dialogs and for
# non-modal buttons the driver uses AT-SPI actions. Reason: a `wtype` key is not
# delivered to GTK3 toplevels in this harness, and an AT-SPI doAction that opens a
# modal `Gtk.Dialog.run()` freezes the application's AT-SPI service for as long as
# the dialog is open (observed with a plain MessageDialog too).
#
# Disposable only: private HOME/XDG/runtime and D-Bus session. Exit 77 = tool missing.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
release="$root/components/riceplate-wayland/target/release"
clicker="$release/examples/wayland_pointer_click"
for command in dbus-run-session labwc wlr-randr grim swaybg timeout; do
    command -v "$command" >/dev/null 2>&1 || { echo "Missing $command" >&2; exit 77; }
done
test -x "$clicker" && test -x "$release/riceplate-native" || {
    echo "Build riceplate-native and the wayland_pointer_click example first" >&2; exit 77; }
/usr/bin/python3 -c 'import PIL, pyatspi, gi' >/dev/null 2>&1 || exit 77
[ "$(id -u)" -ne 0 ] || { echo "Do not run the Creator GUI smoke as root" >&2; exit 2; }

runtime=$(mktemp -d -t ricebowl-sg4-gui-XXXXXXXX)
chmod 0700 "$runtime"
trap 'rm -rf -- "$runtime"' EXIT
mkdir -m 0700 "$runtime/run" "$runtime/packs" "$runtime/shots"
for profile in author importer; do
    mkdir -m 0700 "$runtime/$profile" "$runtime/$profile/home" \
        "$runtime/$profile/config" "$runtime/$profile/state"
done
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
export SG4G_RUNTIME="$runtime" SG4G_ROOT="$root" SG4G_CLICKER="$clicker"
export PATH="$release:$PATH"

set +e
timeout -k 5s "${SG4G_BUDGET:-420}s" dbus-run-session -- sh -eu -c '
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
    wlr-randr --output "$output" --custom-mode 1920x1080@60Hz --scale 1
    /usr/bin/python3 -c "import pyatspi; pyatspi.Registry.getDesktop(0).childCount" >/dev/null
    /usr/bin/python3 "${SG4G_DRIVER:-$root/scripts/sg4_creator_gui_roundtrip_driver.py}"
' sh "$root" "$runtime"
status=$?
set -e
if [ -n "${SG4G_KEEP_DIR:-}" ]; then
    cp "$runtime"/shots/*.png "$runtime"/*.log "$SG4G_KEEP_DIR"/ 2>/dev/null || :
fi
[ "$status" -eq 0 ] || { echo "FAIL: SG4 Creator GUI round-trip smoke exited $status" >&2; exit "$status"; }
echo "PASS: SG4 real GTK Creator export -> import round trip"

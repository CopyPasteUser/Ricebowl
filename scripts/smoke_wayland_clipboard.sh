#!/bin/sh
# Real cross-protocol clipboard acceptance, in a disposable headless session.
set -eu

source_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
for executable in labwc Xwayland xterm wl-copy wl-paste xclip timeout dbus-run-session; do
    command -v "$executable" >/dev/null || { echo "Missing clipboard CI dependency: $executable" >&2; exit 1; }
done
runtime=$(mktemp -d)
chmod 0700 "$runtime"
trap 'rm -r -- "$runtime"' EXIT
export XDG_RUNTIME_DIR="$runtime"
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=1
export WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=1

dbus-run-session -- sh -eu -c '
    source_root=$1
    runtime=$2
    labwc --config-dir "$source_root/macrice/de/resources/labwc" \
        --startup "sh \"$source_root/scripts/wayland_clipboard_smoke_client.sh\" \"$runtime\" >\"$runtime/client.log\" 2>&1" \
        >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    trap '\''kill "$compositor" 2>/dev/null || :; wait "$compositor" 2>/dev/null || :'\'' EXIT
    count=0
    while [ ! -f "$runtime/clipboard-ok" ] && [ ! -f "$runtime/clipboard-failed" ] && [ "$count" -lt 220 ]; do
        if ! kill -0 "$compositor" 2>/dev/null; then
            echo "Clipboard compositor exited early" >&2
            break
        fi
        sleep 0.25
        count=$((count + 1))
    done
    if [ ! -f "$runtime/clipboard-ok" ]; then
        echo "Wayland/XWayland clipboard handoff failed or timed out" >&2
        if [ -f "$runtime/client.log" ]; then sed -n "1,55p" "$runtime/client.log" >&2; fi
        if [ -f "$runtime/wl-copy.log" ]; then sed -n "1,25p" "$runtime/wl-copy.log" >&2; fi
        if [ -f "$runtime/xclip.log" ]; then sed -n "1,25p" "$runtime/xclip.log" >&2; fi
        if [ -f "$runtime/xterm.log" ]; then sed -n "1,25p" "$runtime/xterm.log" >&2; fi
        sed -n "1,55p" "$runtime/labwc.log" >&2
        exit 1
    fi
    grep -Fxq OK "$runtime/clipboard-ok"
    echo "Both clipboard directions passed inside headless labwc/XWayland"
' sh "$source_root" "$runtime"

#!/bin/sh
# CI-only: real headless labwc plus one separately launched native layer surface.
set -eu

source_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$source_root/components/riceplate-wayland/target/release/riceplate-native"
if [ ! -x "$native" ]; then
    echo "Native RicePlate binary is not built" >&2
    exit 1
fi
"$native" --version
if "$native" --recipe ../classic >/dev/null 2>&1; then
    echo "Native RicePlate accepted an unsupported external recipe" >&2
    exit 1
fi

runtime=$(mktemp -d)
chmod 0700 "$runtime"
cp "$source_root/macrice/de/resources/recipes/classic.json" "$runtime/custom.json"
cp "$source_root/tests/fixtures/riceplate-nested-v3.json" "$runtime/nested.json"
cp "$source_root/tests/fixtures/riceplate-shell-v4.json" "$runtime/shell-v4.json"
cp "$source_root/tests/fixtures/riceplate-desktop-v5.json" "$runtime/desktop-v5.json"
cp "$source_root/tests/fixtures/riceplate-sidebar-v6.json" "$runtime/sidebar-v6.json"
cp "$source_root/tests/fixtures/riceplate-composed-v6.json" "$runtime/composed-v6.json"
cp "$source_root/tests/fixtures/riceplate-actions-v6.json" "$runtime/actions-v6.json"
cp "$source_root/tests/fixtures/riceplate-controls-v7.json" "$runtime/controls-v7.json"
cp "$source_root/tests/fixtures/riceplate-layout-v8.json" "$runtime/layout-v8.json"
cp "$source_root/tests/fixtures/riceplate-components-v9.json" "$runtime/components-v9.json"
cp "$source_root/tests/fixtures/riceplate-desktop-actions-v9.json" "$runtime/desktop-actions-v9.json"
cp "$source_root/tests/fixtures/riceplate-appearance-v10.json" "$runtime/appearance-v10.json"
cp "$source_root/examples/wayland/xp-luna-columns.json" "$runtime/xp-luna-columns.json"
cp "$source_root/tests/fixtures/riceplate-desktop-v5-overflow.json" "$runtime/overflow-v5.json"
chmod 0600 "$runtime/custom.json"
chmod 0600 "$runtime/nested.json"
chmod 0600 "$runtime/shell-v4.json"
chmod 0600 "$runtime/desktop-v5.json"
chmod 0600 "$runtime/sidebar-v6.json"
chmod 0600 "$runtime/composed-v6.json"
chmod 0600 "$runtime/actions-v6.json"
chmod 0600 "$runtime/controls-v7.json"
chmod 0600 "$runtime/layout-v8.json"
chmod 0600 "$runtime/components-v9.json"
chmod 0600 "$runtime/desktop-actions-v9.json"
chmod 0600 "$runtime/appearance-v10.json"
chmod 0600 "$runtime/xp-luna-columns.json"
chmod 0600 "$runtime/overflow-v5.json"
# Exercise the real private Creator font import and native font path in CI.
# The fixture is freely redistributable and never installed into the host's
# font directories or used by any existing rice/profile.
test_font=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf
if [ ! -f "$test_font" ]; then
    echo "Native font smoke requires the DejaVu Sans Mono fixture" >&2
    exit 1
fi
mkdir -m 0700 "$runtime/config"
export XDG_CONFIG_HOME="$runtime/config"
python3 - "$source_root" "$runtime" "$test_font" <<'PY'
import json
from pathlib import Path
import sys

root, runtime, fixture = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
from macrice.de import style_assets

source = runtime / "font-fixture.ttf"
source.write_bytes(fixture.read_bytes())
source.chmod(0o600)
asset = style_assets.import_asset(source, kind="font", label="DejaVu CI",
    provenance={"author": "DejaVu contributors", "license": "custom",
                "origin": "adapted", "source_reference": "DejaVu Fonts license"})
recipe = json.loads((runtime / "xp-luna-columns.json").read_text())
recipe["id"] = "xp-luna-font-preview"
recipe["name"] = "XP Luna Font Preview"
recipe["artwork"]["font"] = asset.identifier
target = runtime / "xp-luna-font.json"
target.write_text(json.dumps(recipe), encoding="utf-8")
target.chmod(0o600)
baseline = json.loads((runtime / "xp-luna-columns.json").read_text())
baseline["id"] = "xp-luna-default-icons"
baseline["name"] = "XP Luna Default Icons"
baseline["artwork"]["icons"] = {name: "builtin" for name in
                                  ("applications", "terminal", "lock")}
target = runtime / "xp-luna-default-icons.json"
target.write_text(json.dumps(baseline), encoding="utf-8")
target.chmod(0o600)
PY
ln -s "$runtime/custom.json" "$runtime/symlink.json"
if "$native" --recipe "$runtime/symlink.json" >"$runtime/rejected.log" 2>&1; then
    echo "Native RicePlate accepted a symlinked recipe" >&2
    exit 1
fi
chmod 0644 "$runtime/custom.json"
if "$native" --recipe "$runtime/custom.json" >"$runtime/rejected.log" 2>&1; then
    echo "Native RicePlate accepted an overly public recipe" >&2
    exit 1
fi
if ! grep -q "owner-private" "$runtime/rejected.log"; then
    echo "Native RicePlate did not reject unsafe permissions at validation" >&2
    exit 1
fi
chmod 0600 "$runtime/custom.json"
cleanup_runtime() {
    if ! rm -r -- "$runtime" 2>/dev/null; then
        echo "CI note: temporary runtime mount remained for runner cleanup" >&2
    fi
}
trap cleanup_runtime EXIT
export XDG_RUNTIME_DIR="$runtime"
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=1
export WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=1

dbus-run-session -- sh -eu -c '
    source_root=$1
    runtime=$2
    native=$3
    labwc --config-dir "$source_root/macrice/de/resources/labwc" \
        --startup true >"$runtime/labwc.log" 2>&1 &
    compositor=$!
    plate=
    wallpaper=
    cleanup() {
        if [ -n "$wallpaper" ]; then
            kill "$wallpaper" 2>/dev/null || :
            wait "$wallpaper" 2>/dev/null || :
        fi
        if [ -n "$plate" ]; then
            kill "$plate" 2>/dev/null || :
            wait "$plate" 2>/dev/null || :
        fi
        kill "$compositor" 2>/dev/null || :
        wait "$compositor" 2>/dev/null || :
    }
    trap cleanup EXIT
    count=0
    while [ "$count" -lt 40 ]; do
        if ! kill -0 "$compositor" 2>/dev/null; then
            echo "labwc stopped before creating the Wayland socket" >&2
            sed -n "1,70p" "$runtime/labwc.log" >&2
            exit 1
        fi
        if [ -S "$runtime/wayland-0" ]; then break; fi
        count=$((count + 1))
        sleep 0.25
    done
    if [ ! -S "$runtime/wayland-0" ]; then
        echo "No headless Wayland socket" >&2
        sed -n "1,70p" "$runtime/labwc.log" >&2
        exit 1
    fi
    for recipe in classic chrome "$runtime/custom.json" "$runtime/nested.json" "$runtime/shell-v4.json" "$runtime/desktop-v5.json" "$runtime/actions-v6.json" "$runtime/controls-v7.json" "$runtime/layout-v8.json" "$runtime/components-v9.json" "$runtime/desktop-actions-v9.json" "$runtime/appearance-v10.json" "$runtime/xp-luna-columns.json" "$runtime/xp-luna-default-icons.json" "$runtime/xp-luna-columns-menu" "$runtime/xp-luna-font-menu" "$runtime/xp-luna-columns-calendar" "$runtime/xp-luna-font-calendar" "$runtime/xp-luna-columns-osd" "$runtime/xp-luna-font-osd" "$runtime/overflow-v5.json" "$runtime/desktop-v5-menu" "$runtime/sidebar-v6-menu" "$runtime/composed-v6-menu" "$runtime/desktop-v5-calendar"; do
        case "$recipe" in
            */desktop-v5-calendar) label=calendar-v5 ;;
            */desktop-v5-menu) label=menu-v5 ;;
            */sidebar-v6-menu) label=menu-sidebar-v6 ;;
            */composed-v6-menu) label=menu-composed-v6 ;;
            */xp-luna-columns-menu) label=xp-luna-columns-menu ;;
            */xp-luna-font-menu) label=xp-luna-font-menu ;;
            */xp-luna-columns-calendar) label=xp-luna-columns-calendar ;;
            */xp-luna-font-calendar) label=xp-luna-font-calendar ;;
            */xp-luna-columns-osd) label=xp-luna-columns-osd ;;
            */xp-luna-font-osd) label=xp-luna-font-osd ;;
            */xp-luna-columns.json) label=xp-luna-columns ;;
            */xp-luna-default-icons.json) label=xp-luna-default-icons ;;
            */overflow-v5.json) label=overflow-v5 ;;
            */desktop-v5.json) label=desktop-v5 ;;
            */actions-v6.json) label=actions-v6 ;;
            */controls-v7.json) label=controls-v7 ;;
            */layout-v8.json) label=layout-v8 ;;
            */components-v9.json) label=components-v9 ;;
            */desktop-actions-v9.json) label=desktop-actions-v9 ;;
            */appearance-v10.json) label=appearance-v10 ;;
            */shell-v4.json) label=shell-v4 ;;
            */nested.json) label=nested-v3 ;;
            /*) label=custom ;;
            *) label=$recipe ;;
        esac
        if [ "$label" = xp-luna-columns ] || [ "$label" = xp-luna-default-icons ] || [ "$label" = xp-luna-columns-menu ] || [ "$label" = xp-luna-font-menu ] || [ "$label" = xp-luna-columns-calendar ] || [ "$label" = xp-luna-font-calendar ] || [ "$label" = xp-luna-columns-osd ] || [ "$label" = xp-luna-font-osd ]; then
            # Actual Wayland sessions run swaybg separately. Mirror that real
            # compositor process for Luna only; avoid altering legacy captures.
            WAYLAND_DISPLAY=wayland-0 swaybg \
                --image "$source_root/assets/wallpapers/luna-hills.jpg" --mode fill \
                >"$runtime/swaybg-$label.log" 2>&1 &
            wallpaper=$!
            sleep 0.5
            if ! kill -0 "$wallpaper" 2>/dev/null; then
                echo "XP Luna wallpaper process exited before capture" >&2
                sed -n "1,60p" "$runtime/swaybg-$label.log" >&2
                exit 1
            fi
        fi
        if [ "$label" = menu-v5 ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/desktop-v5.json" --preview-menu >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = menu-sidebar-v6 ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/sidebar-v6.json" --preview-menu >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = menu-composed-v6 ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/composed-v6.json" --preview-menu >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-columns-menu ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-columns.json" --preview-menu >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-font-menu ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-font.json" --preview-menu >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-columns-calendar ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-columns.json" --preview-calendar >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-font-calendar ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-font.json" --preview-calendar >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-columns-osd ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-columns.json" --preview-osd >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-font-osd ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-font.json" --preview-osd >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = calendar-v5 ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/desktop-v5.json" --preview-calendar >"$runtime/plate-$label.log" 2>&1 &
        else
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$recipe" >"$runtime/plate-$label.log" 2>&1 &
        fi
        plate=$!
        sleep 1
        state=$(ps -o stat= -p "$plate" 2>/dev/null || :)
        case "$state" in
            ""|*Z*)
                echo "Native RicePlate ($label) exited unexpectedly" >&2
                sed -n "1,80p" "$runtime/plate-$label.log" >&2
                sed -n "1,80p" "$runtime/labwc.log" >&2
                exit 1 ;;
        esac
        echo "Native RicePlate $label layer surface remained alive"
        if [ "$label" = shell-v4 ] || [ "$label" = desktop-v5 ] || [ "$label" = actions-v6 ] || [ "$label" = controls-v7 ] || [ "$label" = layout-v8 ] || [ "$label" = components-v9 ] || [ "$label" = desktop-actions-v9 ] || [ "$label" = appearance-v10 ] || [ "$label" = xp-luna-columns ] || [ "$label" = xp-luna-default-icons ] || [ "$label" = xp-luna-columns-menu ] || [ "$label" = xp-luna-font-menu ] || [ "$label" = xp-luna-columns-calendar ] || [ "$label" = xp-luna-font-calendar ] || [ "$label" = xp-luna-columns-osd ] || [ "$label" = xp-luna-font-osd ] || [ "$label" = menu-v5 ] || [ "$label" = menu-sidebar-v6 ] || [ "$label" = menu-composed-v6 ] || [ "$label" = calendar-v5 ]; then
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/$label.png"
            cp "$runtime/$label.png" "$source_root/dist/riceplate-native-preview/$label.png"
            echo "Captured real native RicePlate $label framebuffer"
        fi
        if [ "$label" = desktop-v5 ]; then
            # Exercise output reconfiguration while the SAME native shell is
            # running. These are actual compositor screenshots, not mockups.
            # The surrounding sh -c payload is single-quoted: use only
            # double quotes here so no part is evaluated by the parent shell.
            output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
            if [ -z "$output" ]; then
                echo "No headless output found for multi-size Wayland capture" >&2
                exit 1
            fi
            for mode in 1024x768 1366x768 1920x1080; do
                WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode "${mode}@60Hz" --scale 1
                sleep 0.5
                WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/desktop-v5-$mode.png"
                cp "$runtime/desktop-v5-$mode.png" \
                   "$source_root/dist/riceplate-native-preview/desktop-v5-$mode.png"
                echo "Captured native desktop-v5 at $mode"
            done
            WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1.25
            sleep 0.5
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/desktop-v5-scale-125.png"
            cp "$runtime/desktop-v5-scale-125.png" \
               "$source_root/dist/riceplate-native-preview/desktop-v5-scale-125.png"
            echo "Captured native desktop-v5 at fractional scale 1.25"
        fi
        if [ "$label" = overflow-v5 ]; then
            # Separate recipe deliberately requests x=4090 on a 1024px output.
            # This capture verifies that compositor-facing native layout reflows it.
            WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode 1024x768@60Hz --scale 1
            sleep 0.5
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/overflow-v5.png"
            cp "$runtime/overflow-v5.png" "$source_root/dist/riceplate-native-preview/overflow-v5.png"
            echo "Captured reflowed icon on 1024x768 headless output"
            # Exercise the installed Creator command against a REAL Wayland
            # framebuffer as well as its isolated unit-test fake-grim path.
            WAYLAND_DISPLAY=wayland-0 /usr/bin/python3 "$source_root/launcher.py" \
                de capture --output "$runtime/creator-v1.png" --json > "$runtime/creator-v1.json"
            cp "$runtime/creator-v1.png" "$source_root/dist/riceplate-native-preview/creator-v1.png"
            cp "$runtime/creator-v1.json" "$source_root/dist/riceplate-native-preview/creator-v1.json"
            echo "Captured real headless Wayland frame via Creator CLI"
        fi
        kill "$plate"
        wait "$plate" 2>/dev/null || :
        plate=
        if [ -n "$wallpaper" ]; then
            kill "$wallpaper"
            wait "$wallpaper" 2>/dev/null || :
            wallpaper=
        fi
    done
    # We own this exact CI compositor PID. On labwc 0.7.1 the --exit client
    # command is not a reliable external teardown mechanism in a headless job.
    kill -TERM "$compositor"
    count=0
    while [ "$count" -lt 40 ]; do
        state=$(ps -o stat= -p "$compositor" 2>/dev/null || :)
        case "$state" in
            ""|*Z*)
                wait "$compositor" 2>/dev/null || :
                echo "Native RicePlate and headless labwc shut down cleanly"
                exit 0 ;;
        esac
        count=$((count + 1))
        sleep 0.25
    done
    echo "CI labwc did not respond to SIGTERM" >&2
    sed -n "1,70p" "$runtime/labwc.log" >&2
    exit 1
' sh "$source_root" "$runtime" "$native"

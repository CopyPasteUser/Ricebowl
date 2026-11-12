#!/bin/sh
# CI-only: real headless labwc plus one separately launched native layer surface.
set -eu

source_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$source_root/components/riceplate-wayland/target/release/riceplate-native"
clicker="$source_root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
if [ ! -x "$native" ]; then
    echo "Native RicePlate binary is not built" >&2
    exit 1
fi
if [ ! -x "$clicker" ]; then
    echo "CI native virtual-pointer example is not built" >&2
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
cp "$source_root/tests/fixtures/riceplate-clip-actions-v6.json" "$runtime/riceclip-actions.json"
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
chmod 0600 "$runtime/riceclip-actions.json"
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
# A private fake Gio is visible only to this specific Luna test process.
# Never open the runner home trash or change installed desktop settings.
mkdir -m 0700 "$runtime/mock-bin"
cat >"$runtime/mock-bin/gio" <<'GIO'
#!/bin/sh
set -eu
[ "$#" -eq 2 ] || exit 64
printf '%s\n' "$1" "$2" >"$RICEBOWL_CI_TRASH_LOG"
GIO
chmod 0700 "$runtime/mock-bin/gio"
# The disposable shim records exact native argv and execs the real GTK CLI.
# No watcher starts and no host clipboard content is read.
cat >"$runtime/mock-bin/ricebowl" <<"CLIP_CLI"
#!/bin/sh
set -eu
[ "$#" -eq 4 ] && [ "$1" = de ] && [ "$2" = clip ] \
    && [ "$3" = --clip-op ] && [ "$4" = gui ] || exit 64
printf "%s\n" "$1" "$2" "$3" "$4" >"$RICEBOWL_CI_CLIP_LOG"
printf "%s\n" "$" >"$RICEBOWL_CI_CLIP_PID"
exec /usr/bin/python3 -B "$RICEBOWL_CI_SOURCE_ROOT/launcher.py" "$@"
CLIP_CLI
chmod 0700 "$runtime/mock-bin/ricebowl"
export XDG_RUNTIME_DIR="$runtime"
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=1
export WLR_RENDERER=pixman
export RICEBOWL_DE_NESTED=1

dbus-run-session -- sh -eu -c '
    source_root=$1
    runtime=$2
    native=$3
    clicker=$4
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
    for recipe in classic chrome "$runtime/custom.json" "$runtime/nested.json" "$runtime/shell-v4.json" "$runtime/desktop-v5.json" "$runtime/actions-v6.json" "$runtime/riceclip-actions.json" "$runtime/controls-v7.json" "$runtime/layout-v8.json" "$runtime/components-v9.json" "$runtime/desktop-actions-v9.json" "$runtime/appearance-v10.json" "$runtime/xp-luna-columns.json" "$runtime/xp-luna-default-icons.json" "$runtime/xp-luna-columns-menu" "$runtime/xp-luna-font-menu" "$runtime/xp-luna-columns-calendar" "$runtime/xp-luna-font-calendar" "$runtime/xp-luna-columns-osd" "$runtime/xp-luna-font-osd" "$runtime/xp-luna-columns-notifications" "$runtime/xp-luna-columns-notifications-scroll" "$runtime/xp-luna-font-notifications" "$runtime/xp-luna-columns-notification-detail" "$runtime/xp-luna-font-notification-detail" "$runtime/overflow-v5.json" "$runtime/desktop-v5-menu" "$runtime/sidebar-v6-menu" "$runtime/composed-v6-menu" "$runtime/desktop-v5-calendar"; do
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
            */xp-luna-columns-notifications) label=xp-luna-columns-notifications ;;
            */xp-luna-columns-notifications-scroll) label=xp-luna-columns-notifications-scroll ;;
            */xp-luna-font-notifications) label=xp-luna-font-notifications ;;
            */xp-luna-columns-notification-detail) label=xp-luna-columns-notification-detail ;;
            */xp-luna-font-notification-detail) label=xp-luna-font-notification-detail ;;
            */xp-luna-columns.json) label=xp-luna-columns ;;
            */xp-luna-default-icons.json) label=xp-luna-default-icons ;;
            */overflow-v5.json) label=overflow-v5 ;;
            */desktop-v5.json) label=desktop-v5 ;;
            */actions-v6.json) label=actions-v6 ;;
            */riceclip-actions.json) label=riceclip-actions ;;
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
        if [ "$label" = xp-luna-columns ] || [ "$label" = xp-luna-default-icons ] || [ "$label" = xp-luna-columns-menu ] || [ "$label" = xp-luna-font-menu ] || [ "$label" = xp-luna-columns-calendar ] || [ "$label" = xp-luna-font-calendar ] || [ "$label" = xp-luna-columns-osd ] || [ "$label" = xp-luna-font-osd ] || [ "$label" = xp-luna-columns-notifications ] || [ "$label" = xp-luna-columns-notifications-scroll ] || [ "$label" = xp-luna-font-notifications ] || [ "$label" = xp-luna-columns-notification-detail ] || [ "$label" = xp-luna-font-notification-detail ]; then
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
        elif [ "$label" = xp-luna-columns-notifications ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-columns.json" --preview-notifications >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-columns-notifications-scroll ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-columns.json" --preview-notifications-scroll >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-font-notifications ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-font.json" --preview-notifications >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-columns-notification-detail ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-columns.json" --preview-notification-detail >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-font-notification-detail ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-font.json" --preview-notification-detail >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = calendar-v5 ]; then
            WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/desktop-v5.json" --preview-calendar >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = riceclip-actions ]; then
            PATH="$runtime/mock-bin:$PATH" GDK_BACKEND=wayland \
                RICEBOWL_CI_CLIP_LOG="$runtime/clip-action-argv.log" \
                RICEBOWL_CI_CLIP_PID="$runtime/clip-action-gui.pid" \
                RICEBOWL_CI_SOURCE_ROOT="$source_root" \
                WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$recipe" \
                >"$runtime/plate-$label.log" 2>&1 &
        elif [ "$label" = xp-luna-columns ]; then
            RICEBOWL_DE_TRACE_MENU=1 PATH="$runtime/mock-bin:$PATH" \
                RICEBOWL_CI_TRASH_LOG="$runtime/trash-gio.log" \
                WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$recipe" \
                >"$runtime/plate-$label.log" 2>&1 &
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
        if [ "$label" = shell-v4 ] || [ "$label" = desktop-v5 ] || [ "$label" = actions-v6 ] || [ "$label" = riceclip-actions ] || [ "$label" = controls-v7 ] || [ "$label" = layout-v8 ] || [ "$label" = components-v9 ] || [ "$label" = desktop-actions-v9 ] || [ "$label" = appearance-v10 ] || [ "$label" = xp-luna-columns ] || [ "$label" = xp-luna-default-icons ] || [ "$label" = xp-luna-columns-menu ] || [ "$label" = xp-luna-font-menu ] || [ "$label" = xp-luna-columns-calendar ] || [ "$label" = xp-luna-font-calendar ] || [ "$label" = xp-luna-columns-osd ] || [ "$label" = xp-luna-font-osd ] || [ "$label" = xp-luna-columns-notifications ] || [ "$label" = xp-luna-columns-notifications-scroll ] || [ "$label" = xp-luna-font-notifications ] || [ "$label" = xp-luna-columns-notification-detail ] || [ "$label" = xp-luna-font-notification-detail ] || [ "$label" = menu-v5 ] || [ "$label" = menu-sidebar-v6 ] || [ "$label" = menu-composed-v6 ] || [ "$label" = calendar-v5 ]; then
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/$label.png"
            cp "$runtime/$label.png" "$source_root/dist/riceplate-native-preview/$label.png"
            echo "Captured real native RicePlate $label framebuffer"
        fi
        if [ "$label" = xp-luna-columns-notifications-scroll ]; then
            # A real Wayland virtual pointer must change the visible RicePop
            # page, then restore it with the opposite axis. The preview has
            # seven offline sample notices and never reads the host Mako log.
            WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 100 600 1366 768
            sleep 0.25
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/$label-hover.png"
            cp "$runtime/$label-hover.png" "$source_root/dist/riceplate-native-preview/$label-hover.png"
            WAYLAND_DISPLAY=wayland-0 "$clicker" --scroll-down 100 600 1366 768
            sleep 0.25
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/$label-paged.png"
            cp "$runtime/$label-paged.png" "$source_root/dist/riceplate-native-preview/$label-paged.png"
            WAYLAND_DISPLAY=wayland-0 "$clicker" --scroll-up 100 600 1366 768
            sleep 0.25
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/$label-restored.png"
            cp "$runtime/$label-restored.png" "$source_root/dist/riceplate-native-preview/$label-restored.png"
            kill -0 "$plate"
            echo "Native RicePop notification wheel paged and reversed in labwc"
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
            # A fractional-scale screenshot must not silently contaminate all
            # later recipe captures. In particular, the nominal Luna 1x menu,
            # icons and OSD need their own explicit output geometry.
            WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1
            sleep 0.5
        fi
        if [ "$label" = xp-luna-columns ]; then
            # Capture closed AND opened menus from the same running native
            # shell and swaybg process. Comparing two separately launched
            # wallpaper sessions can report irrelevant panel/background diffs
            # instead of the actual menu change. The virtual pointer provides
            # a genuine compositor-delivered Start click at each geometry.
            output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
            if [ -z "$output" ]; then
                echo "No headless output for Luna live-geometry capture" >&2
                exit 1
            fi
            for mode in 1024x768 1366x768 1920x1080; do
                WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode "${mode}@60Hz" --scale 1
                sleep 0.65
                WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/$label-$mode.png"
                cp "$runtime/$label-$mode.png" \
                   "$source_root/dist/riceplate-native-preview/$label-$mode.png"
                height=${mode#*x}
                WAYLAND_DISPLAY=wayland-0 "$clicker" 35 "$((height - 20))" "${mode%x*}" "$height"
                sleep 0.35
                WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-columns-menu-$mode.png"
                cp "$runtime/xp-luna-columns-menu-$mode.png" \
                   "$source_root/dist/riceplate-native-preview/xp-luna-columns-menu-$mode.png"
                WAYLAND_DISPLAY=wayland-0 "$clicker" 35 "$((height - 20))" "${mode%x*}" "$height"
                sleep 0.25
                echo "Captured live Luna closed/open pair at $mode scale 1"
            done
            WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1.25
            sleep 0.65
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/$label-scale-125.png"
            cp "$runtime/$label-scale-125.png" \
               "$source_root/dist/riceplate-native-preview/$label-scale-125.png"
            WAYLAND_DISPLAY=wayland-0 "$clicker" 35 748 1366 768
            sleep 0.35
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-columns-menu-scale-125.png"
            cp "$runtime/xp-luna-columns-menu-scale-125.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-columns-menu-scale-125.png"
            # Emit only menu-geometry diagnostics for the direct Full-HD ->
            # fractional-scale transition. No user data or full logs are
            # archived; this identifies whether the pending layer configure
            # or the virtual-pointer delivery made an opened frame invisible.
            echo "Luna 125% live output:"
            WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1,9p"
            grep -E "RicePlate: (menu trace|ignoring superseded native menu|compositor proposed unsupported native menu|native menu buffer unavailable|cannot allocate native menu)" \
                "$runtime/plate-$label.log" | tail -n 22 || true
            WAYLAND_DISPLAY=wayland-0 "$clicker" 35 748 1366 768
            sleep 0.25
            echo "Captured live Luna closed/open pair at 1366x768 scale 1.25"
            WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1
            sleep 0.5
        fi
        if [ "$label" = xp-luna-columns ]; then
            # In contrast to --preview-menu, these are real compositor pointer
            # clicks on the green Start button of a running native shell.
            # Preserve genuine open and closed frames as CI evidence.
            for geometry in 1024x768 1920x1080 scale-125; do
                case "$geometry" in
                    1024x768) mode=1024x768; width=1024; height=768; scale=1 ;;
                    1920x1080) mode=1920x1080; width=1920; height=1080; scale=1 ;;
                    scale-125) mode=1366x768; width=1366; height=768; scale=1.25 ;;
                esac
                WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" \
                    --custom-mode "${mode}@60Hz" --scale "$scale"
                sleep 0.65
                kill -0 "$plate"
                button_y=$((height - 20))
                if [ "$geometry" = 1024x768 ]; then
                    # Real compositor-delivered motion, with no click:
                    # two screenshots prove Start has an interactive hover
                    # face independently of opening the menu. Grim excludes
                    # the cursor itself; a no-op hover yields equal PNGs.
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 250 "$button_y" "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-start-idle-$geometry.png"
                    cp "$runtime/xp-luna-pointer-start-idle-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-start-idle-$geometry.png"
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 35 "$button_y" "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-start-hover-$geometry.png"
                    cp "$runtime/xp-luna-pointer-start-hover-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-start-hover-$geometry.png"
                    if cmp -s "$runtime/xp-luna-pointer-start-idle-$geometry.png" \
                              "$runtime/xp-luna-pointer-start-hover-$geometry.png"; then
                        echo "Native Luna Start hover produced no compositor-visible state" >&2
                        exit 1
                    fi
                    echo "Captured native Luna idle/hover pointer frames at $geometry"
                fi
                WAYLAND_DISPLAY=wayland-0 "$clicker" 35 "$button_y" "$width" "$height"
                sleep 0.35
                WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-open-$geometry.png"
                cp "$runtime/xp-luna-pointer-open-$geometry.png" \
                   "$source_root/dist/riceplate-native-preview/xp-luna-pointer-open-$geometry.png"
                if [ "$geometry" = 1024x768 ]; then
                    # Exercise the actual menu header hit targets via labwc,
                    # not the Rust hit tester or a --preview-menu shortcut.
                    # The 320x304 popup sits directly above the 40px panel.
                    header_y=$((height - 40 - 304 + 16))
                    WAYLAND_DISPLAY=wayland-0 "$clicker" 220 "$header_y" "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-find-$geometry.png"
                    cp "$runtime/xp-luna-pointer-find-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-find-$geometry.png"
                    # A compositor-delivered wheel axis must page long search
                    # results while the popup remains open and interactive.
                    # Capture hover separately so highlight-only motion cannot
                    # masquerade as successful paging in the pixel assertion.
                    # Match the wheel-event coordinates so pointer motion
                    # cannot change the selected search row between the hover
                    # baseline and the reverse-wheel restoration. This matters
                    # now that Luna searches eight rather than six actions.
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 220 685 "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-find-hover-$geometry.png"
                    cp "$runtime/xp-luna-pointer-find-hover-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-find-hover-$geometry.png"
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --scroll-down 220 600 "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-find-paged-$geometry.png"
                    cp "$runtime/xp-luna-pointer-find-paged-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-find-paged-$geometry.png"
                    # Reverse the real wheel axis without closing the menu.
                    # Land on the last selected row of the scrolled page:
                    # pointer motion alone must NOT restore the first page.
                    # Only the negative compositor axis event can do that.
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --scroll-up 220 685 "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-find-restored-$geometry.png"
                    cp "$runtime/xp-luna-pointer-find-restored-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-find-restored-$geometry.png"
                    WAYLAND_DISPLAY=wayland-0 "$clicker" 220 "$header_y" "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 "$clicker" 284 "$header_y" "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-saved-$geometry.png"
                    cp "$runtime/xp-luna-pointer-saved-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-saved-$geometry.png"
                    WAYLAND_DISPLAY=wayland-0 "$clicker" 284 "$header_y" "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-return-$geometry.png"
                    cp "$runtime/xp-luna-pointer-return-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-return-$geometry.png"
                    # The first left-column action must open the native XDG
                    # All Programs page, then the real header Back hit target
                    # must restore the two-column Luna menu.
                    WAYLAND_DISPLAY=wayland-0 "$clicker" 60 552 "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-programs-$geometry.png"
                    cp "$runtime/xp-luna-pointer-programs-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-programs-$geometry.png"
                    WAYLAND_DISPLAY=wayland-0 "$clicker" 220 "$header_y" "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-programs-back-$geometry.png"
                    cp "$runtime/xp-luna-pointer-programs-back-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-programs-back-$geometry.png"
                    # The real full-size XP footer now has three independent
                    # hit boxes. Move without clicking: do not lock CI or log
                    # out the isolated labwc session during visual QA.
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 45 713 "$width" "$height"
                    sleep 0.25
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-footer-lock-hover-$geometry.png"
                    cp "$runtime/xp-luna-footer-lock-hover-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-footer-lock-hover-$geometry.png"
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 138 713 "$width" "$height"
                    sleep 0.25
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-footer-logout-hover-$geometry.png"
                    cp "$runtime/xp-luna-footer-logout-hover-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-footer-logout-hover-$geometry.png"
                    if cmp -s "$runtime/xp-luna-footer-lock-hover-$geometry.png" \
                              "$runtime/xp-luna-footer-logout-hover-$geometry.png"; then
                        echo "XP Luna native Lock footer hover did not redraw independently" >&2
                        exit 1
                    fi
                    # Exercise real labwc pointer motion across the new XP
                    # places and existing Session rows on 1024x768. The popup
                    # starts at screen y=424; native hit centers are y=80 and
                    # y=234. Capture both without launching host applications.
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 190 504 "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-places-documents-$geometry.png"
                    cp "$runtime/xp-luna-pointer-places-documents-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-places-documents-$geometry.png"
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 190 658 "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-session-logout-$geometry.png"
                    cp "$runtime/xp-luna-pointer-session-logout-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-session-logout-$geometry.png"
                    if cmp -s "$runtime/xp-luna-pointer-places-documents-$geometry.png" \
                              "$runtime/xp-luna-pointer-session-logout-$geometry.png"; then
                        echo "XP Luna Places and Session hover did not alter the native compositor frame" >&2
                        exit 1
                    fi
                    # Pin one validated action with a real compositor
                    # right-button press, open Saved, then unpin it there.
                    # This must work without any keyboard-only F2 shortcut.
                    WAYLAND_DISPLAY=wayland-0 "$clicker" 220 "$header_y" "$width" "$height"
                    sleep 0.2
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --right-click 60 552 "$width" "$height"
                    sleep 0.2
                    WAYLAND_DISPLAY=wayland-0 "$clicker" 284 "$header_y" "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-saved-pinned-$geometry.png"
                    cp "$runtime/xp-luna-pointer-saved-pinned-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-saved-pinned-$geometry.png"
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --right-click 60 552 "$width" "$height"
                    sleep 0.35
                    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-saved-unpinned-$geometry.png"
                    cp "$runtime/xp-luna-pointer-saved-unpinned-$geometry.png" \
                       "$source_root/dist/riceplate-native-preview/xp-luna-pointer-saved-unpinned-$geometry.png"
                    WAYLAND_DISPLAY=wayland-0 "$clicker" 284 "$header_y" "$width" "$height"
                    sleep 0.2
                    kill -0 "$plate"
                    echo "Clicked native Luna Find/Back, Saved/Back and right-click pin/unpin at $geometry"
                fi
                WAYLAND_DISPLAY=wayland-0 "$clicker" 35 "$button_y" "$width" "$height"
                sleep 0.35
                WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-pointer-closed-$geometry.png"
                cp "$runtime/xp-luna-pointer-closed-$geometry.png" \
                   "$source_root/dist/riceplate-native-preview/xp-luna-pointer-closed-$geometry.png"
                kill -0 "$plate"
                echo "Clicked Luna Start open/closed at $geometry scale $scale"
            done
            WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" --custom-mode 1366x768@60Hz --scale 1
            sleep 0.5
            # Actual labwc-delivered left-click on the fourth Luna desktop
            # icon (24,400; 104x88). Capture exact Gio argv in a private
            # stand-in; no host trash backend or user files are touched.
            test ! -e "$runtime/trash-gio.log"
            WAYLAND_DISPLAY=wayland-0 "$clicker" 68 435 1366 768
            count=0
            while [ ! -s "$runtime/trash-gio.log" ] && [ "$count" -lt 25 ]; do
                count=$((count + 1))
                sleep 0.1
            done
            expected=$(printf "open\ntrash:///")
            actual=$(cat "$runtime/trash-gio.log" 2>/dev/null || :)
            if [ "$actual" != "$expected" ]; then
                echo "Luna Recycle Bin compositor click did not issue safe Gio open" >&2
                exit 1
            fi
            kill -0 "$plate"
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-recycle-bin-click.png"
            cp "$runtime/xp-luna-recycle-bin-click.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-recycle-bin-click.png"
            echo "Verified real Luna Recycle Bin pointer activation through isolated Gio stand-in"
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
            # RiceShot reuses the same safe no-overwrite PNG writer; prove
            # both full-display and real named-output grim paths in labwc.
            output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
            test -n "$output"
            WAYLAND_DISPLAY=wayland-0 /usr/bin/python3 "$source_root/launcher.py" \
                de shot --output "$runtime/riceshot-full.png" --json > "$runtime/riceshot-full.json"
            WAYLAND_DISPLAY=wayland-0 /usr/bin/python3 "$source_root/launcher.py" \
                de shot --shot-mode output --monitor "$output" \
                --output "$runtime/riceshot-output.png" --json > "$runtime/riceshot-output.json"
            WAYLAND_DISPLAY=wayland-0 /usr/bin/python3 "$source_root/launcher.py" \
                de shot --clipboard --json > "$runtime/riceshot-clipboard.json"
            WAYLAND_DISPLAY=wayland-0 timeout 5s wl-paste --no-newline \
                --type image/png > "$runtime/riceshot-clipboard.png"
            /usr/bin/python3 - "$runtime" <<"PY"
import json
import hashlib
from pathlib import Path
import struct
import sys

root = Path(sys.argv[1])
for mode in ("full", "output"):
    report = json.loads((root / f"riceshot-{mode}.json").read_text())
    capture = report["capture"]
    image = (root / f"riceshot-{mode}.png").read_bytes()
    assert report["ok"] and report["riceshot_version"] == 1
    assert capture["mode"] == mode
    assert image[:8] == bytes.fromhex("89504e470d0a1a0a")
    assert struct.unpack(">II", image[16:24]) == (capture["width"], capture["height"])
    assert len(image) == capture["bytes"]
report = json.loads((root / "riceshot-clipboard.json").read_text())
capture = report["capture"]
image = (root / "riceshot-clipboard.png").read_bytes()
assert report["ok"] and capture["clipboard_updated"] is True
assert capture["destination"] == "clipboard" and "path" not in capture
assert hashlib.sha256(image).hexdigest() == capture["sha256"]
PY
            echo "RiceShot captured real full, named-output and clipboard PNGs in labwc"
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
' sh "$source_root" "$runtime" "$native" "$clicker"

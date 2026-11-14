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
# Real pointer-to-RiceField dispatch is captured as argv, without ever
# launching a file manager on the CI runner or touching user files.
cat >"$runtime/mock-bin/ricefield" <<'RICEFIELD'
#!/bin/sh
set -eu
[ "$#" -eq 4 ] || exit 64
printf '%s\n' "$1" "$2" "$3" "$4" >"$RICEBOWL_CI_RICEFIELD_LOG"
RICEFIELD
chmod 0700 "$runtime/mock-bin/ricefield"
# The disposable shim records exact native argv and execs the real GTK CLI.
# No watcher starts and no host clipboard content is read.
cat >"$runtime/mock-bin/ricebowl" <<"CLIP_CLI"
#!/bin/sh
set -eu
[ "$#" -eq 4 ] && [ "$1" = de ] && [ "$2" = clip ] \
    && [ "$3" = --clip-op ] && [ "$4" = gui ] || exit 64
# The wrapper shell becomes this Python process. Record the actual PID
# directly, without relying on shell PID expansion in a generated script.
exec /usr/bin/python3 -B -c '
import os
import sys
from pathlib import Path
Path(os.environ["RICEBOWL_CI_CLIP_PID"]).write_text(str(os.getpid()) + "\n")
Path(os.environ["RICEBOWL_CI_CLIP_LOG"]).write_text("\n".join(sys.argv[1:]) + "\n")
os.execv(sys.executable, [sys.executable, "-B",
         os.environ["RICEBOWL_CI_SOURCE_ROOT"] + "/launcher.py", *sys.argv[1:]])
' "$@"
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
        if [ -s "$runtime/clip-action-gui.pid" ]; then
            clip_pid=$(cat "$runtime/clip-action-gui.pid" 2>/dev/null || :)
            case "$clip_pid" in
                ""|*[!0-9]*) : ;;
                *) kill "$clip_pid" 2>/dev/null || : ;;
            esac
        fi
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
                RICEBOWL_CI_RICEFIELD_LOG="$runtime/ricefield-argv.log" \
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
        if [ "$label" = riceclip-actions ]; then
            # A real Wayland virtual-pointer click crosses the native panel,
            # the fixed action dispatcher and the GTK3 browser entrypoint.
            # The only shim logs argv before execing the real Python GUI.
            output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
            test -n "$output"
            WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" \
                --custom-mode 1366x768@60Hz --scale 1
            sleep 0.35
            WAYLAND_DISPLAY=wayland-0 grim - >"$runtime/riceclip-panel-before.png"
            test ! -e "$runtime/clip-action-argv.log"
            WAYLAND_DISPLAY=wayland-0 "$clicker" 135 20 1366 768
            count=0
            while [ ! -s "$runtime/clip-action-argv.log" ] && [ "$count" -lt 30 ]; do
                count=$((count + 1))
                sleep 0.1
            done
            expected=$(printf "de\nclip\n--clip-op\ngui")
            actual=$(cat "$runtime/clip-action-argv.log" 2>/dev/null || :)
            if [ "$actual" != "$expected" ] || [ ! -s "$runtime/clip-action-gui.pid" ]; then
                echo "RiceClip panel click did not dispatch the exact safe GUI command" >&2
                exit 1
            fi
            clip_pid=$(cat "$runtime/clip-action-gui.pid")
            case "$clip_pid" in
                ""|*[!0-9]*) echo "Invalid RiceClip GUI PID" >&2; exit 1 ;;
            esac
            count=0
            while [ "$count" -lt 30 ]; do
                kill -0 "$clip_pid" 2>/dev/null || {
                    echo "RiceClip GTK client exited before compositor capture" >&2
                    exit 1
                }
                sleep 0.15
                WAYLAND_DISPLAY=wayland-0 grim - >"$runtime/riceclip-panel-after.png"
                if /usr/bin/python3 - "$runtime/riceclip-panel-before.png" \
                    "$runtime/riceclip-panel-after.png" <<"PY"
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as before, Image.open(sys.argv[2]) as after:
    before.load()
    after.load()
    if before.size != (1366, 768) or after.size != before.size:
        raise SystemExit(1)
    diff = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
    raise SystemExit(0 if sum(any(pixel) for pixel in diff.getdata()) > 15000 else 1)
PY
                then
                    break
                fi
                count=$((count + 1))
            done
            if [ "$count" -eq 30 ]; then
                echo "RiceClip GTK window did not appear on the compositor output" >&2
                exit 1
            fi
            kill -0 "$plate"
            artifact="$source_root/dist/riceplate-native-preview"
            cp "$runtime/riceclip-panel-after.png" \
                "$artifact/riceclip-panel-action-1366x768.png"
            /usr/bin/python3 - "$artifact/riceclip-panel-action-1366x768.png" \
                "$artifact/riceclip-panel-action-1366x768.json" <<"PY"
import hashlib
import json
import os
from pathlib import Path
import sys
from PIL import Image
image, manifest = map(Path, sys.argv[1:])
with Image.open(image) as screenshot:
    screenshot.load()
    dimensions = screenshot.size
manifest.write_text(json.dumps({
    "source": "real headless labwc compositor, grim",
    "renderer": "pixman",
    "wayland_pointer_click": [135, 20],
    "action": "clip-history",
    "gui": "real GTK3 RiceClip client, watcher absent",
    "command_verified": ["de", "clip", "--clip-op", "gui"],
    "resolution": dimensions,
    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
    "commit": os.environ.get("GITHUB_SHA", "unavailable"),
    "run_id": os.environ.get("GITHUB_RUN_ID", "unavailable"),
}, indent=2) + "\n")
PY
            kill "$clip_pid" 2>/dev/null || :
            rm -f "$runtime/clip-action-gui.pid"
            echo "Real native RicePlate click launched the on-demand GTK RiceClip browser"
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
                    # All Programs is now the actual bottom-left XP tile;
                    # click its moved real hitbox, then test the real Back action.
                    WAYLAND_DISPLAY=wayland-0 "$clicker" 60 680 "$width" "$height"
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
                    WAYLAND_DISPLAY=wayland-0 "$clicker" --right-click 60 680 "$width" "$height"
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
            # XP semantics: first compositor-delivered click selects;
            # two subsequent clicks within 650 ms activate the safe Gio target.
            # All events run in isolated labwc with a private Gio stand-in.
            test ! -e "$runtime/trash-gio.log"
            WAYLAND_DISPLAY=wayland-0 "$clicker" 68 435 1366 768
            sleep 0.2
            if [ -e "$runtime/trash-gio.log" ]; then
                echo "Luna single-select unexpectedly opened a desktop location" >&2
                exit 1
            fi
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-icon-selected.png"
            cp "$runtime/xp-luna-icon-selected.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-icon-selected.png"
            # Expire the initial click, then immediately perform a fresh pair.
            sleep 0.85
            WAYLAND_DISPLAY=wayland-0 "$clicker" 68 435 1366 768
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
            echo "Verified Luna single-select and double-open through real pointer/Gio events"
            # Right-click must open a bounded popup, never launch a shortcut.
            rm -f "$runtime/trash-gio.log"
            WAYLAND_DISPLAY=wayland-0 "$clicker" --right-click 68 435 1366 768
            sleep 0.3
            if [ -e "$runtime/trash-gio.log" ]; then
                echo "Luna right-click unexpectedly executed a desktop shortcut" >&2
                exit 1
            fi
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-shortcut-context.png"
            cp "$runtime/xp-luna-shortcut-context.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-shortcut-context.png"
            # Real pointer-driven properties transition on the SAME bounded
            # output-local popup. No shortcut launch, no external settings app.
            # Properties row is the fifth row (148..175), Back is at 150..177.
            WAYLAND_DISPLAY=wayland-0 "$clicker" 88 596 1366 768
            sleep 0.3
            if [ -e "$runtime/trash-gio.log" ]; then
                echo "Luna properties unexpectedly launched a shortcut" >&2
                exit 1
            fi
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-shortcut-properties.png"
            cp "$runtime/xp-luna-shortcut-properties.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-shortcut-properties.png"
            /usr/bin/python3 - "$runtime/xp-luna-shortcut-context.png" \
                "$runtime/xp-luna-shortcut-properties.png" <<"PY"
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as menu, Image.open(sys.argv[2]) as details:
    menu.load()
    details.load()
    if menu.size != (1366, 768) or details.size != menu.size:
        raise SystemExit("Luna properties screenshot geometry changed")
    # Popup is output-local; check the actual compositor pixels, not just
    # that both PNGs exist or have different metadata.
    region = (68, 435, 292, 625)
    if ImageChops.difference(menu.crop(region).convert("RGB"),
                            details.crop(region).convert("RGB")).getbbox() is None:
        raise SystemExit("Luna properties did not redraw its native popup")
PY
            WAYLAND_DISPLAY=wayland-0 "$clicker" 88 596 1366 768
            sleep 0.15
            if [ -e "$runtime/trash-gio.log" ]; then
                echo "Luna properties Back unexpectedly launched a shortcut" >&2
                exit 1
            fi
            # Popup anchored at (68,435); Open occupies row 36..63.
            WAYLAND_DISPLAY=wayland-0 "$clicker" 88 485 1366 768
            count=0
            while [ ! -s "$runtime/trash-gio.log" ] && [ "$count" -lt 25 ]; do
                count=$((count + 1))
                sleep 0.1
            done
            actual=$(cat "$runtime/trash-gio.log" 2>/dev/null || :)
            if [ "$actual" != "$expected" ]; then
                echo "Luna right-click context Open failed the actual Wayland/Gio path" >&2
                exit 1
            fi
            kill -0 "$plate"
            echo "Verified Luna right-click context Open through labwc virtual pointer"
            # The XP Explorer shortcut must prefer RiceField 1.0, with
            # exactly the documented theme/separate-window argv and the
            # fixed root path. No spurious Gio call is permitted.
            rm -f "$runtime/trash-gio.log" "$runtime/ricefield-argv.log"
            WAYLAND_DISPLAY=wayland-0 "$clicker" 68 125 1366 768
            WAYLAND_DISPLAY=wayland-0 "$clicker" 68 125 1366 768
            count=0
            while [ ! -s "$runtime/ricefield-argv.log" ] && [ "$count" -lt 25 ]; do
                count=$((count + 1))
                sleep 0.1
            done
            expected=$(printf "%s\\n" --theme xp-luna --separate-window /)
            actual=$(cat "$runtime/ricefield-argv.log" 2>/dev/null || :)
            if [ "$actual" != "$expected" ] || [ -e "$runtime/trash-gio.log" ]; then
                echo "Luna My Computer did not dispatch exact RiceField XP argv" >&2
                exit 1
            fi
            kill -0 "$plate"
            echo "Verified My Computer real pointer dispatch to RiceField XP theme"
            # XP Start Run and Help are real bounded overlay surfaces.
            # Capture the actual compositor frames, not an illustrated mock.
            WAYLAND_DISPLAY=wayland-0 "$clicker" 35 748 1366 768
            sleep 0.3
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-parity-start.png"
            cp "$runtime/xp-luna-parity-start.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-parity-start.png"
            # On 1366x768 the 400x380 Start popup is at y348. The 10-row
            # native right shelf places Help at logical y176..194.
            WAYLAND_DISPLAY=wayland-0 "$clicker" 265 580 1366 768
            sleep 0.35
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-parity-help.png"
            cp "$runtime/xp-luna-parity-help.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-parity-help.png"
            # The 448x232 overlay is centered at (459,248). Close uses
            # its actual on-screen button and must return keyboard ownership.
            WAYLAND_DISPLAY=wayland-0 "$clicker" 759 450 1366 768
            sleep 0.25
            WAYLAND_DISPLAY=wayland-0 "$clicker" 35 748 1366 768
            sleep 0.25
            # Run is the next right-shelf action: logical y194..212.
            WAYLAND_DISPLAY=wayland-0 "$clicker" 265 602 1366 768
            sleep 0.35
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-parity-run.png"
            cp "$runtime/xp-luna-parity-run.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-parity-run.png"
            # Real compositor-owned keyboard input, not a synthetic state or
            # a mocked screenshot. The native Run overlay owns focus here.
            command -v wtype >/dev/null || { echo "wtype missing" >&2; exit 1; }
            WAYLAND_DISPLAY=wayland-0 wtype -d 35 abcd
            sleep 0.25
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-parity-run-typed.png"
            cp "$runtime/xp-luna-parity-run-typed.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-parity-run-typed.png"
            # Left, Backspace, and an insertion must edit in-place:
            # "abcd" -> "abd" -> "abXd", never execute anything.
            WAYLAND_DISPLAY=wayland-0 wtype -k Left -k BackSpace
            WAYLAND_DISPLAY=wayland-0 wtype X
            sleep 0.25
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-parity-run-edited.png"
            cp "$runtime/xp-luna-parity-run-edited.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-parity-run-edited.png"
            # Home plus four Deletes must restore the actual empty input.
            WAYLAND_DISPLAY=wayland-0 wtype -k Home -k Delete -k Delete -k Delete -k Delete
            sleep 0.25
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-parity-run-cleared.png"
            cp "$runtime/xp-luna-parity-run-cleared.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-parity-run-cleared.png"
            # Submitting an empty command must display an error, never
            # dispatch an empty argv or perform any host operation.
            WAYLAND_DISPLAY=wayland-0 "$clicker" 759 450 1366 768
            sleep 0.25
            WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xp-luna-parity-run-empty.png"
            cp "$runtime/xp-luna-parity-run-empty.png" \
               "$source_root/dist/riceplate-native-preview/xp-luna-parity-run-empty.png"
            WAYLAND_DISPLAY=wayland-0 "$clicker" 843 450 1366 768
            sleep 0.25
            kill -0 "$plate"
            /usr/bin/python3 - "$runtime" <<PY
from pathlib import Path
from PIL import Image, ImageChops

folder = Path("$runtime")
names = ["start", "help", "run", "run-typed", "run-edited", "run-cleared", "run-empty"]
images = {name: Image.open(folder / f"xp-luna-parity-{name}.png").convert("RGB")
          for name in names}
assert all(img.size == (1366, 768) for img in images.values())
region = (459, 248, 907, 480)
def changed(a, b):
    delta = ImageChops.difference(images[a].crop(region), images[b].crop(region))
    return sum(1 for r, g, b in delta.getdata() if max(r, g, b) > 18)
assert changed("start", "help") > 5000, "Help did not open a real Wayland dialog"
assert changed("start", "run") > 5000, "Run did not open a real Wayland dialog"
assert changed("help", "run") > 1500, "Run and Help must have distinct real UI"
assert changed("run", "run-empty") > 80, "Empty Run input must show a visible error"
# Verify actual Wayland virtual-keyboard input changed only the bounded Run
# text field. The typed/edited/cleared screenshots are genuine grim frames.
text_region = (577, 359, 883, 391)
def text_changed(a, b):
    delta = ImageChops.difference(
        images[a].crop(text_region), images[b].crop(text_region))
    return sum(1 for pixel in delta.getdata() if max(pixel) > 18)
assert text_changed("run", "run-typed") > 20, "Wayland typing did not reach native Run"
assert text_changed("run-typed", "run-edited") > 20, (
    "Wayland Left/Backspace/insertion did not repaint Run"
)
assert text_changed("run", "run-cleared") < 8, (
    "Wayland Home/Delete failed to clear the Run input"
)
# Native Run paints a visible 2x16px input caret at (128,120)
# relative to its (459,248) compositor surface. Probe actual grim PNG
# pixels rather than accepting a model fixture or a painted mockup.
caret = images["run"].getpixel((587, 372))
background = images["run"].getpixel((594, 372))
assert max(abs(a-b) for a, b in zip(caret, background)) > 75, (
    "Native Run input caret is not visible in real labwc framebuffer"
)
print("Validated native labwc Run/Help screenshots, real virtual keyboard edits, caret and empty-input error")
PY
            echo "Verified real Luna Start Help and Run dialogs at 1366x768"
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
    # Exercise real XDG file surfaces in a full isolated session. All earlier
    # recipe screenshots run nested and must remain isolated from host files.
    output=$(WAYLAND_DISPLAY=wayland-0 wlr-randr | sed -n "1s/[[:space:]].*//p")
    test -n "$output"
    WAYLAND_DISPLAY=wayland-0 wlr-randr --output "$output" \
        --custom-mode 1366x768@60Hz --scale 1
    mkdir -m 0700 "$runtime/file-home" "$runtime/file-home/Desktop" "$runtime/file-config"
    printf "%s\n" "XDG_DESKTOP_DIR=\"\$HOME/Desktop\"" \
        > "$runtime/file-config/user-dirs.dirs"
    printf "%s\n" "RiceBowl native XDG file acceptance" \
        > "$runtime/file-home/Desktop/00-note.txt"
    # A .desktop file and a symlink must be visible, but never executables.
    printf "%s\n" "[Desktop Entry]" "Type=Application" "Name=Unsafe test" \
        "Exec=/usr/bin/false" > "$runtime/file-home/Desktop/01-app.desktop"
    ln -s /etc/passwd "$runtime/file-home/Desktop/02-outside-link"
    HOME="$runtime/file-home" XDG_CONFIG_HOME="$runtime/file-config" \
        RICEBOWL_DE_NESTED=0 RICEBOWL_DE_TRACE_FILES=1 RICEBOWL_DE_TRACE_FOCUS=1 \
        PATH="$runtime/mock-bin:$PATH" \
        RICEBOWL_CI_TRASH_LOG="$runtime/full-gio.log" \
        RICEBOWL_CI_RICEFIELD_LOG="$runtime/full-ricefield.log" \
        WAYLAND_DISPLAY=wayland-0 "$native" --recipe "$runtime/xp-luna-columns.json" \
        > "$runtime/file-plate.log" 2>&1 &
    plate=$!
    sleep 1.3
    kill -0 "$plate"
    grep -Fq "RicePlate: XDG mapped" "$runtime/file-plate.log" || {
        echo "Full native session never mapped a real XDG Desktop file layer" >&2
        sed -n "1,75p" "$runtime/file-plate.log" >&2
        exit 1
    }
    # Stable compositor pointer outside the screenshot crop; all icon
    # differences must come from actual file/surface changes.
    WAYLAND_DISPLAY=wayland-0 "$clicker" --move-only 1100 450 1366 768
    sleep 0.2
    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xdg-before.png"
    # A file created by a different process must trigger calloop/inotify
    # without a fake reload, polling request or direct State mutation.
    printf "%s\n" "Externally created from test shell" \
        > "$runtime/file-home/Desktop/03-new.txt"
    sleep 0.7
    kill -0 "$plate"
    grep -Fq "RicePlate: XDG inventory refreshed entries=4" "$runtime/file-plate.log" || {
        echo "Native XDG Desktop did not react to external create/inotify" >&2
        tail -n 35 "$runtime/file-plate.log" >&2
        exit 1
    }
    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xdg-created.png"
    /usr/bin/python3 - "$runtime/xdg-before.png" "$runtime/xdg-created.png" <<"PY"
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as first, Image.open(sys.argv[2]) as next_frame:
    assert first.size == next_frame.size == (1366, 768)
    roi = (0, 0, 900, 700)
    diff = ImageChops.difference(first.convert("RGB").crop(roi),
                                 next_frame.convert("RGB").crop(roi))
    changed = sum(any(c > 20 for c in px) for px in diff.getdata())
    print("Native XDG file creation framebuffer changed pixels:", changed, flush=True)
    assert changed > 60, "External XDG file creation produced no compositor-visible icon"
PY
    # The initial regular file occupies a logged position. Do not hardcode a
    # fake click or bypass compositor hit-testing for the file-open action.
    position=$(sed -n "s/.*XDG mapped x=\([0-9][0-9]*\) y=\([0-9][0-9]*\) kind=File.*/\1 \2/p" \
        "$runtime/file-plate.log" | head -n 1)
    test -n "$position" || { echo "No real regular file position" >&2; exit 1; }
    set -- $position
    cx=$(($1 + 52))
    cy=$(($2 + 45))
    test ! -e "$runtime/full-gio.log"
    WAYLAND_DISPLAY=wayland-0 "$clicker" "$cx" "$cy" 1366 768
    sleep 0.1
    test ! -e "$runtime/full-gio.log" || {
        echo "Native file single click unexpectedly launched an application" >&2
        exit 1
    }
    WAYLAND_DISPLAY=wayland-0 "$clicker" "$cx" "$cy" 1366 768
    count=0
    while [ ! -s "$runtime/full-gio.log" ] && [ "$count" -lt 25 ]; do
        count=$((count + 1))
        sleep 0.1
    done
    expected_gio=$(printf "open\n%s" "$runtime/file-home/Desktop/00-note.txt")
    test "$(cat "$runtime/full-gio.log" 2>/dev/null || :)" = "$expected_gio" || {
        echo "Real XDG double-click did not open the original regular file" >&2
        exit 1
    }
    rm -f "$runtime/full-gio.log"
    # Focus request must be confirmed by a genuine wl_keyboard.enter. One
    # ephemeral wtype client drives Type-to-Select and Enter, not state APIs.
    WAYLAND_DISPLAY=wayland-0 "$clicker" "$cx" "$cy" 1366 768
    sleep 0.25
    WAYLAND_DISPLAY=wayland-0 wtype -d 85 -k F13 0 -k Return
    count=0
    while [ ! -s "$runtime/full-gio.log" ] && [ "$count" -lt 25 ]; do
        count=$((count + 1))
        sleep 0.1
    done
    grep -Fq "RicePlate: compositor confirmed XDG file keyboard focus" \
        "$runtime/file-plate.log" || {
        echo "Native XDG file focus not confirmed by real compositor keyboard enter" >&2
        tail -n 50 "$runtime/file-plate.log" >&2
        exit 1
    }
    grep -Fq "RicePlate: XDG file keyboard focus released" \
        "$runtime/file-plate.log" || {
        echo "Native XDG temporary keyboard focus never released" >&2
        exit 1
    }
    test "$(cat "$runtime/full-gio.log" 2>/dev/null || :)" = "$expected_gio" || {
        echo "Native XDG Type-to-Select and real Enter did not open selected file" >&2
        exit 1
    }
    rm -f "$runtime/full-gio.log"
    # A visible desktop launcher / symlink must NOT become executable through
    # the shared double-click path. Their hitboxes come from actual placement.
    for unsafe_kind in DesktopFile Symlink; do
        unsafe_position=$(sed -n "s/.*XDG mapped x=\([0-9][0-9]*\) y=\([0-9][0-9]*\) kind=$unsafe_kind.*/\1 \2/p" \
            "$runtime/file-plate.log" | head -n 1)
        test -n "$unsafe_position" || {
            echo "Missing mapped unsafe XDG file kind $unsafe_kind" >&2
            exit 1
        }
        set -- $unsafe_position
        unsafe_x=$(($1 + 52))
        unsafe_y=$(($2 + 45))
        WAYLAND_DISPLAY=wayland-0 "$clicker" "$unsafe_x" "$unsafe_y" 1366 768
        WAYLAND_DISPLAY=wayland-0 "$clicker" "$unsafe_x" "$unsafe_y" 1366 768
        sleep 0.2
        test ! -e "$runtime/full-gio.log" || {
            echo "Unsafe XDG file $unsafe_kind invoked an opener" >&2
            exit 1
        }
        test ! -e "$runtime/full-ricefield.log" || {
            echo "Unsafe XDG file $unsafe_kind invoked RiceField" >&2
            exit 1
        }
    done
    # Rename and removal are external writes; the live watcher must notice
    # both, clean up the old surface, and preserve the existing panel.
    mv "$runtime/file-home/Desktop/00-note.txt" \
       "$runtime/file-home/Desktop/00-renamed.txt"
    sleep 0.65
    grep -Fq "RicePlate: XDG inventory refreshed entries=4" "$runtime/file-plate.log"
    rm "$runtime/file-home/Desktop/03-new.txt"
    sleep 0.65
    grep -Fq "RicePlate: XDG inventory refreshed entries=3" "$runtime/file-plate.log" || {
        echo "Native XDG Desktop did not refresh after external deletion" >&2
        exit 1
    }
    WAYLAND_DISPLAY=wayland-0 grim - > "$runtime/xdg-deleted.png"
    kill -0 "$plate"
    test ! -e "$runtime/full-gio.log"
    test ! -e "$runtime/full-ricefield.log"
    echo "Verified live XDG file layers, compositor double-click, external create/rename/delete and inert .desktop/symlink inventory"
    kill "$plate"
    wait "$plate" 2>/dev/null || :
    plate=
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

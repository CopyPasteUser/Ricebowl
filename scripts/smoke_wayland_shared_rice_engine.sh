#!/bin/sh
# CI-only: end-to-end shared Rice engine with one real native labwc session.
# It never uses the runner's user recipes or modifies XFCE/default login.
set -eu

source_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
native="$source_root/components/riceplate-wayland/target/release/riceplate-native"
test -x "$native" || { echo "Native RicePlate build missing" >&2; exit 1; }

if [ "$#" -eq 0 ]; then
    runtime=$(mktemp -d)
    chmod 0700 "$runtime"
    mkdir -m 0700 "$runtime/run" "$runtime/config" "$runtime/state"
    export XDG_RUNTIME_DIR="$runtime/run" XDG_CONFIG_HOME="$runtime/config"
    export XDG_STATE_HOME="$runtime/state" RICEBOWL_ENGINE_CI_RUNTIME="$runtime"
    export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
    export XDG_SESSION_TYPE=wayland
    export PATH="$source_root/components/riceplate-wayland/target/release:$PATH"
    trap 'rm -r -- "$runtime" 2>/dev/null || :' EXIT
    dbus-run-session -- sh "$0" --child
    exit $?
fi

runtime=$RICEBOWL_ENGINE_CI_RUNTIME
unset RICEBOWL_DE_READY_FD
# Make the real Luna recipe available as another distinct, validated private
# data-only layout. Importing it does not change the active login selection.
cp "$source_root/examples/wayland/xp-luna-columns.json" "$runtime/luna.json"
chmod 0600 "$runtime/luna.json"
luna=$(PYTHONPATH="$source_root" /usr/bin/python3 - "$runtime/luna.json" <<'PY'
import sys
from pathlib import Path
from macrice.de import recipes
recipe, _ = recipes.import_recipe(Path(sys.argv[1]))
print(recipe.recipe_id)
PY
)
test -n "$luna"

compositor=
cleanup() {
    if [ -n "$compositor" ]; then
        kill "$compositor" 2>/dev/null || :
        wait "$compositor" 2>/dev/null || :
    fi
}
trap cleanup EXIT
/usr/bin/python3 "$source_root/launcher.py" de start --nested --panel native \
    --recipe classic >"$runtime/session.log" 2>&1 &
compositor=$!
ready=0
count=0
while [ "$count" -lt 80 ]; do
    kill -0 "$compositor" 2>/dev/null || {
        echo "Shared native session died before socket startup" >&2
        tail -n 80 "$runtime/session.log" >&2
        exit 1
    }
    if [ -S "$XDG_RUNTIME_DIR/wayland-0" ] \
       && [ -S "$XDG_RUNTIME_DIR/ricebowl-live-wayland-0.sock" ]; then
        ready=1
        break
    fi
    count=$((count + 1))
    sleep 0.25
done
test "$ready" -eq 1 || {
    echo "Shared native session never exposed a real private Wayland/live socket" >&2
    tail -n 80 "$runtime/session.log" >&2
    exit 1
}
export WAYLAND_DISPLAY=wayland-0
/usr/bin/python3 "$source_root/launcher.py" de creator-live-status --json \
    >"$runtime/initial.json"
/usr/bin/python3 - "$runtime/initial.json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1]))
assert data["ok"] and data["active"] == "classic", data
assert data["panel"] == "native" and not data["next_login_persisted"], data
PY
grim "$runtime/classic.png"

review_hash() {
    PYTHONPATH="$source_root" /usr/bin/python3 - "$1" <<'PY'
from macrice.de import staging
import sys
print(staging._hash(sys.argv[1]))
PY
}
apply_rice() {
    previous=$1
    candidate=$2
    digest=$(review_hash "$candidate")
    /usr/bin/python3 "$source_root/launcher.py" de creator-live-apply \
        --recipe "$candidate" --expect-sha256 "$digest" \
        --expect-active "$previous" --json >"$runtime/apply-$candidate.json"
    /usr/bin/python3 - "$runtime/apply-$candidate.json" "$candidate" "$previous" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1]))
assert data["ok"] and data["changed"], data
assert data["active"] == sys.argv[2], data
assert data["previous"] == sys.argv[3], data
assert data["panel"] == "native" and not data["next_login_persisted"], data
PY
    # Supervisor already received the real compositor frame acknowledgement,
    # not merely a successful process poll.
    kill -0 "$compositor"
    grim "$runtime/$candidate.png"
}
apply_rice classic chrome
apply_rice chrome "$luna"

# Malformed/unreviewed changes must never kill or replace the live shell.
if /usr/bin/python3 "$source_root/launcher.py" de creator-live-apply \
    --recipe classic --expect-sha256 "$(printf %064d 0)" \
    --expect-active "$luna" --json >"$runtime/refused.json" 2>&1; then
    echo "Native shared Rice engine accepted an unreviewed target" >&2
    exit 1
fi
/usr/bin/python3 "$source_root/launcher.py" de creator-live-status --json \
    >"$runtime/after-reject.json"
/usr/bin/python3 - "$runtime/after-reject.json" "$luna" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1]))
assert data["ok"] and data["active"] == sys.argv[2], data
PY

/usr/bin/python3 "$source_root/launcher.py" de creator-live-restore \
    --expect-active "$luna" --json >"$runtime/restore.json"
/usr/bin/python3 - "$runtime/restore.json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1]))
assert data["ok"] and data["changed"], data
assert data["active"] == "chrome" and data["previous"] != "chrome", data
assert data["panel"] == "native" and not data["next_login_persisted"], data
PY
grim "$runtime/restored-chrome.png"

# Compare actual compositor framebuffers, not standalone mockups. Each rice
# shares the same runtime services but composes a different native layout.
mkdir -p "$source_root/dist/riceplate-native-preview/shared-engine"
/usr/bin/python3 - "$runtime/classic.png" "$runtime/chrome.png" "$runtime/$luna.png" \
    "$runtime/restored-chrome.png" <<'PY'
from PIL import Image, ImageChops
import sys
images = [Image.open(path).convert("RGB") for path in sys.argv[1:]]
try:
    assert len({item.size for item in images}) == 1, "Output changed between rice frames"
    w, h = images[0].size
    assert w >= 800 and h >= 600, (w, h)
    strips = [im.crop((0, h - 96, w, h)) for im in images]
    def changed(a, b):
        return sum(max(px) > 20 for px in ImageChops.difference(a, b).getdata())
    classic_chrome = changed(strips[0], strips[1])
    chrome_luna = changed(strips[1], strips[2])
    assert classic_chrome > 100, f"Classic and Chrome panels did not differ: {classic_chrome}"
    assert chrome_luna > 100, f"Chrome and Luna panels did not differ: {chrome_luna}"
    assert changed(strips[1], strips[3]) < 6000, "Restore changed the prior rice panel"
    print("Real labwc native Rice engine: distinct layouts, compositor-ready apply and restore",
          classic_chrome, chrome_luna)
finally:
    for image in images:
        image.close()
PY
for name in classic chrome "$luna" restored-chrome; do
    cp "$runtime/$name.png" "$source_root/dist/riceplate-native-preview/shared-engine/$name.png"
done
# SG4: real compositor-driven compact/laptop/desktop + fractional scale
# matrix, two structurally different native rices (Chrome and XP Luna).
# Every capture follows an actual labwc wl_output mode/scale change and
# native compositor-frame-acknowledged Creator live apply/restore. No mocked
# image, display-config persistence, XFCE or greeter mutation.
output=$(wlr-randr | sed -n "1s/[[:space:]].*//p")
test -n "$output" || { echo "No real labwc output for Creator matrix" >&2; exit 1; }
size_artifacts="$source_root/dist/riceplate-native-preview/creator-output-matrix"
mkdir -p "$size_artifacts"
capture_matrix() {
    rice=$1
    target_width=$2
    target_height=$3
    name=$4
    target="$runtime/matrix-$name-$rice.png"
    attempt=0
    while [ "$attempt" -lt 16 ]; do
        grim -o "$output" "$target"
        if /usr/bin/python3 - "$target" "$target_width" "$target_height" <<'PY'
from PIL import Image
from pathlib import Path
import sys
path, width, height = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
try:
    with Image.open(path) as image:
        assert image.format == "PNG" and image.size == (width, height)
        image.verify()
    with Image.open(path) as image:
        image.load()
        sample = image.convert("RGB")
        # A real native panel must cause bottom-area pixels to differ from
        # background and must remain inside the compositor output geometry.
        x = width // 2
        center = sample.getpixel((x, height // 2))
        bar = sample.getpixel((x, height - 10))
        assert max(abs(a - b) for a, b in zip(center, bar)) > 8
except (OSError, AssertionError, ValueError):
    sys.exit(1)
PY
        then
            cp "$target" "$size_artifacts/$name-$rice.png"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 0.25
    done
    echo "Native Creator $rice output was not visible at $name" >&2
    exit 1
}
for spec in 'compact 1024 768 1' 'laptop 1366 768 1.25' 'desktop 1600 900 1'; do
    set -- $spec
    name=$1
    width=$2
    height=$3
    scale=$4
    wlr-randr --output "$output" --custom-mode "${width}x${height}@60Hz" --scale "$scale"
    capture_matrix chrome "$width" "$height" "$name"
    apply_rice chrome "$luna"
    capture_matrix "$luna" "$width" "$height" "$name"
    /usr/bin/python3 "$source_root/launcher.py" de creator-live-restore \
        --expect-active "$luna" --json >"$runtime/matrix-restore-$name.json"
    /usr/bin/python3 - "$runtime/matrix-restore-$name.json" <<'PY'
import json
import sys
reply = json.load(open(sys.argv[1]))
assert reply["ok"] and reply["active"] == "chrome"
assert reply["panel"] == "native" and not reply["next_login_persisted"]
PY
    # The compositor can acknowledge the Creator transaction before the
    # scaled wl_output's next fully repainted layer frame is captured. Keep
    # the *same* strict pixel threshold; retry only real grim frames for a
    # bounded period instead of accepting the previous Luna surface.
    attempt=0
    restored_ready=0
    while [ "$attempt" -lt 24 ]; do
        grim -o "$output" "$runtime/matrix-restored-$name.png"
        if /usr/bin/python3 - "$size_artifacts/$name-chrome.png" \
                "$runtime/matrix-restored-$name.png" "$width" "$height" <<'PY'
from PIL import Image, ImageChops
import sys
try:
    with Image.open(sys.argv[1]) as chrome, Image.open(sys.argv[2]) as restored:
        a, c = chrome.convert("RGB"), restored.convert("RGB")
        assert a.size == c.size == (int(sys.argv[3]), int(sys.argv[4]))
        width, height = a.size
        strip = (0, height - 96, width, height)
        diff = ImageChops.difference(a.crop(strip), c.crop(strip))
        changed = sum(max(pixel) > 20 for pixel in diff.getdata())
        assert changed < 6000
except (OSError, ValueError, AssertionError):
    sys.exit(1)
PY
        then
            restored_ready=1
            break
        fi
        attempt=$((attempt + 1))
        sleep 0.25
    done
    if [ "$restored_ready" -ne 1 ]; then
        # Do not hide a persistent compositor mismatch. Preserve the real
        # frames and log exactly which panel was actually rendered.
        cp "$runtime/matrix-restored-$name.png" "$size_artifacts/$name-restore-mismatch.png"
        /usr/bin/python3 - "$size_artifacts/$name-chrome.png" \
                "$size_artifacts/$name-$luna.png" \
                "$size_artifacts/$name-restore-mismatch.png" <<'PY'
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as a0, Image.open(sys.argv[2]) as b0, \
     Image.open(sys.argv[3]) as c0:
    a, b, c = (im.convert("RGB") for im in (a0, b0, c0))
    def changed(x, y, part):
        w, h = x.size
        x0, x1 = (0, w) if part == "full" else (0, w // 2) if part == "left" else (w // 2, w)
        region = (x0, h - 96, x1, h)
        diff = ImageChops.difference(x.crop(region), y.crop(region))
        return sum(max(pixel) > 20 for pixel in diff.getdata())
    print(f"Creator diagnostic: sizes chrome={a.size} luna={b.size} restored={c.size}", flush=True)
    if a.size == b.size == c.size:
        for part in ("full", "left", "right"):
            print(f"Creator diagnostic: {part} chrome/luna={changed(a,b,part)} "
                  f"chrome/restored={changed(a,c,part)} "
                  f"luna/restored={changed(b,c,part)}", flush=True)
PY
        wlr-randr >&2
        echo "Creator restore did not converge to previous Chrome pixels at $name" >&2
        exit 1
    fi
    /usr/bin/python3 - "$size_artifacts/$name-chrome.png" \
            "$size_artifacts/$name-$luna.png" "$runtime/matrix-restored-$name.png" <<'PY'
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as chrome, Image.open(sys.argv[2]) as luna, \
     Image.open(sys.argv[3]) as restored:
    a, b, c = (img.convert("RGB") for img in (chrome, luna, restored))
    assert a.size == b.size == c.size
    w, h = a.size
    def changed(x, y):
        diff = ImageChops.difference(x.crop((0, h - 96, w, h)),
                                     y.crop((0, h - 96, w, h)))
        return sum(max(pixel) > 20 for pixel in diff.getdata())
    assert changed(a, b) > 100, "Chrome and Luna were not distinct at this scale"
    assert changed(a, c) < 6000, "Creator restore changed the previous rice"
PY
    echo "Real Creator output matrix $name: $width x $height scale $scale validated"
done
# Restore compact output without touching user monitor preferences.
wlr-randr --output "$output" --custom-mode 1024x768@60Hz --scale 1

# Nested preview must never update a real saved selection.
PYTHONPATH="$source_root" /usr/bin/python3 - <<'PY'
from macrice.de import recipes
assert recipes.current_selection() == ("classic", None)
PY
echo "Verified composited Classic → Chrome → XP Luna → Chrome live apply/restore without host mutation"

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
    mkdir -m 0700 "$runtime/run" "$runtime/config" "$runtime/state" "$runtime/mock-bin"
    # CI-only fixed-action witness: the REAL compositor pointer must reach
    # the Chrome launcher and dispatch its allowlisted fuzzel fallback.
    # Never launch an external application or modify the host's user config.
    cat > "$runtime/mock-bin/fuzzel" <<'SH'
#!/bin/sh
test -n "${RICEBOWL_ENGINE_CI_RUNTIME:-}" || exit 2
printf '%s\n' "fuzzel" >> "$RICEBOWL_ENGINE_CI_RUNTIME/launcher-actions.log"
SH
    chmod 0700 "$runtime/mock-bin/fuzzel"
    export XDG_RUNTIME_DIR="$runtime/run" XDG_CONFIG_HOME="$runtime/config"
    export XDG_STATE_HOME="$runtime/state" RICEBOWL_ENGINE_CI_RUNTIME="$runtime"
    export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
    export XDG_SESSION_TYPE=wayland
    export PATH="$runtime/mock-bin:$source_root/components/riceplate-wayland/target/release:$PATH"
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
keyboard_keeper=
cleanup() {
    # Keep the disposable virtual keyboard alive throughout the native
    # pointer/keyboard handoff; always tear it down with this exact session.
    if [ -n "$keyboard_keeper" ]; then
        kill "$keyboard_keeper" 2>/dev/null || :
        wait "$keyboard_keeper" 2>/dev/null || :
    fi
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
# A real desktop keeps its keyboard attached. A one-shot wtype invocation
# otherwise drops wl_seat keyboard capability between events and can hide a
# real menu focus regression behind a compositor/device reconnect race.
# F13 has no associated rice action; this keyboard never leaves private labwc.
wtype -k F13 -s 1800000 -k F13 >"$runtime/keyboard-keeper.log" 2>&1 &
keyboard_keeper=$!
sleep 0.3
kill -0 "$keyboard_keeper" 2>/dev/null || {
    echo "Private Wayland keyboard failed to attach" >&2
    cat "$runtime/keyboard-keeper.log" >&2
    exit 1
}
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
# SG1/SG4: exercise actual labwc pointer delivery across structurally
# different rices, not only Python transaction replies or painted pixels.
clicker="$source_root/components/riceplate-wayland/target/release/examples/wayland_pointer_click"
test -x "$clicker" || { echo "Missing real Wayland virtual-pointer helper" >&2; exit 1; }
geometry=$(/usr/bin/python3 - "$runtime/chrome.png" <<'PY'
from PIL import Image
import sys
with Image.open(sys.argv[1]) as frame:
    frame.verify()
with Image.open(sys.argv[1]) as frame:
    print(*frame.size)
PY
)
set -- $geometry
width=$1
height=$2
test "$width" -ge 800 && test "$height" -ge 600 || exit 1
# Chrome's v1 bottom shelf uses a real left launcher with the fixed
# external fuzzel action. The private executable only logs the argv target.
"$clicker" 35 "$((height - 22))" "$width" "$height"
attempt=0
while [ ! -s "$runtime/launcher-actions.log" ] && [ "$attempt" -lt 30 ]; do
    attempt=$((attempt + 1))
    sleep 0.1
done
test "$(cat "$runtime/launcher-actions.log" 2>/dev/null || :)" = fuzzel || {
    echo "Chrome launcher pointer did not dispatch the allowlisted action" >&2
    exit 1
}
apply_rice chrome "$luna"
grim "$runtime/luna-before-real-pointer.png"
# Luna's separate two-column menu must open as a NATIVE surface, with
# genuine compositor-delivered events. It must NOT run Chrome's fallback.
"$clicker" 35 "$((height - 20))" "$width" "$height"
attempt=0
changed=0
while [ "$attempt" -lt 20 ]; do
    sleep 0.15
    grim "$runtime/luna-after-real-pointer.png"
    if /usr/bin/python3 - "$runtime/luna-before-real-pointer.png" \
          "$runtime/luna-after-real-pointer.png" <<'PY'
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as before, Image.open(sys.argv[2]) as after:
    a, b = before.convert("RGB"), after.convert("RGB")
    assert a.size == b.size
    w, h = a.size
    region = (0, max(0, h - 550), min(w, 640), h)
    diff = ImageChops.difference(a.crop(region), b.crop(region))
    changed = sum(max(pixel) > 20 for pixel in diff.getdata())
    assert changed > 2000, f"Luna menu did not paint: only {changed} pixels"
PY
    then
        changed=1
        break
    fi
    attempt=$((attempt + 1))
done
test "$changed" -eq 1 || {
    echo "Luna native menu did not open from a real Wayland pointer" >&2
    exit 1
}
test "$(cat "$runtime/launcher-actions.log")" = fuzzel || {
    echo "Luna dispatched Chrome's external launcher instead of native menu" >&2
    exit 1
}
# SG1: move the selected native Luna item using a genuine Wayland keyboard
# event routed by the SAME compositor that delivered the opening pointer.
# A synthetic MenuState unit test or a standalone preview cannot prove this.
wtype -k Down
sleep 0.2
grim "$runtime/luna-after-real-keyboard-down.png"
/usr/bin/python3 - "$runtime/luna-after-real-pointer.png" \
        "$runtime/luna-after-real-keyboard-down.png" <<'PY'
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as opened, Image.open(sys.argv[2]) as navigated:
    a, b = opened.convert("RGB"), navigated.convert("RGB")
    assert a.size == b.size
    w, h = a.size
    region = (0, max(0, h - 550), min(w, 640), h)
    changed = sum(max(px) > 20 for px in
                  ImageChops.difference(a.crop(region), b.crop(region)).getdata())
    assert changed > 80, f"Wayland Down key did not repaint Luna selection: {changed}"
PY
# Escape must dismiss the very same menu through its keyboard lease, and
# release focus rather than keeping the next rice trapped in Luna.
wtype -k Escape
attempt=0
keyboard_closed=0
while [ "$attempt" -lt 20 ]; do
    sleep 0.15
    grim "$runtime/luna-after-real-keyboard-escape.png"
    if /usr/bin/python3 - "$runtime/luna-before-real-pointer.png" \
            "$runtime/luna-after-real-keyboard-escape.png" <<'PY'
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as before, Image.open(sys.argv[2]) as after:
    a, b = before.convert("RGB"), after.convert("RGB")
    assert a.size == b.size
    w, h = a.size
    region = (0, max(0, h - 550), min(w, 640), h)
    changed = sum(max(px) > 20 for px in
                  ImageChops.difference(a.crop(region), b.crop(region)).getdata())
    assert changed < 1200, f"Luna Escape left menu visible: {changed} pixels"
PY
    then
        keyboard_closed=1
        break
    fi
    attempt=$((attempt + 1))
done
test "$keyboard_closed" -eq 1 || {
    echo "Luna did not release its real keyboard/menu focus after Escape" >&2
    exit 1
}
test "$(cat "$runtime/launcher-actions.log")" = fuzzel || {
    echo "Luna keyboard navigation dispatched the Chrome launcher" >&2
    exit 1
}
# Reopen and close again with real pointer input: keyboard dismissal must
# not strand the menu's input region or active Wayland surface.
"$clicker" 35 "$((height - 20))" "$width" "$height"
sleep 0.25
grim "$runtime/luna-reopened-after-keyboard.png"
/usr/bin/python3 - "$runtime/luna-before-real-pointer.png" \
        "$runtime/luna-reopened-after-keyboard.png" <<'PY'
from PIL import Image, ImageChops
import sys
with Image.open(sys.argv[1]) as before, Image.open(sys.argv[2]) as after:
    a, b = before.convert("RGB"), after.convert("RGB")
    assert a.size == b.size
    w, h = a.size
    region = (0, max(0, h - 550), min(w, 640), h)
    changed = sum(max(px) > 20 for px in
                  ImageChops.difference(a.crop(region), b.crop(region)).getdata())
    assert changed > 2000, f"Luna did not reopen after keyboard Escape: {changed}"
PY
"$clicker" 35 "$((height - 20))" "$width" "$height"
sleep 0.2

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
# After frame-acknowledged restore, the SAME launcher location must once
# again dispatch Chrome's allowlisted action. No stale Luna menu handler.
"$clicker" 35 "$((height - 22))" "$width" "$height"
attempt=0
while [ "$(wc -l < "$runtime/launcher-actions.log")" -lt 2 ] && [ "$attempt" -lt 30 ]; do
    attempt=$((attempt + 1))
    sleep 0.1
done
test "$(wc -l < "$runtime/launcher-actions.log")" -eq 2 || {
    echo "Restored Chrome launcher failed or dispatched twice" >&2
    exit 1
}
test "$(sed -n '2p' "$runtime/launcher-actions.log")" = fuzzel
# SG1: neutral Chrome shelf space provides an explicit pointer-initiated
# keyboard-focus gesture. Labwc does NOT guarantee focus merely because a
# Bottom/OnDemand panel's launcher was clicked; that click also starts an app.
# Keep the same persistent keyboard seat and require the bounded, fresh
# overlay's real compositor wl_keyboard.enter before dispatch.
"$clicker" "$((width / 2))" "$((height - 22))" "$width" "$height"
sleep 0.3
test "$(wc -l < "$runtime/launcher-actions.log")" -eq 2 || {
    echo "Neutral Chrome focus click unexpectedly dispatched an action" >&2
    exit 1
}
# Escape must revoke the first grant, not leave a permanent keyboard grab.
wtype -k Escape
wtype -k Tab
wtype -k Return
sleep 0.25
test "$(wc -l < "$runtime/launcher-actions.log")" -eq 2 || {
    echo "Cancelled Chrome focus lease unexpectedly activated the launcher" >&2
    exit 1
}
# A NEW genuine neutral click is needed before Tab and Return may activate.
"$clicker" "$((width / 2))" "$((height - 22))" "$width" "$height"
sleep 0.3
wtype -k Tab
wtype -k Return
attempt=0
while [ "$(wc -l < "$runtime/launcher-actions.log")" -lt 3 ] && [ "$attempt" -lt 30 ]; do
    attempt=$((attempt + 1))
    sleep 0.1
done
test "$(wc -l < "$runtime/launcher-actions.log")" -eq 3 || {
    echo "Restored Chrome keyboard launcher failed or dispatched twice" >&2
    exit 1
}
test "$(sed -n '3p' "$runtime/launcher-actions.log")" = fuzzel || {
    echo "Chrome keyboard activation routed to a stale Luna action" >&2
    exit 1
}
# The keyboard invocation must not leave an input grab or stale popup:
# immediately prove the restored Chrome pointer still dispatches exactly
# one more action through the same compositor/seat.
"$clicker" 35 "$((height - 22))" "$width" "$height"
attempt=0
while [ "$(wc -l < "$runtime/launcher-actions.log")" -lt 4 ] && [ "$attempt" -lt 30 ]; do
    attempt=$((attempt + 1))
    sleep 0.1
done
test "$(wc -l < "$runtime/launcher-actions.log")" -eq 4 || {
    echo "Restored Chrome pointer lost input after keyboard dispatch" >&2
    exit 1
}
test "$(sed -n '4p' "$runtime/launcher-actions.log")" = fuzzel
kill -0 "$compositor"

# Compare actual compositor framebuffers, not standalone mockups. Each rice
# shares the same runtime services but composes a different native layout.
mkdir -p "$source_root/dist/riceplate-native-preview/shared-engine"
cp "$runtime/luna-before-real-pointer.png" \
   "$source_root/dist/riceplate-native-preview/shared-engine/luna-before-pointer.png"
cp "$runtime/luna-after-real-pointer.png" \
   "$source_root/dist/riceplate-native-preview/shared-engine/luna-opened-pointer.png"
cp "$runtime/luna-after-real-keyboard-down.png" \
   "$source_root/dist/riceplate-native-preview/shared-engine/luna-keyboard-down.png"
cp "$runtime/luna-after-real-keyboard-escape.png" \
   "$source_root/dist/riceplate-native-preview/shared-engine/luna-keyboard-escape.png"
cp "$runtime/luna-reopened-after-keyboard.png" \
   "$source_root/dist/riceplate-native-preview/shared-engine/luna-reopened.png"
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
# SG7: real, owner-private native memory/FD/thread comparison, not a
# cold-login or cumulative leak benchmark. The supervisor replaces RicePlate
# on an applied rice change (the compositor/session stays alive), so same-PID
# comparison across switches would be an invalid assumption. Require exactly
# ONE native process in this private runtime after EVERY transition and
# compare the final Chrome process footprint to the Chrome baseline.
# Never sample other users' sessions.
resource_probe="$source_root/scripts/ci_wayland_resource_smoke.py"
resource_baseline="$runtime/native-resource-baseline.json"
sleep 0.3
/usr/bin/python3 "$resource_probe" capture \
    --binary "$native" --runtime "$XDG_RUNTIME_DIR" --baseline "$resource_baseline"
# apply_rice writes snapshots to the same canonical names used by the
# downstream visual/geometry matrix. Preserve its original screenshot
# evidence while stress-testing process replacement.
cp "$runtime/classic.png" "$runtime/sg7-preserved-classic.png"
cp "$runtime/chrome.png" "$runtime/sg7-preserved-chrome.png"
for cycle in 1 2 3; do
    apply_rice chrome classic
    # Receipt alone would miss an orphaned former panel. Require its actual
    # /proc PID+start identity to disappear after compositor-acknowledged apply.
    /usr/bin/python3 "$resource_probe" assert-gone \
        --binary "$native" --runtime "$XDG_RUNTIME_DIR" \
        --baseline "$resource_baseline" >/dev/null
    /usr/bin/python3 "$resource_probe" capture \
        --binary "$native" --runtime "$XDG_RUNTIME_DIR" \
        --baseline "$runtime/native-resource-intermediate.json" >/dev/null
    apply_rice classic chrome
    /usr/bin/python3 "$resource_probe" assert-gone \
        --binary "$native" --runtime "$XDG_RUNTIME_DIR" \
        --baseline "$runtime/native-resource-intermediate.json" >/dev/null
    /usr/bin/python3 "$resource_probe" capture \
        --binary "$native" --runtime "$XDG_RUNTIME_DIR" \
        --baseline "$runtime/native-resource-intermediate.json" >/dev/null
    # A final-only comparison would miss a transient per-process footprint
    # regression that recovers before cycle three. Check every Chrome return
    # against the same settled Chrome baseline, after the supervisor's
    # compositor-acknowledged process replacement.
    sleep 0.3
    growth="$source_root/dist/riceplate-native-preview/shared-engine/resource-growth-cycle-$cycle.json"
    /usr/bin/python3 "$resource_probe" compare-replaced \
        --binary "$native" --runtime "$XDG_RUNTIME_DIR" --baseline "$resource_baseline" \
        >"$growth"
    test -s "$growth"
    # Measure /proc utime+stime with the same verified executable/runtime
    # identity before/after a bounded settled interval. These are observed
    # CI CPU samples, NOT a physical idle-power or long-duration leak claim.
    /usr/bin/python3 "$resource_probe" cpu-sample \
        --binary "$native" --runtime "$XDG_RUNTIME_DIR" \
        --baseline "$resource_baseline" \
        >"$source_root/dist/riceplate-native-preview/shared-engine/resource-cpu-cycle-$cycle.json"
done
# Keep the established artifact path for downstream consumers, and preserve
# all three cycle-specific comparisons for independent CI review.
cp "$growth" "$source_root/dist/riceplate-native-preview/shared-engine/resource-growth.json"
cp "$runtime/sg7-preserved-classic.png" "$runtime/classic.png"
cp "$runtime/sg7-preserved-chrome.png" "$runtime/chrome.png"
echo "Verified 3 real labwc cycles: prior-panel teardown, CPU ticks and bounded PSS/RSS, FDs, threads"
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
        # Compare the panel, not the wallpaper behind its upper edge.
        # The restored compositor may crop the same wallpaper differently
        # at fractional scales even when every panel pixel is identical.
        strip = (0, height - 40, width, height)
        diff = ImageChops.difference(a.crop(strip), c.crop(strip))
        changed = sum(max(pixel) > 20 for pixel in diff.getdata())
        assert changed < 2000
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
        # Bottom 40 physical rows belong to both native taskbars at all
        # tested output scales; the older 96-row strip includes wallpaper.
        diff = ImageChops.difference(x.crop((0, h - 40, w, h)),
                                     y.crop((0, h - 40, w, h)))
        return sum(max(pixel) > 20 for pixel in diff.getdata())
    assert changed(a, b) > 100, "Chrome and Luna were not distinct at this scale"
    assert changed(a, c) < 2000, "Creator restore changed the previous rice"
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

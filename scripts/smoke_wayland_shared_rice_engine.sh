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
# Nested preview must never update a real saved selection.
PYTHONPATH="$source_root" /usr/bin/python3 - <<'PY'
from macrice.de import recipes
assert recipes.current_selection() == ("classic", None)
PY
echo "Verified composited Classic → Chrome → XP Luna → Chrome live apply/restore without host mutation"

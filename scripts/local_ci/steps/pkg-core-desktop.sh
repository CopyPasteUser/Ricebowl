#!/bin/bash
# local-ci step: pkg-core-desktop
# Mirrors: riceplate-native.yml / native-layer-shell / Package complete standalone Wayland app and aggregate desktop
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
artifact="$PWD/dist/riceplate-native-preview"
core="$artifact/ricebowl-wayland-core_0.1.0~preview2_all.deb"
bundle="$artifact/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb"
bash scripts/build_wayland_core_deb.sh "$core"
bash scripts/build_wayland_core_deb.sh "$RUNNER_TEMP/ricebowl-core-rebuild.deb"
cmp "$core" "$RUNNER_TEMP/ricebowl-core-rebuild.deb"
sh scripts/build_wayland_desktop_deb.sh "$bundle"
sh scripts/build_wayland_desktop_deb.sh "$RUNNER_TEMP/ricebowl-desktop-rebuild.deb"
cmp "$bundle" "$RUNNER_TEMP/ricebowl-desktop-rebuild.deb"
isolated="$RUNNER_TEMP/ricebowl-standalone-root"
mkdir -p "$isolated"
dpkg-deb -x "$core" "$isolated"
dpkg-deb -x "$bundle" "$isolated"
test -f "$isolated/usr/lib/ricebowl-wayland/macrice/de/session.py"
test -f "$isolated/usr/lib/ricebowl-wayland/macrice/de/acceptance.py"
test -f "$isolated/usr/lib/ricebowl-wayland/macrice/creator_gui.py"
test -x "$isolated/usr/bin/ricebowl-wayland-app"
test -x "$isolated/usr/lib/ricebowl-wayland/bin/ricebowl"
/usr/bin/python3 -B "$isolated/usr/lib/ricebowl-wayland/launcher.py" de --help
(cd "$artifact" && sha256sum "$(basename "$core")" "$(basename "$bundle")" >> SHA256SUMS && sha256sum -c SHA256SUMS)

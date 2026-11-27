#!/bin/bash
# local-ci step: pkg-session-deb
# Mirrors: riceplate-native.yml / native-layer-shell / Validate native login and both reproducible preview packages together
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
artifact="$PWD/dist/riceplate-native-preview"
session="$artifact/ricebowl-wayland-session_0.1.0~preview3_all.deb"
sh scripts/build_wayland_session_deb.sh "$session"
sh scripts/build_wayland_session_deb.sh "$RUNNER_TEMP/ricebowl-session-rebuilt.deb"
cmp "$session" "$RUNNER_TEMP/ricebowl-session-rebuilt.deb"
test "$(dpkg-deb --field "$session" Version)" = '0.1.0~preview3'
private_root="$RUNNER_TEMP/ricebowl-wayland-login-pair"
mkdir -p "$private_root"
dpkg-deb --extract "$session" "$private_root"
dpkg-deb --extract "$artifact/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb" "$private_root"
test -x "$private_root/usr/bin/riceplate-native"
test -x "$private_root/usr/bin/ricebowl-wayland-session"
grep -Fxq 'Exec=/usr/bin/ricebowl-wayland-session --native' \
  "$private_root/usr/share/wayland-sessions/ricebowl-native.desktop"
grep -Fxq 'TryExec=/usr/bin/riceplate-native' \
  "$private_root/usr/share/wayland-sessions/ricebowl-native.desktop"
grep -Fxq 'Exec=/usr/bin/ricebowl-wayland-session' \
  "$private_root/usr/share/wayland-sessions/ricebowl.desktop"
(cd "$artifact" && sha256sum "$(basename "$session")" >> SHA256SUMS && sha256sum -c SHA256SUMS)

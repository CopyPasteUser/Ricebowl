#!/bin/bash
# local-ci step: pkg-docker-install
# Mirrors: riceplate-native.yml / native-layer-shell / Install, reinstall and purge complete preview in disposable Ubuntu
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
sh -n scripts/smoke_wayland_packaged_login.sh
docker run --rm --pull=missing \
  --volume "$PWD/dist/riceplate-native-preview:/packages:ro" \
  --volume "$PWD/scripts/smoke_wayland_packaged_login.sh:/tests/packaged-login.sh:ro" \
  ubuntu:24.04 bash -ceu '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends \
      /packages/ricebowl-wayland-core_0.1.0~preview2_all.deb \
      /packages/ricebowl-wayland-session_0.1.0~preview3_all.deb \
      /packages/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb \
      /packages/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb
    dpkg-query -W ricebowl-wayland-desktop | grep -q "^ricebowl-wayland-desktop[[:space:]]"
    /usr/bin/ricebowl-wayland-app de --help >/dev/null
    test -x /usr/lib/ricebowl-wayland/bin/ricebowl
    test "$(PATH=/usr/lib/ricebowl-wayland/bin:$PATH command -v ricebowl)" = /usr/lib/ricebowl-wayland/bin/ricebowl
    test -e /usr/share/wayland-sessions/ricebowl.desktop
    test -e /usr/share/wayland-sessions/ricebowl-native.desktop
    test -x /usr/bin/riceplate-native
    apt-get install -y --no-install-recommends wayland-utils grim procps >/dev/null
    RICEBOWL_PACKAGED_CI=1 sh /tests/packaged-login.sh
    mkdir -p /root/.config/ricebowl
    printf "%s\n" user-state > /root/.config/ricebowl/upgrade-preservation-marker
    apt-get install -y --no-install-recommends --reinstall \
      /packages/ricebowl-wayland-core_0.1.0~preview2_all.deb \
      /packages/ricebowl-wayland-session_0.1.0~preview3_all.deb \
      /packages/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb \
      /packages/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb
    test "$(cat /root/.config/ricebowl/upgrade-preservation-marker)" = user-state
    /usr/bin/ricebowl-wayland-app de --help >/dev/null
    apt-get purge -y ricebowl-wayland-desktop ricebowl-wayland-core \
      ricebowl-wayland-session ricebowl-riceplate-native
    test ! -e /usr/bin/ricebowl-wayland-app
    test ! -e /usr/lib/ricebowl-wayland/launcher.py
    test ! -e /usr/share/wayland-sessions/ricebowl.desktop
    test ! -e /usr/share/wayland-sessions/ricebowl-native.desktop
    test ! -e /usr/bin/riceplate-native
    test "$(cat /root/.config/ricebowl/upgrade-preservation-marker)" = user-state
    echo "Clean install, reinstall and purge preserved user state"
  '

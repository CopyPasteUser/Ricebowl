#!/bin/bash
# local-ci step: pkg-verify-set
# Mirrors: riceplate-native.yml / native-layer-shell / Reject inconsistent or unsafe Wayland release packages
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
artifact="$PWD/dist/riceplate-native-preview"
bash scripts/verify_wayland_package_set.sh \
  "$artifact/ricebowl-wayland-core_0.1.0~preview2_all.deb" \
  "$artifact/ricebowl-wayland-session_0.1.0~preview3_all.deb" \
  "$artifact/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb" \
  "$artifact/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb"

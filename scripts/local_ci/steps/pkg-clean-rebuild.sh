#!/bin/bash
# local-ci step: pkg-clean-rebuild
# Mirrors: riceplate-native.yml / native-layer-shell / Rebuild all four packages from clean tracked source
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
bash -n scripts/verify_wayland_clean_rebuild.sh
/usr/bin/python3 -m unittest tests.test_wayland_clean_rebuild -v
artifact="$PWD/dist/riceplate-native-preview"
bash scripts/verify_wayland_clean_rebuild.sh \
  "$artifact/ricebowl-wayland-core_0.1.0~preview2_all.deb" \
  "$artifact/ricebowl-wayland-session_0.1.0~preview3_all.deb" \
  "$artifact/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb" \
  "$artifact/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb"

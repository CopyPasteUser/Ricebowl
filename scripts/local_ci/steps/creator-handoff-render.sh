#!/bin/bash
# local-ci step: creator-handoff-render
# Mirrors: riceplate-native.yml / native-layer-shell / Render installed Creator drafts in real isolated Wayland compositors
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
mkdir -p dist/riceplate-native-preview/creator-handoff
export PATH="$PWD/components/riceplate-wayland/target/release:$PATH"
timeout -k 5s 160s dbus-run-session -- /usr/bin/python3 \
  -m scripts.verify_wayland_creator_handoff \
  --output-dir "$PWD/dist/riceplate-native-preview/creator-handoff"

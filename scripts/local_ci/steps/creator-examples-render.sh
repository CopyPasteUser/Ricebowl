#!/bin/bash
# local-ci step: creator-examples-render
# Mirrors: riceplate-native.yml / native-layer-shell / Render both Creator demonstrators at four real output geometries
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
mkdir -p dist/riceplate-native-preview/creator-examples
export PATH="$PWD/components/riceplate-wayland/target/release:$PATH"
python3 -m scripts.verify_wayland_creator_examples \
  --output-dir "$PWD/dist/riceplate-native-preview/creator-examples"

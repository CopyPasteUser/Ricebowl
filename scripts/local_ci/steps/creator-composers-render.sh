#!/bin/bash
# local-ci step: creator-composers-render
# Mirrors: riceplate-native.yml / native-layer-shell / Render two distinct Composer rices through native labwc
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
/usr/bin/python3 -m unittest tests.test_de_creator_runtime_parity -v
mkdir -p dist/riceplate-native-preview/creator-composers
export PATH="$PWD/components/riceplate-wayland/target/release:$PATH"
timeout -k 5s 200s python3 -m scripts.verify_wayland_creator_examples \
  --composers --output-dir "$PWD/dist/riceplate-native-preview/creator-composers"

#!/bin/bash
# local-ci step: pkg-preview-artifact
# Mirrors: riceplate-native.yml / native-layer-shell / Prepare native preview artifact with build provenance
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
mkdir -p dist/riceplate-native-preview
install -m 0755 components/riceplate-wayland/target/release/riceplate-native \
  dist/riceplate-native-preview/riceplate-native
cp components/riceplate-wayland/Cargo.lock \
  dist/riceplate-native-preview/Cargo.lock
dist/riceplate-native-preview/riceplate-native --version
printf 'Git commit: %s\nToolchain: %s\nBuild host: Ubuntu 24.04 x86_64\nStatus: experimental native panel, not a full desktop release\n' \
  "$GITHUB_SHA" "$(rustc --version)" > dist/riceplate-native-preview/BUILDINFO.txt
(cd dist/riceplate-native-preview && sha256sum riceplate-native Cargo.lock > SHA256SUMS)

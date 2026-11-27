#!/bin/bash
# local-ci step: pkg-native-deb
# Mirrors: riceplate-native.yml / native-layer-shell / Build reproducible, removable native amd64 preview package
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
sh -n scripts/build_riceplate_native_deb.sh
binary="$PWD/components/riceplate-wayland/target/release/riceplate-native"
output="$PWD/dist/riceplate-native-preview/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb"
sh scripts/build_riceplate_native_deb.sh "$binary" "$output"
second="$RUNNER_TEMP/riceplate-reproducibility.deb"
sh scripts/build_riceplate_native_deb.sh "$binary" "$second"
cmp "$output" "$second"
test "$(dpkg-deb --field "$output" Architecture)" = amd64
test -n "$(dpkg-deb --field "$output" Depends)"
expected_digest=$(sha256sum "$binary")
expected_digest=${expected_digest%% *}
test "$(dpkg-deb --field "$output" X-RiceBowl-Native-SHA256)" = "$expected_digest"
mkdir -p "$RUNNER_TEMP/riceplate-package-check"
dpkg-deb --extract "$output" "$RUNNER_TEMP/riceplate-package-check"
cmp "$binary" "$RUNNER_TEMP/riceplate-package-check/usr/bin/riceplate-native"
(cd dist/riceplate-native-preview && sha256sum "$(basename "$output")" >> SHA256SUMS)
(cd dist/riceplate-native-preview && sha256sum -c SHA256SUMS)

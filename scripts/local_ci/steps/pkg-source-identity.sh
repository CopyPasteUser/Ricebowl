#!/bin/bash
# local-ci step: pkg-source-identity
# Mirrors: riceplate-native.yml / attest-native-preview / Verify downloaded package and committed-source identity
# Local adaptation: verifies the locally built package; the sigstore attestation step is not translated
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
directory=dist/riceplate-native-preview
package="$directory/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb"
test -f "$package"
(cd "$directory" && sha256sum -c SHA256SUMS)
test "$(dpkg-deb -f "$package" X-RiceBowl-Source-Commit)" = "$GITHUB_SHA"
declared=$(dpkg-deb -f "$package" X-RiceBowl-Native-SHA256)
actual=$(sha256sum "$directory/riceplate-native")
actual=${actual%% *}
test "$declared" = "$actual"
extracted=$(mktemp -d)
trap 'rm -rf -- "$extracted"' EXIT
dpkg-deb -x "$package" "$extracted"
cmp "$directory/riceplate-native" "$extracted/usr/bin/riceplate-native"

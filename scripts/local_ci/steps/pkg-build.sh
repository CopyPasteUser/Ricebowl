#!/bin/bash
# local-ci step: pkg-build
# Mirrors: sg6-cross-runner.yml / build / Independently compile, package and verify from exact committed source
# Local adaptation: matrix worker comes from --worker (host-a|host-b)
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -euo pipefail
WORKER="${LCI_WORKER:-host-a}"
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
test -z "$(git status --porcelain)"
export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct HEAD)"
export LC_ALL=C
/usr/bin/python3 -m unittest tests.test_sg6_cross_runner -v
cargo build --release --locked --manifest-path components/riceplate-wayland/Cargo.toml
target="$PWD/dist/sg6"
mkdir -p "$target"
bash scripts/build_wayland_core_deb.sh "$target/ricebowl-wayland-core_0.1.0~preview2_all.deb"
sh scripts/build_wayland_session_deb.sh "$target/ricebowl-wayland-session_0.1.0~preview3_all.deb"
sh scripts/build_riceplate_native_deb.sh \
  "$PWD/components/riceplate-wayland/target/release/riceplate-native" \
  "$target/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb"
sh scripts/build_wayland_desktop_deb.sh "$target/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb"
bash scripts/verify_wayland_package_set.sh \
  "$target/ricebowl-wayland-core_0.1.0~preview2_all.deb" \
  "$target/ricebowl-wayland-session_0.1.0~preview3_all.deb" \
  "$target/ricebowl-riceplate-native_0.1.0~preview2_amd64.deb" \
  "$target/ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb"
/usr/bin/python3 scripts/verify_sg6_cross_runner.py record \
  --directory "$target" --source-sha "$GITHUB_SHA" \
  --worker "$WORKER" --output "$target/receipt.json"

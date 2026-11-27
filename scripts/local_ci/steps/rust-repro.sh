#!/bin/bash
# local-ci step: rust-repro
# Mirrors: riceplate-native.yml / native-layer-shell / Verify same-source native ELF reproducibility from a fresh target
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
# A second clean target isolates Cargo's incremental/build outputs
# while retaining the same checked-out source and pinned toolchain.
# This checks same-run byte reproducibility, not cross-host releases.
target="$RUNNER_TEMP/riceplate-clean-rebuild"
CARGO_TARGET_DIR="$target" cargo build --offline --locked --release \
  --manifest-path components/riceplate-wayland/Cargo.toml
cmp components/riceplate-wayland/target/release/riceplate-native \
  "$target/release/riceplate-native"
sha256sum components/riceplate-wayland/target/release/riceplate-native \
  "$target/release/riceplate-native"

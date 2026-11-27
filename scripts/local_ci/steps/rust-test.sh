#!/bin/bash
# local-ci step: rust-test
# Mirrors: riceplate-native.yml / native-layer-shell / Build and test native RicePlate [cargo test]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
cargo test --locked --manifest-path components/riceplate-wayland/Cargo.toml

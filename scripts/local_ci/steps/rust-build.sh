#!/bin/bash
# local-ci step: rust-build
# Mirrors: riceplate-native.yml / native-layer-shell / Build and test native RicePlate [release build and examples]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
cargo build --locked --release --manifest-path components/riceplate-wayland/Cargo.toml
cargo build --locked --release --manifest-path components/riceplate-wayland/Cargo.toml \
  --example wayland_pointer_click
cargo build --locked --release --manifest-path components/riceplate-wayland/Cargo.toml \
  --example wayland_ime_v2_client

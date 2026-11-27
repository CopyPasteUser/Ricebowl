#!/bin/bash
# local-ci step: rust-clippy
# Mirrors: riceplate-native.yml / native-layer-shell / Build and test native RicePlate [cargo clippy]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
# Baseline contains legacy style warnings in other owner modules.
# Keep full lint output; fail the merge on correctness, suspicious
# code, perf regressions and ignored must-use results.
cargo clippy --locked --manifest-path components/riceplate-wayland/Cargo.toml --all-targets -- -D clippy::correctness -D clippy::suspicious -D clippy::perf -D unused_must_use

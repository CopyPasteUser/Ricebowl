#!/bin/bash
# local-ci step: rust-fmt
# Mirrors: (none) -- local-only addition; no hosted workflow runs rustfmt.
# The repository is rustfmt-clean today; this keeps it that way.
cargo fmt --manifest-path components/riceplate-wayland/Cargo.toml --check

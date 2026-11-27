#!/bin/bash
# local-ci step: native-smoke
# Mirrors: riceplate-native.yml / native-layer-shell / Boot native Wayland layer surface
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 240s sh scripts/smoke_riceplate_native.sh
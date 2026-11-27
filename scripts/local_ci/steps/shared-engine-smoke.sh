#!/bin/bash
# local-ci step: shared-engine-smoke
# Mirrors: riceplate-native.yml / native-layer-shell / Prove shared Rice engine across three native compositor-confirmed live layouts
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 125s sh scripts/smoke_wayland_shared_rice_engine.sh
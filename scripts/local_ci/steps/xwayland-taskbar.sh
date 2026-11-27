#!/bin/bash
# local-ci step: xwayland-taskbar
# Mirrors: riceplate-native.yml / native-layer-shell / Prove legacy XWayland application uses native RicePlate taskbar
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 70s sh scripts/smoke_riceplate_windows.sh --xwayland
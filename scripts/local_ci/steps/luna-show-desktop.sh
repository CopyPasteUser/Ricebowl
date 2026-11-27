#!/bin/bash
# local-ci step: luna-show-desktop
# Mirrors: riceplate-native.yml / native-layer-shell / Prove XP Luna Show Desktop with real Wayland window and screenshot changes
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 70s sh scripts/smoke_riceplate_windows.sh --luna
#!/bin/bash
# local-ci step: chrome-window-lifecycle
# Mirrors: riceplate-native.yml / native-layer-shell / Verify real Chrome-rice Wayland window lifecycle
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 70s sh scripts/smoke_riceplate_windows.sh --chrome
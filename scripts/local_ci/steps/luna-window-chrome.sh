#!/bin/bash
# local-ci step: luna-window-chrome
# Mirrors: riceplate-native.yml / native-layer-shell / Capture reversible Luna compositor window decorations
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 80s sh scripts/smoke_luna_window_chrome.sh

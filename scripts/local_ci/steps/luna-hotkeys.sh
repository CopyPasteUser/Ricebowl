#!/bin/bash
# local-ci step: luna-hotkeys
# Mirrors: riceplate-native.yml / native-layer-shell / Verify real XP Super+D/E/R shortcuts and native Run dialog
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 90s sh scripts/smoke_luna_hotkeys.sh
#!/bin/bash
# local-ci step: luna-autohide
# Mirrors: riceplate-native.yml / native-layer-shell / Prove real XP Luna Auto-hide and Start popup lifecycle
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 65s sh scripts/smoke_riceplate_luna_autohide.sh
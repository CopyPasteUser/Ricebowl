#!/bin/bash
# local-ci step: sg1-window-recovery
# Mirrors: riceplate-native.yml / native-layer-shell / Prove real SG1 window minimize/restore/close recovery on Chrome and XP Luna
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 90s sh scripts/smoke_sg1_window_recovery_labwc.sh
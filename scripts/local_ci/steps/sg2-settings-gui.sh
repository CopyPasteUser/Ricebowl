#!/bin/bash
# local-ci step: sg2-settings-gui
# Mirrors: riceplate-native.yml / native-layer-shell / Prove RiceSpice denied/busy/unavailable states on every settings page (real GTK under labwc, fake providers)
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 480s sh scripts/smoke_sg2_settings_gui_labwc.sh

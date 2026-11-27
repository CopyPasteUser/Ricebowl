#!/bin/bash
# local-ci step: windows-taskbar
# Mirrors: riceplate-native.yml / native-layer-shell / Prove live Wayland application taskbar lifecycle
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m unittest tests.test_de_window_outputs -v
timeout -k 5s 70s sh scripts/smoke_riceplate_windows.sh

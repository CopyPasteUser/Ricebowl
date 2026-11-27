#!/bin/bash
# local-ci step: luna-settings-labwc
# Mirrors: wayland-session.yml / session-smoke / Capture real Luna GTK system UI under native labwc
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
mkdir -p dist/luna-labwc
sh -n scripts/smoke_luna_settings_labwc.sh
/usr/bin/python3 -m py_compile scripts/capture_luna_labwc.py
timeout -k 5s 95s sh scripts/smoke_luna_settings_labwc.sh "$PWD/dist/luna-labwc"

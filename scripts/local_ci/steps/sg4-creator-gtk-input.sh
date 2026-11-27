#!/bin/bash
# local-ci step: sg4-creator-gtk-input
# Mirrors: riceplate-native.yml / sg4-creator-gtk-input / Verify real Wayland Tab/Return reaches both GTK Creator templates
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
sh -n scripts/smoke_creator_gui_labwc.sh
mkdir -p "$RUNNER_TEMP/creator-gtk-keyboard"
timeout -k 3s 90s sh scripts/smoke_creator_gui_labwc.sh \
  "$RUNNER_TEMP/creator-gtk-keyboard"

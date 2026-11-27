#!/bin/bash
# local-ci step: creator-gtk-wayland
# Mirrors: riceplate-native.yml / native-layer-shell / Test real Wayland GTK Creator keyboard focus for both Composer rices
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
sh -n scripts/smoke_creator_gui_labwc.sh
mkdir -p dist/riceplate-native-preview/creator-gtk-wayland
timeout -k 5s 95s sh scripts/smoke_creator_gui_labwc.sh \
  "$PWD/dist/riceplate-native-preview/creator-gtk-wayland"

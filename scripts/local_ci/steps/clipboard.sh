#!/bin/bash
# local-ci step: clipboard
# Mirrors: riceplate-native.yml / native-layer-shell / Prove bidirectional Wayland and XWayland clipboard
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 65s sh scripts/smoke_wayland_clipboard.sh
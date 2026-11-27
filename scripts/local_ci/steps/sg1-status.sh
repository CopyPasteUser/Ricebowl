#!/bin/bash
# local-ci step: sg1-status
# Mirrors: riceplate-native.yml / native-layer-shell / Prove honest native status controls (Wi-Fi/volume/mute) under labwc
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 240s sh scripts/smoke_sg1_status_labwc.sh
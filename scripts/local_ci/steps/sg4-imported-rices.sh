#!/bin/bash
# local-ci step: sg4-imported-rices
# Mirrors: riceplate-native.yml / native-layer-shell / Prove interactive pointer/keyboard/popup/error/AT-SPI behavior of both imported Creator rices (Heritage, Orbit) under labwc
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 300s sh scripts/smoke_sg4_imported_rices_labwc.sh
#!/bin/bash
# local-ci step: multioutput
# Mirrors: riceplate-native.yml / native-layer-shell / Prove two native outputs, secondary calendar/menu and hotplug
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 70s sh scripts/smoke_riceplate_multioutput.sh
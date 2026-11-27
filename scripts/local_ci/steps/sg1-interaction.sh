#!/bin/bash
# local-ci step: sg1-interaction
# Mirrors: riceplate-native.yml / native-layer-shell / Prove SG1 window/launcher/clock/SNI/failure-notice/desktop-file/output interaction negatives under labwc
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 600s sh scripts/smoke_sg1_interaction_labwc.sh
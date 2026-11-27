#!/bin/bash
# local-ci step: sg1-sni
# Mirrors: riceplate-native.yml / native-layer-shell / Prove real SNI provider owner lifecycle on Chrome and XP Luna under labwc
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout -k 5s 105s sh scripts/smoke_sg1_sni_labwc.sh
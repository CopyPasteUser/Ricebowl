#!/bin/bash
# local-ci step: native-syntax
# Mirrors: riceplate-native.yml / native-layer-shell / Fail fast on SG5 external harness syntax
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
sh -n scripts/smoke_luna_atspi.sh
/usr/bin/python3 -m py_compile scripts/smoke_riceplate_atspi_client.py

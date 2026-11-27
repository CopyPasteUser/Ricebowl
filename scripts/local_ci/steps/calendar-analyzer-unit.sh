#!/bin/bash
# local-ci step: calendar-analyzer-unit
# Mirrors: riceplate-native.yml / native-layer-shell / Validate two-output calendar pixel analyzer
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m unittest discover -s tests -p test_de_calendar_outputs.py -v
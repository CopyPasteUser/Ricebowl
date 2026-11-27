#!/bin/bash
# local-ci step: menu-analyzer-unit
# Mirrors: riceplate-native.yml / native-layer-shell / Validate two-output menu pixel analyzer
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m unittest discover -s tests -p test_de_menu_outputs.py -v
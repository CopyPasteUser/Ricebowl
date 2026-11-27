#!/bin/bash
# local-ci step: creator-examples-validate
# Mirrors: riceplate-native.yml / native-layer-shell / Validate both declarative Creator examples
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m unittest discover -s tests -p test_de_creator_examples.py -v
/usr/bin/python3 -m unittest tests.test_de_ricepack_export_durability -v

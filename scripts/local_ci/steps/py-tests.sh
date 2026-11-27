#!/bin/bash
# local-ci step: py-tests
# Mirrors: ci.yml / test / Validate and test the suite [unittest discover]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m unittest discover -s tests -v

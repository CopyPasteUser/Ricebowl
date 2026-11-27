#!/bin/bash
# local-ci step: py-compile
# Mirrors: ci.yml / test / Validate and test the suite [compileall]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m compileall -q macrice launcher.py

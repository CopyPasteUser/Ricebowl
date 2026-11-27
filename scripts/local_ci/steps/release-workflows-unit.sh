#!/bin/bash
# local-ci step: release-workflows-unit
# Mirrors: release-candidate.yml / source-gate / Require exact-source main CI for candidate and stable artifacts
# Local adaptation: check_release_workflows.py queries hosted Actions evidence and is not translated
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m unittest tests.test_release_workflows -v

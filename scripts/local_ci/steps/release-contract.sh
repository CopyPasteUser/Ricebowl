#!/bin/bash
# local-ci step: release-contract
# Mirrors: release-candidate.yml / source-gate / Require matching version and documented hardware approval for stable 1.0
# Local adaptation: tag-dependent check_release_contract.py runs only with LCI_RELEASE_TAG
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
# check_release_contract.py needs a release tag. Local CI runs it only when a
# tag is supplied (LCI_RELEASE_TAG); otherwise only the contract unit tests run.
if [ -n "${LCI_RELEASE_TAG:-}" ]; then
  /usr/bin/python3 scripts/check_release_contract.py --tag "$LCI_RELEASE_TAG"
fi
/usr/bin/python3 -m unittest tests.test_release_contract -v

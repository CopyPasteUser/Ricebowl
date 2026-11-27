#!/bin/bash
# local-ci step: sg7-resource-receipts
# Mirrors: riceplate-native.yml / native-layer-shell / Verify SG7 compositor resource growth receipts at exact source SHA
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
set -eu
/usr/bin/python3 -m unittest tests.test_sg7_resource_receipts -v
/usr/bin/python3 scripts/verify_sg7_resource_receipts.py \
  --directory "$PWD/dist/riceplate-native-preview/shared-engine" \
  --source-commit "$GITHUB_SHA"

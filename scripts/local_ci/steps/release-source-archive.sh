#!/bin/bash
# local-ci step: release-source-archive
# Mirrors: release-candidate.yml / source-gate / Produce source archive and checksum
# Local adaptation: RELEASE_TAG comes from LCI_RELEASE_TAG or a local placeholder
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
RELEASE_TAG="${LCI_RELEASE_TAG:-local-$GITHUB_SHA}"
mkdir -p dist
git archive --format=zip --output="dist/RiceBowl-${RELEASE_TAG}-source.zip" HEAD
(cd dist && sha256sum RiceBowl-*-source.zip > SHA256SUMS)

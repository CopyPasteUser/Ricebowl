#!/bin/bash
# local-ci step: release-source-verify
# Mirrors: ci.yml / publish-ricebowl / Verify release source and package
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
test -f RICEBOWL.md
test -f RELEASE_NOTES.md
test -f assets/ricebowl-symbolic.svg
mkdir -p dist
git archive --format=zip --output=dist/RiceBowl-v0.9.1-source.zip HEAD
(cd dist && sha256sum RiceBowl-v0.9.1-source.zip | tee SHA256SUMS)

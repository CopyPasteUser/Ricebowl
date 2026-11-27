#!/bin/bash
# local-ci step: creator-supervisor-e2e
# Mirrors: riceplate-native.yml / native-layer-shell / Prove Creator install and recovery through the real Wayland supervisor socket
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m unittest \
  tests.test_wayland_creator_e2e tests.test_wayland_creator_handoff -v

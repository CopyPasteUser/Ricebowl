#!/bin/bash
# local-ci step: creator-teardown
# Mirrors: riceplate-native.yml / native-layer-shell / Prove Creator teardown after real success and injected failures
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
export PATH="$PWD/components/riceplate-wayland/target/release:$PATH"
export RICEBOWL_TEST_NATIVE_RENDER=1
dbus-run-session -- /usr/bin/python3 -m unittest \
  tests.test_de_render.HeadlessRenderTests.test_real_headless_success_and_injected_failures_leave_no_processes -v

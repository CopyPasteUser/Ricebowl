#!/bin/bash
# local-ci step: py-native-unit
# Mirrors: riceplate-native.yml / native-layer-shell / Build and test native RicePlate [Python unit tests]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m unittest tests.test_de_session -v
/usr/bin/python3 -m unittest tests.test_de_acceptance -v
/usr/bin/python3 -m unittest tests.test_ci_wayland_resource_smoke -v
/usr/bin/python3 -m unittest tests.test_wayland_payload_safety tests.test_wayland_control_safety tests.test_wayland_control_path_limits -v

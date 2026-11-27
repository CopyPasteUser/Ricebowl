#!/bin/bash
# local-ci step: portal-smoke
# Mirrors: riceplate-native.yml / native-layer-shell / Validate portal screenshot and headless ScreenCast negotiation
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
sh -n scripts/smoke_wayland_portals.sh
sh -n scripts/wayland_portals_smoke_client.sh
/usr/bin/python3 -m unittest discover -s tests -p test_wayland_portal_probe.py -v
/usr/bin/python3 -m unittest discover -s tests -p test_wayland_portal_capture.py -v
timeout -k 5s 80s sh scripts/smoke_wayland_portals.sh

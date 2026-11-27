#!/bin/bash
# local-ci step: portal-unit
# Mirrors: wayland-portal-strict.yml / portal-unit / Test negative paths and validate shell / Python syntax
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
sh -n scripts/smoke_wayland_portals.sh
sh -n scripts/wayland_portals_smoke_client.sh
/usr/bin/python3 -m py_compile scripts/wayland_portal_capture_smoke.py scripts/wayland_portal_frame_painter.py scripts/ci_portal_generic_remote.py scripts/ci_portal_pipewire_link.py scripts/check_wayland_portals.py
/usr/bin/python3 -m unittest discover -s tests -p 'test_wayland_portal_*.py' -v

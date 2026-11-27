#!/bin/bash
# local-ci step: portal-strict-frame
# Mirrors: wayland-portal-strict.yml / portal-strict-software-frame / Strict no-DRM ScreenCast from real wlroots SHM frames to GStreamer
# Local adaptation: step env exported inline; the pinned backend must already be installed by the operator (never installed by local CI)
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
export RICEBOWL_PORTAL_RENDERER=pixman RICEBOWL_PORTAL_BACKEND=generic RICEBOWL_PORTAL_STRICT_CI=1
timeout -k 5s 160s sh scripts/smoke_wayland_portals.sh

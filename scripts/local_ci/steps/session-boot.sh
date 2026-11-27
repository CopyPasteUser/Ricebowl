#!/bin/bash
# local-ci step: session-boot
# Mirrors: wayland-session.yml / session-smoke / Boot actual labwc and Waybar headlessly
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
RICEBOWL_SMOKE_RICEPOP=1 timeout -k 5s 60s sh scripts/smoke_wayland_session.sh
timeout -k 5s 45s sh scripts/smoke_wayland_session.sh chrome
timeout -k 5s 45s sh scripts/smoke_wayland_session.sh classic
RICEBOWL_SMOKE_OUTPUTS=2 timeout -k 5s 60s sh scripts/smoke_wayland_session.sh classic

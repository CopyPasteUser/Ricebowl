#!/bin/bash
# local-ci step: mako111-real
# Mirrors: wayland-session.yml / session-smoke / Verify real source-locked Mako 1.11 notification arrivals in labwc
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
# Uses only temporary source/build dirs and a new private Wayland
# compositor plus private D-Bus. Never installs or switches Mako.
sh scripts/smoke_real_mako_111.sh

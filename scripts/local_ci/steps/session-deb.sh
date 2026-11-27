#!/bin/bash
# local-ci step: session-deb
# Mirrors: wayland-session.yml / session-smoke / Build non-installed login session package
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
sh scripts/build_wayland_session_deb.sh
dpkg-deb --field dist/ricebowl-wayland-session_0.1.0~preview3_all.deb
sh scripts/test_wayland_package_reproducibility.sh

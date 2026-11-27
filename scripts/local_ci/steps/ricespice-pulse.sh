#!/bin/bash
# local-ci step: ricespice-pulse
# Mirrors: wayland-session.yml / session-smoke / Validate and test isolated session runtime [PulseAudio smoke]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
# Real disposable PulseAudio server, isolated socket and app stream;
# no changes to host audio devices or the logged-in user's session.
/usr/bin/python3 -m py_compile scripts/smoke_ricespice_pulse.py
RICEBOWL_SG2_DISPOSABLE=1 timeout -k 2s 40s dbus-run-session -- /usr/bin/python3 scripts/smoke_ricespice_pulse.py

#!/bin/bash
# local-ci step: session-unit
# Mirrors: wayland-session.yml / session-smoke / Validate and test isolated session runtime
# Local adaptation: the disposable PulseAudio smoke is its own step (ricespice-pulse)
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m compileall -q macrice/de macrice/cli.py
/usr/bin/python3 -m unittest discover -s tests -p 'test_de_*.py' -v
/usr/bin/python3 -m unittest tests.test_wayland_creator_e2e tests.test_wayland_creator_handoff -v
# Session-specific DesktopNames is valid for display managers but
# desktop-file-validate only knows ordinary application entries.
sh -n scripts/build_wayland_session_deb.sh
sh -n scripts/test_wayland_package_reproducibility.sh
sh -n scripts/smoke_wayland_session.sh
sh -n scripts/smoke_real_mako_111.sh
/usr/bin/python3 -m py_compile scripts/smoke_wayland_ricepop.py scripts/smoke_ricepop_atspi_client.py scripts/smoke_ricepop_modern_bus.py scripts/smoke_ricepop_recovery.py scripts/smoke_ricepop_live_updates.py
# Real private D-Bus wire contract for Mako 1.11+, separately from
# the production Mako 1.8 close signal checked by the labwc smoke.
timeout -k 2s 15s dbus-run-session -- /usr/bin/python3 scripts/smoke_ricepop_modern_bus.py

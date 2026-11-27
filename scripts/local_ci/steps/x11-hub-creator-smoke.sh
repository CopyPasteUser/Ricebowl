#!/bin/bash
# local-ci step: x11-hub-creator-smoke
# Mirrors: ci.yml / test / Validate and test the suite [hub and Creator smoke]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
# Catch GTK constructor/style/asset regressions in the real hub.
RICEBOWL_HUB_SMOKE=1 timeout 18s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 -c 'from macrice.hub import run; raise SystemExit(run())'
# Exercise the real optional GTK Creator, immutable draft, editor,
# revision/undo and X11 rendering without touching user settings.
creator_state="$(mktemp -d -t ricebowl-creator-XXXXXX)"
mkdir -m 700 "$creator_state/config"
mkdir -p dist/creator-gtk-smoke
RICEBOWL_CREATOR_SMOKE=1 XDG_STATE_HOME="$creator_state" \
  XDG_CONFIG_HOME="$creator_state/config" \
  RICEBOWL_CREATOR_SMOKE_CAPTURE="$PWD/dist/creator-gtk-smoke/creator.png" \
  timeout 40s dbus-run-session -- xvfb-run -a -s '-screen 0 1600x900x24' \
  /usr/bin/python3 launcher.py creator

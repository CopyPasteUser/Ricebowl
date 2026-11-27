#!/bin/bash
# local-ci step: x11-shell-smoke
# Mirrors: ci.yml / test / Validate and test the suite [shell smoke tests]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -c 'from macrice.aero_shell import run; raise SystemExit(run(["ricehub-aero-shell", "--smoke-test"]))'
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -c 'from macrice.ten_shell import run; raise SystemExit(run(["ricehub-ten-shell", "--smoke-test"]))'
for profile in winxp winclassic chromeos frutiger; do
  RICEHUB_PROFILE="$profile" timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -c 'import os; from macrice.aero_shell import run; p=os.environ["RICEHUB_PROFILE"]; raise SystemExit(run([f"ricehub-{p}-shell", "--smoke-test"], profile=p))'
done
# Synthetic button.clicked() misses X11 pointer hit-testing after
# switching Aqua from Apps to the taller Settings list.
RICEHUB_AQUA_NAV_NATIVE=1 timeout 28s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' sh -c 'xfwm4 --compositor=off >/tmp/ricebowl-aqua-native-xfwm4.log 2>&1 & sleep 1; test_config="$(mktemp -d -t ricebowl-aqua-nav-XXXXXX)"; XDG_CONFIG_HOME="$test_config" /usr/bin/python3 -c '\''from macrice.aero_shell import run; raise SystemExit(run(["ricehub-frutiger-shell", "--smoke-test"], profile="frutiger"))'\'''
# Real X11 pointer dwell catches the classic 650ms focus-loss bug.
RICEHUB_CLASSIC_POINTER_NATIVE=1 timeout 28s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' sh -c 'xfwm4 --compositor=off >/tmp/ricebowl-classic-pointer-xfwm4.log 2>&1 & sleep 1; /usr/bin/python3 -c '\''from macrice.aero_shell import run; raise SystemExit(run(["ricehub-winclassic-shell", "--smoke-test"], profile="winclassic"))'\'''
timeout 30s dbus-run-session -- xvfb-run -a sh -c 'xfwm4 >/tmp/ricehub-ci-xfwm4.log 2>&1 & sleep 1; RICEHUB_WNCK_INTEGRATION=1 /usr/bin/python3 -m unittest tests.test_aero_windows.AeroWindowTests.test_native_window_open_close_does_not_crash_shell -v'

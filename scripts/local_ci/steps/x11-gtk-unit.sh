#!/bin/bash
# local-ci step: x11-gtk-unit
# Mirrors: ci.yml / test / Validate and test the suite [GTK unit suites under Xvfb]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
# RiceSpice must construct and navigate all real GTK sections, even
# when no Linux hardware services are present on a CI runner.
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -m unittest tests.test_de_settings_gui -v
# Exercise the XP Luna-specific GTK category overview and live search.
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -m unittest tests.test_wayland_luna_settings -v
timeout 18s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 -m unittest tests.test_luna_system_ux_fidelity -v
# Exercise real Windows 10 Settings search, sidebar and live controls.
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -m unittest tests.test_ten_settings_gui -v
# Exercise the actual Win98 Find GTK widgets, not only parser contracts.
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -m unittest tests.test_classic98_find_gui -v
# Exercise the second-click Win98 Help topics, Back and local Search in a real GTK window.
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -m unittest tests.test_classic98_help_gui -v
# Verify the read-only classic System Properties dialog on a real X11 display.
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -m unittest tests.test_classic98_system_gui -v
# Frutiger's date flyout uses real GTK Calendar/Popover controls.
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -m unittest tests.test_frutiger_calendar_gui -v
# Standalone settings windows are normal WM clients with usable,
# keyboard-accessible drag handles rather than auto-hiding popovers.
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -m unittest tests.test_rice_windows_gui -v
# ricePlate remains a normal preview window with real, bounded desktop icons.
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 -m unittest tests.test_riceplate_preview_gui -v

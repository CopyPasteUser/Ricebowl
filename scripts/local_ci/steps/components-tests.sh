#!/bin/bash
# local-ci step: components-tests
# Mirrors: ci.yml / test / Validate and test the suite [macmenu, macbar, control-center]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
(cd components/macmenu && /usr/bin/python3 -m unittest discover -s tests -v)
# The macOS-style launcher is a separate GTK application. Capture
# the real widget, not an invented MacBar/Plank composite.
(cd components/macmenu && timeout 24s dbus-run-session -- xvfb-run -a -s '-screen 0 1600x900x24' /usr/bin/python3 capture_screenshot.py --theme dark --output ../../screenshots/ricebowl-macmenu-dark-current.png)
/usr/bin/python3 -c 'from pathlib import Path; from PIL import Image; p=Path("screenshots/ricebowl-macmenu-dark-current.png"); assert p.is_file() and p.stat().st_size>10000; im=Image.open(p); assert 320<=im.width<=1000 and 300<=im.height<=900, "MacMenu screenshot clipped"'
(cd components/macbar && /usr/bin/python3 -m unittest discover -s tests -v)
(cd components/control-center && PATH=/usr/bin:/bin bash run-tests.sh)

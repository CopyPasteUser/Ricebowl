#!/bin/bash
# local-ci step: x11-luna-panel-capture
# Mirrors: ci.yml / test / Validate and test the suite [Luna Control Panel capture]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
# Visual QA from a real GTK client under Xvfb (not a Wayland capture).
timeout 18s dbus-run-session -- xvfb-run -a -s '-screen 0 1280x800x24' /usr/bin/python3 scripts/capture_luna_control_panel.py --output-dir dist/luna-settings
/usr/bin/python3 -c 'from pathlib import Path; from PIL import Image; import hashlib; ps=sorted(Path("dist/luna-settings").glob("luna-control-panel-*.png")); assert len(ps)==6, ps; assert all((lambda im: im.width >= 700 and im.height >= 470)(Image.open(p)) for p in ps), "Clipped Luna Control Panel capture"; assert len({hashlib.sha256(p.read_bytes()).digest() for p in ps})==6, "Luna Control Panel views rendered identical"; assert (Path("dist/luna-settings") / "luna-control-panel-capture-metrics.json").is_file()'

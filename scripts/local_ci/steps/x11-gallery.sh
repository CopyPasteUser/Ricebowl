#!/bin/bash
# local-ci step: x11-gallery
# Mirrors: ci.yml / test / Validate and test the suite [screenshot gallery and compact-screen captures]
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
timeout 18s dbus-run-session -- xvfb-run -a -s '-screen 0 1600x900x24' /usr/bin/python3 screenshots/capture_ten_shell.py
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 screenshots/capture_windows10.py
timeout 18s dbus-run-session -- xvfb-run -a /usr/bin/python3 screenshots/capture_windows10_hub.py
for profile in windows10 winxp winclassic chromeos frutiger; do
  RICEHUB_PROFILE="$profile" timeout 24s dbus-run-session -- xvfb-run -a -s '-screen 0 1600x900x24' /usr/bin/python3 -c 'import os; from macrice.aero_shell import run; p=os.environ["RICEHUB_PROFILE"]; raise SystemExit(run([f"ricebowl-{p}-shell", "--capture-gallery"], profile=p))'
done
# Aero Control Panel is now a real decorated window; run the XFWM4
# compositor-free native frame rather than capturing bare GTK only.
timeout 35s dbus-run-session -- xvfb-run -a -s '-screen 0 1600x900x24' /usr/bin/python3 screenshots/capture_win7_panel.py
# Fail the release if any gallery screen silently failed to capture.
# Flat Windows 98 teal compresses to ~28 KiB as a valid 1600x900 PNG;
# size alone must not reject a real capture. The area-diff validation below
# independently proves that the functional control panel rendered.
/usr/bin/python3 -c 'from pathlib import Path; import hashlib, struct; fs=sorted(Path("screenshots").glob("ricebowl-*-0.9.1.png")); assert len(fs)==20, f"Expected 20 GTK captures, found {len(fs)}"; data=[p.read_bytes() for p in fs]; assert all(len(b)>15000 and b[:8]==bytes.fromhex("89504e470d0a1a0a") and struct.unpack(">II", b[16:24])==(1600,900) for b in data), "Invalid or incomplete screenshot"; assert len({hashlib.sha256(b).digest() for b in data})==20, "Duplicate screenshot detected"'
/usr/bin/python3 screenshots/validate_gallery.py
# Capture the real second-click ChromeOS notification and Settings
# pages, including honest unavailable-provider states in CI.
/usr/bin/python3 -c 'from pathlib import Path; import struct; names=("notifications","settings"); fs=[Path(f"screenshots/ricebowl-chromeos-{name}-0.9.1-extra.png") for name in names]; assert all(p.is_file() and p.stat().st_size>12000 and struct.unpack(">II",p.read_bytes()[16:24])==(1600,900) for p in fs), "Missing ChromeOS detail screenshots"'
/usr/bin/python3 -c 'from pathlib import Path; import struct; names=("home","sound"); fs=[Path(f"screenshots/ricebowl-windows10-settings-{name}-0.9.1-extra.png") for name in names]; assert all(p.is_file() and p.stat().st_size>16000 and struct.unpack(">II",p.read_bytes()[16:24])==(1600,900) for p in fs), "Missing Windows 10 Settings screenshots"'
/usr/bin/python3 -c 'from pathlib import Path; import struct; names=("letters","actions-expanded"); fs=[Path(f"screenshots/ricebowl-windows10-{name}-0.9.1-extra.png") for name in names]; assert all(p.is_file() and p.stat().st_size>16000 and struct.unpack(">II",p.read_bytes()[16:24])==(1600,900) for p in fs), "Missing Windows 10 interaction screenshots"'
# Each desktop must also render a REAL application window, with its
# own GTK theme, icons, Thunar controls and native XFWM4 titlebar.
# The helper uses a temporary HOME inside a fresh DBus/Xvfb session.
for profile in aero windows10 winxp winclassic chromeos frutiger; do
  timeout 35s dbus-run-session -- xvfb-run -a -s '-screen 0 1600x900x24' /usr/bin/python3 screenshots/capture_native_workspace.py "$profile"
done
/usr/bin/python3 -c 'from pathlib import Path; import struct; fs=sorted(Path("screenshots").glob("ricebowl-*-workspace-0.9.1.png")); assert len(fs)==6, f"Expected 6 genuine workspace captures, got {len(fs)}"; assert all(p.stat().st_size>30000 and struct.unpack(">II",p.read_bytes()[16:24])==(1600,900) for p in fs),"Invalid native XFWM4/Thunar screenshot"'
# XP 2001 layout must fit a real 1024x768 GTK/XFWM workarea as well.
RICEBOWL_CAPTURE_SIZE=1024 timeout 24s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 -c 'from macrice.aero_shell import run; raise SystemExit(run(["ricebowl-winxp-shell", "--capture-gallery"], profile="winxp"))'
/usr/bin/python3 -c 'from pathlib import Path; import struct; files=(Path("screenshots/ricebowl-winxp-properties-0.9.1-extra.png"),Path("screenshots/ricebowl-winxp-properties-0.9.1-1024-extra.png")); assert all(p.exists() and p.stat().st_size>12000 for p in files), "XP properties dialogs missing"; assert [struct.unpack(">II",p.read_bytes()[16:24]) for p in files]==[(1600,900),(1024,768)], "XP properties captures have wrong dimensions"'
/usr/bin/python3 -c 'from pathlib import Path; import struct; files=(Path("screenshots/ricebowl-winxp-notification-icons-0.9.1-extra.png"),Path("screenshots/ricebowl-winxp-notification-icons-0.9.1-1024-extra.png")); assert all(p.exists() and p.stat().st_size>12000 for p in files), "XP notification preferences dialogs missing"; assert [struct.unpack(">II",p.read_bytes()[16:24]) for p in files]==[(1600,900),(1024,768)], "XP notification dialogs have wrong dimensions"'
/usr/bin/python3 -c 'from pathlib import Path; import struct; files=(Path("screenshots/ricebowl-winxp-run-0.9.1-extra.png"),Path("screenshots/ricebowl-winxp-run-0.9.1-1024-extra.png")); assert all(p.exists() and p.stat().st_size>10000 for p in files), "XP Run dialogs missing"; assert [struct.unpack(">II",p.read_bytes()[16:24]) for p in files]==[(1600,900),(1024,768)], "XP Run captures have wrong dimensions"'
/usr/bin/python3 -c 'from pathlib import Path; import struct; names=("help","system"); fs=[Path(f"screenshots/ricebowl-winxp-{name}-0.9.1{size}-extra.png") for name in names for size in ("","-1024")]; assert all(p.exists() and p.stat().st_size>10000 for p in fs), "XP Help/System screenshots missing"; assert [struct.unpack(">II",p.read_bytes()[16:24]) for p in fs]==[(1600,900),(1024,768)]*2, "XP Help/System dialogs clipped or invalid"'
/usr/bin/python3 -c 'from pathlib import Path; import struct; fs=sorted(Path("screenshots").glob("ricebowl-winxp-*-0.9.1-1024.png")); assert len(fs)==10, "XP deep-menu/tray captures missing"; assert all(struct.unpack(">II", p.read_bytes()[16:24])==(1024,768) for p in fs), "XP 1024x768 capture invalid"'
RICEBOWL_CAPTURE_SIZE=1024 timeout 35s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 screenshots/capture_native_workspace.py winxp
/usr/bin/python3 -c 'from pathlib import Path; import struct; p=Path("screenshots/ricebowl-winxp-workspace-0.9.1-1024.png"); b=p.read_bytes(); assert len(b)>30000 and struct.unpack(">II", b[16:24])==(1024,768), "XP compact Thunar window invalid"'
# Windows 7 uses the historically sized 48px Superbar and a genuine
# framed Control Panel, both fitting a 1024x768 XFWM4 desktop.
RICEBOWL_CAPTURE_SIZE=1024 timeout 35s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 screenshots/capture_win7_panel.py
/usr/bin/python3 -c 'from pathlib import Path; import struct; fs=sorted(Path("screenshots").glob("ricebowl-aero-*-0.9.1-1024.png")); assert len(fs)==2, "Aero small-screen captures missing"; assert all(struct.unpack(">II", p.read_bytes()[16:24])==(1024,768) for p in fs), "Aero 1024x768 capture invalid"'
/usr/bin/python3 -c 'from pathlib import Path; import struct; files=(Path("screenshots/ricebowl-aero-action-center-0.9.1-extra.png"),Path("screenshots/ricebowl-aero-action-center-0.9.1-1024-extra.png")); assert all(p.exists() and p.stat().st_size>12000 for p in files), "Aero Action Center captures missing"; assert [struct.unpack(">II",p.read_bytes()[16:24]) for p in files]==[(1600,900),(1024,768)], "Aero Action Center captures have wrong dimensions"'
# The actual Thunar Explorer window must fit the same compact screen.
RICEBOWL_CAPTURE_SIZE=1024 timeout 35s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 screenshots/capture_native_workspace.py aero
/usr/bin/python3 -c 'from pathlib import Path; import struct; p=Path("screenshots/ricebowl-aero-workspace-0.9.1-1024.png"); b=p.read_bytes(); assert len(b)>30000 and struct.unpack(">II", b[16:24])==(1024,768), "Aero 1024x768 Thunar window invalid"'
# Aqua World must also fit on older 1024x768 laptops while preserving tab/search controls.
RICEBOWL_CAPTURE_SIZE=1024 timeout 24s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 -c 'from macrice.aero_shell import run; raise SystemExit(run(["ricebowl-frutiger-shell", "--capture-gallery"], profile="frutiger"))'
/usr/bin/python3 -c 'from pathlib import Path; import struct; fs=sorted(Path("screenshots").glob("ricebowl-frutiger-*-0.9.1-1024.png")); assert len(fs)==2, "Frutiger small-screen captures missing"; assert all(struct.unpack(">II", p.read_bytes()[16:24])==(1024,768) for p in fs), "Frutiger 1024x768 capture invalid"'
# Frutiger's redesigned Thunar chrome is also an actual XFWM4 window,
# not just a cropped shell mockup; verify its compact-screen fit.
RICEBOWL_CAPTURE_SIZE=1024 timeout 35s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 screenshots/capture_native_workspace.py frutiger
/usr/bin/python3 -c 'from pathlib import Path; import struct; p=Path("screenshots/ricebowl-frutiger-workspace-0.9.1-1024.png"); b=p.read_bytes(); assert len(b)>30000 and struct.unpack(">II", b[16:24])==(1024,768), "Frutiger 1024x768 Thunar window invalid"'
# Win98 Classic must keep its narrow cascades above a 34px taskbar at 1024x768.
RICEBOWL_CAPTURE_SIZE=1024 timeout 24s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 -c 'from macrice.aero_shell import run; raise SystemExit(run(["ricebowl-winclassic-shell", "--capture-gallery"], profile="winclassic"))'
/usr/bin/python3 -c 'from pathlib import Path; import struct; fs=sorted(Path("screenshots").glob("ricebowl-winclassic-*-0.9.1-1024.png")); assert len(fs)==2, "Classic small-screen captures missing"; assert all(struct.unpack(">II", p.read_bytes()[16:24])==(1024,768) for p in fs), "Classic 1024x768 capture invalid"'
# Windows 10's real three-column Start and tall Action Center stay inside 1024x768.
RICEBOWL_CAPTURE_SIZE=1024 timeout 24s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 -c 'from macrice.ten_shell import run; raise SystemExit(run(["ricebowl-windows10-shell", "--capture-gallery"]))'
/usr/bin/python3 -c 'from pathlib import Path; import struct; fs=sorted(Path("screenshots").glob("ricebowl-windows10-*-0.9.1-1024.png")); assert len(fs)==2, "Ten small-screen captures missing"; assert all(struct.unpack(">II", p.read_bytes()[16:24])==(1024,768) for p in fs), "Ten 1024x768 capture invalid"'
/usr/bin/python3 -c 'from pathlib import Path; import struct; names=("home","sound"); fs=[Path(f"screenshots/ricebowl-windows10-settings-{name}-0.9.1-1024-extra.png") for name in names]; assert all(p.is_file() and p.stat().st_size>12000 and struct.unpack(">II",p.read_bytes()[16:24])==(1024,768) for p in fs), "Missing compact Windows 10 Settings screenshots"'
# Material You Launcher + Quick Settings must both be fully visible on 1024x768.
RICEBOWL_CAPTURE_SIZE=1024 timeout 24s dbus-run-session -- xvfb-run -a -s '-screen 0 1024x768x24' /usr/bin/python3 -c 'from macrice.aero_shell import run; raise SystemExit(run(["ricebowl-chromeos-shell", "--capture-gallery"], profile="chromeos"))'
/usr/bin/python3 -c 'from pathlib import Path; import struct; fs=sorted(Path("screenshots").glob("ricebowl-chromeos-*-0.9.1-1024.png")); assert len(fs)==2, "ChromeOS small-screen captures missing"; assert all(struct.unpack(">II", p.read_bytes()[16:24])==(1024,768) for p in fs), "ChromeOS 1024x768 capture invalid"'

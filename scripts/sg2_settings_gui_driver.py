#!/usr/bin/env python3
"""Fixture app + scenario driver for smoke_sg2_settings_gui_labwc.sh (SG2 WP2.4).

Runs only inside that script's disposable labwc + private D-Bus session.

``sg2_settings_gui_driver.py app <page> [luna]`` is the FIXTURE: the real
``macrice.de.settings.launch()`` (a real GTK3 Wayland window), with only the
system-service boundary replaced by the repository's own fake providers
(``FakeAdapters`` from tests/test_de_settings_gui_controls.py and
``FakePreferences`` from tests/test_de_sg2_gap_gui.py). Which write outcome the
providers produce is read from a control file on every call (``ok`` / ``denied``
/ ``hold``), so the driver can hold a write in flight. Confirmation dialogs are
auto-answered by the fixture (modal ``Dialog.run()`` freezes AT-SPI; the real
dialogs are covered by the Creator GUI smokes).

With no sub-command it is the DRIVER. Per RiceSpice page it proves the baseline,
**denied**, **busy** (a write held in flight, then a refused second click) and
**unavailable** (provider missing) states with
  * the accessibility tree: role, SHOWING state and text of the status widget, the
    presence/absence and SENSITIVE state of the control;
  * a ``grim`` crop of that widget's real output pixels, which must be inked and
    different in every state of the page;
  * the fake provider's call log: no replayed write, no write behind a refused
    busy click.
Buttons are pressed with real compositor pointer events; check boxes use AT-SPI
actions (a ``wtype`` key sent alone or last does nothing in a GTK3 toplevel: GDK3 ignores the
highest keycode of wtype's keymap; see GTK_PAD_KEY in smoke_sg3_ricepop_native_driver.py).

Every receipt line is "PASS: <cell>".
"""
from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(os.environ.get("SG2G_ROOT") or Path(__file__).resolve().parents[1])
RUNTIME = Path(os.environ.get("SG2G_RUNTIME", "/nonexistent"))
CTL = RUNTIME / "ctl.json"
CALLS = RUNTIME / "calls.log"

DENIED_TYPED = "Permission denied: the system did not authorize this change; nothing was changed"
DENIED_FILE = "Unavailable or denied: [Errno 13] Permission denied"
WORKING = "Working with system services…"
REFUSED = "System request in progress; retry this action when it finishes."

# page -> fixture/driver table. ``control`` is the write button pressed with the
# pointer; ``typed`` says the denial is a typed polkit refusal (adapter-backed page)
# rather than a file-store EACCES. ``unavail`` is the exact text the page shows when
# its provider is missing; ``absent`` is the control that must then be withheld.
PAGES = {
    "network": dict(
        control="Disable Wi-Fi", typed=True, base="Wi-Fi radio: enabled",
        done="Wi-Fi radio: disabled", unavail="Wi-Fi radio/scan unavailable: NetworkManager is not running",
        absent="Disable Wi-Fi"),
    "audio": dict(
        control="Set default output", typed=True, base="Current audio and media state",
        done="Current audio and media state",
        unavail="Audio devices unavailable: PulseAudio is not running", absent="Set default output"),
    "notifications": dict(
        control="Turn on Do Not Disturb", typed=True, base="Do Not Disturb: off",
        done="Do Not Disturb: on",
        unavail="Unavailable or denied: Notification host is not running", absent="Turn on Do Not Disturb"),
    "bluetooth": dict(
        control="Turn Bluetooth off", typed=True, base="Bluetooth adapter: on",
        done="Bluetooth adapter: off",
        unavail="Unavailable or denied: BlueZ is not running", absent="Turn Bluetooth off"),
    "displays": dict(
        control="Save current layout as preset", typed=False,
        base="Current: 1920x1080@60.000Hz, scale 1, position 0,0", done=None,
        unavail="Saved monitor layout unavailable: Unsafe monitor preset file",
        absent="Save current layout as preset"),
    "input": dict(
        control="Save for next RiceBowl login", typed=False, base="Currently using inherited settings",
        done="RiceBowl overrides enabled",
        unavail="Private RiceSpice preferences unavailable: Unsafe RiceSpice preference file",
        absent="Save for next RiceBowl login"),
    "accessibility": dict(
        control="Save for next RiceBowl login", typed=False, base="Currently using inherited settings",
        done="RiceBowl overrides enabled",
        unavail="Private RiceSpice preferences unavailable: Unsafe RiceSpice preference file",
        absent="Save for next RiceBowl login"),
    "timezone": dict(
        control="Disable automatic time", typed=True, base="System timezone: UTC",
        done="Current state: disabled",
        unavail="Unavailable or denied: timedated is not running", absent="Disable automatic time"),
    "power": dict(
        control="Lock screen", typed=True, base="Battery: No battery detected",
        done="Lock screen launched",
        unavail="Unavailable or denied: Power profile provider unavailable; refresh",
        absent="Apply energy profile"),
    "appearance": dict(
        control="Restore previous next-login rice", typed=False, base="Next-login rice: classic",
        done="Next-login rice: chrome",
        unavail="Rice selection unavailable: rice selection store unreadable",
        absent="Restore previous next-login rice"),
    "taskbar": dict(
        luna=True, control="Save taskbar options for next Luna login", typed=False,
        base="Current saved clock format: 24h · next Luna login",
        done=None,
        unavail="Clock preferences unavailable: Unsafe Luna panel preference file",
        absent="Save clock format for next Luna login"),
}


# =========================================================================
# FIXTURE APP
# =========================================================================
def ctl_mode() -> str:
    try:
        return json.loads(CTL.read_text(encoding="utf-8"))["mode"]
    except (OSError, ValueError, KeyError):
        return "ok"


def guard(name: str, apply, denied):
    """One fake provider write: log it, hold while asked, refuse when asked."""
    with CALLS.open("a", encoding="utf-8") as handle:
        handle.write(name + "\n")
    deadline = time.monotonic() + 60
    while ctl_mode() == "hold" and time.monotonic() < deadline:
        time.sleep(0.05)
    if ctl_mode() == "denied":
        raise denied
    return apply()


def app(page: str, luna: bool, state: str) -> None:
    sys.path.insert(0, str(ROOT))
    from unittest import mock

    from macrice.de import preferences, settings
    from macrice.de import settings_backend as backend
    from macrice.de.wayland_displays import Output
    from tests.test_de_settings_gui_controls import FakeAdapters
    from tests.test_de_sg2_gap_gui import FakePreferences

    unavailable = state == "unavailable"
    typed_denial = backend.SettingsDenied()
    file_denial = PermissionError(errno.EACCES, "Permission denied")
    denied = typed_denial if PAGES[page]["typed"] else file_denial

    fake = FakeAdapters()
    fake.mutate = lambda name, apply: guard(name, apply, denied)
    if unavailable and page == "network":
        fake.wifi_error = backend.SettingsError("NetworkManager is not running")
    if unavailable and page == "displays":
        fake.preset_error = ValueError("Unsafe monitor preset file")
    patches = [
        mock.patch.object(backend, name, getattr(fake, name))
        for name in ("wifi_snapshot", "connection_profiles", "bluetooth_snapshot",
                     "timezone_snapshot", "ntp_snapshot", "set_wifi", "set_ntp",
                     "set_system_clock", "set_connection_profile",
                     "set_bluetooth_power", "set_bluetooth_connection")]
    patches += [
        mock.patch.object(backend, "external_tool", return_value=None),
        mock.patch.object(settings.wayland_displays, "_in_session", return_value=True),
        mock.patch.object(settings.wayland_displays, "inventory", return_value=(
            Output("HDMI-A-1", "1920x1080@60.000Hz", ("1920x1080@60.000Hz",), 1.0),)),
        mock.patch.object(settings.display_presets, "load", fake.preset_load),
        mock.patch.object(settings.display_presets, "save", fake.preset_save),
        mock.patch.object(settings.display_presets, "auto_trial_enabled", return_value=False),
        mock.patch.object(settings.display_restore, "plan", return_value=None),
    ]
    if unavailable and page == "bluetooth":
        def broken_bluetooth():
            raise backend.SettingsError("BlueZ is not running")
        patches.append(mock.patch.object(backend, "bluetooth_snapshot", broken_bluetooth))
    if unavailable and page == "timezone":
        def broken_timezone():
            raise backend.SettingsError("timedated is not running")
        patches.append(mock.patch.object(backend, "timezone_snapshot", broken_timezone))

    # --- audio -----------------------------------------------------------------
    def inspect():
        if unavailable:
            raise RuntimeError("PulseAudio is not running")
        return {"outputs": [{"name": "alsa_out.a", "description": "Speakers", "default": True},
                            {"name": "alsa_out.b", "description": "HDMI", "default": False}],
                "inputs": [{"name": "alsa_in.a", "description": "Mic", "default": True}]}
    patches += [
        mock.patch.object(settings.audio_devices, "inspect", inspect),
        mock.patch.object(settings.audio_devices, "playback_streams", lambda: {"streams": []}),
        mock.patch.object(settings.media, "read_media_players", lambda: []),
        mock.patch.object(settings.audio_devices, "set_default",
                          lambda kind, name, expected_current: fake.mutate(
                              "set_default", lambda: None)),
    ]

    # --- notifications -----------------------------------------------------------
    dnd = {"on": False}

    def dnd_status():
        if unavailable:
            raise settings.notifications.NotificationBridgeError(
                "Notification host is not running", "dnd_host_unverified")
        return {"do_not_disturb": dnd["on"]}

    def set_dnd(enabled, *, expected=None):
        def apply():
            dnd["on"] = enabled
            return {"do_not_disturb": enabled}
        return fake.mutate("set_dnd", apply)
    patches += [mock.patch.object(settings.notifications, "dnd_status", dnd_status),
                mock.patch.object(settings.notifications, "set_dnd", set_dnd)]

    # --- input / accessibility ---------------------------------------------------
    prefs = FakePreferences()
    if unavailable:
        prefs.load_error = preferences.PreferenceError("Unsafe RiceSpice preference file")
    original_save = prefs.save
    patches += [
        mock.patch.object(settings.preferences, "load", prefs.load),
        mock.patch.object(settings.preferences, "save",
                          lambda requested, *, expected: guard(
                              "preferences.save",
                              lambda: original_save(requested, expected=expected), denied)),
    ]

    # --- power ------------------------------------------------------------------
    def power_snapshot():
        if unavailable:
            raise backend.SettingsError("Power profile provider unavailable; refresh")
        return {"current": "balanced", "supported": ["power-saver", "balanced", "performance"],
                "battery": None}
    patches += [
        mock.patch.object(backend, "power_snapshot", power_snapshot),
        mock.patch.object(backend, "power_action",
                          lambda action, nested=False: fake.mutate("power_action", lambda: None)),
    ]

    # --- appearance --------------------------------------------------------------
    selection = {"current": "classic", "previous": "chrome"}

    def current_selection():
        if unavailable:
            raise OSError("rice selection store unreadable")
        return selection["current"], selection["previous"]

    def change_selection(chosen=None, *, restore=False, expected_active=None):
        def apply():
            if restore:
                selection["current"], selection["previous"] = selection["previous"], None
            else:
                selection["previous"], selection["current"] = selection["current"], chosen
        return guard("change_selection", apply, denied)
    patches += [mock.patch.object(settings.recipes, "current_selection", current_selection),
                mock.patch.object(settings.recipes, "change_selection", change_selection)]

    # --- taskbar (Luna) ----------------------------------------------------------
    from macrice.de import luna_panel_settings, luna_taskbar_settings
    taskbar = {"auto_hide": False, "quick_launch": True}

    def panel_load():
        if unavailable:
            raise luna_panel_settings.LunaPanelError("Unsafe Luna panel preference file")
        return {"clock_format": "24h"}

    def taskbar_save(desired, *, expected):
        return guard("taskbar.save", lambda: taskbar.update(desired) or dict(taskbar), denied)
    patches += [
        mock.patch.object(luna_panel_settings, "load", panel_load),
        mock.patch.object(luna_taskbar_settings, "load", lambda: dict(taskbar)),
        mock.patch.object(luna_taskbar_settings, "save", taskbar_save),
    ]

    # Confirmation dialogs are answered by the fixture (see the module docstring).
    Gtk, _Gdk, _GLib = settings._gtk_modules()
    patches.append(mock.patch.object(Gtk.MessageDialog, "run", lambda _dialog: Gtk.ResponseType.YES))
    for patch in patches:
        patch.start()
    settings.launch(page=page, luna=luna)


# =========================================================================
# DRIVER
# =========================================================================
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "app":
    app(sys.argv[2], len(sys.argv) > 3 and sys.argv[3] == "luna",
        sys.argv[4] if len(sys.argv) > 4 else "ok")
    sys.exit(0)

import pyatspi  # noqa: E402  (driver only)
from gi.repository import Atspi, GLib  # noqa: E402

Atspi.set_timeout(8000, 8000)
CLICKER = os.environ.get("SG2G_CLICKER", "")
WIDTH, HEIGHT = 1366, 768
SHOTS = RUNTIME / "shots"
receipts: list[str] = []
process: subprocess.Popen | None = None


class Fail(Exception):
    pass


def passed(cell: str) -> None:
    receipts.append(cell)
    print("PASS: " + cell, flush=True)


def require(condition, message: str) -> None:
    if not condition:
        raise Fail(message)


def wait_for(predicate, message: str, timeout: float = 10.0, step: float = 0.15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
        except (LookupError, RuntimeError, OSError, GLib.Error, subprocess.SubprocessError):
            value = None
        if value:
            return value
        time.sleep(step)
    raise Fail("timeout: " + message)


def _children(node, limit=400):
    for index in range(min(node.childCount, limit)):
        try:
            child = node.getChildAtIndex(index)
        except (LookupError, RuntimeError, GLib.Error):
            continue
        if child is not None:
            yield child


def application():
    for app_node in _children(pyatspi.Registry.getDesktop(0), 40):
        try:
            if app_node.name == Path(__file__).name:
                return app_node
        except (LookupError, RuntimeError, GLib.Error):
            continue
    return None


def walk(node, maximum=18):
    stack, visited = [(node, 0)], 0
    while stack and visited < 6000:
        current, depth = stack.pop()
        visited += 1
        yield current
        if depth < maximum:
            stack.extend((child, depth + 1) for child in _children(current))


def showing(node) -> bool:
    try:
        return node.getState().contains(pyatspi.STATE_SHOWING)
    except (LookupError, RuntimeError, GLib.Error):
        return False


def find(role: str, name: str | None = None, prefix: str | None = None,
         visible: bool = True) -> list:
    root = application()
    found = []
    if root is None:
        return found
    for node in walk(root):
        try:
            if node.getRoleName() != role:
                continue
            title = node.name or ""
        except (LookupError, RuntimeError, GLib.Error):
            continue
        if name is not None and title != name:
            continue
        if prefix is not None and not title.startswith(prefix):
            continue
        if not visible or showing(node):
            found.append(node)
    return found


def label_with(text: str):
    matches = [n for n in find("label") if (n.name or "") == text]
    return matches[0] if len(matches) == 1 else None


def button(name: str):
    """The one push button of that name, scrolled into view if the page is taller
    than the window (the Notifications DND switch sits at the very bottom)."""
    matches = find("push button", name, visible=False)
    if len(matches) != 1:
        return None
    node = matches[0]
    if not showing(node):
        # GTK3 does not implement AT-SPI scrollTo: drive the page's scroll bar (an
        # AT-SPI Value) to its end, which is what a user dragging it would do.
        for bar in find("scroll bar"):
            value = bar.queryValue()
            if value.maximumValue > value.minimumValue:
                value.currentValue = value.maximumValue
        deadline = time.monotonic() + 3
        while not showing(node) and time.monotonic() < deadline:
            time.sleep(0.1)
    return node if showing(node) else None


def sensitive(node) -> bool:
    return node.getState().contains(pyatspi.STATE_SENSITIVE)


def press(node) -> None:
    """A real compositor pointer click at the centre of a widget."""
    box = node.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
    x, y = box.x + box.width // 2, box.y + box.height // 2
    require(0 <= x < WIDTH and 0 <= y < HEIGHT, "widget %r is off screen at %d,%d" % (node.name, x, y))
    subprocess.run([CLICKER, str(x), str(y), str(WIDTH), str(HEIGHT)], check=True,
                   timeout=10, stdout=subprocess.DEVNULL)


def shot(name: str):
    from PIL import Image
    path = SHOTS / (name + ".png")
    subprocess.run(["grim", str(path)], check=True, timeout=15)
    image = Image.open(path).convert("RGB")
    image.load()
    return image


def widget_crop(node, name: str):
    """The real output pixels under an AT-SPI widget, and its ink pixel count."""
    from collections import Counter
    box = node.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
    require(box.width > 8 and box.height > 4 and 0 <= box.x and 0 <= box.y
            and box.x + box.width <= WIDTH and box.y + box.height <= HEIGHT,
            "status widget %r is not fully on the output: %r" % (node.name, (box.x, box.y, box.width, box.height)))
    crop = shot(name).crop((box.x, box.y, box.x + box.width, box.y + box.height))
    pixels = list(crop.getdata())
    background = Counter(pixels).most_common(1)[0][0]
    ink = sum(max(abs(a - b) for a, b in zip(p, background)) > 40 for p in pixels)
    crop.save(SHOTS / (name + "-crop.png"))
    return crop.tobytes(), ink


def calls() -> list[str]:
    try:
        return CALLS.read_text(encoding="utf-8").split()
    except OSError:
        return []


def set_mode(mode: str) -> None:
    CTL.write_text(json.dumps({"mode": mode}), encoding="utf-8")


def start_app(page: str, state: str) -> None:
    global process
    stop_app()
    log = open(RUNTIME / ("app-%s-%s.log" % (page, state)), "ab")
    argv = ["/usr/bin/python3", str(Path(__file__).resolve()), "app", page,
            "luna" if PAGES[page].get("luna") else "plain", state]
    process = subprocess.Popen(argv, env=dict(os.environ), cwd=str(RUNTIME),
                               stdout=log, stderr=subprocess.STDOUT)
    wait_for(lambda: find("frame"), "RiceSpice window on the bus", 40)
    time.sleep(0.8)


def stop_app() -> None:
    global process
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    process = None
    wait_for(lambda: application() is None, "RiceSpice left the accessibility bus", 10)


def page_status_label(page: str, expected: str):
    """The one showing label whose text is exactly ``expected``."""
    return wait_for(lambda: label_with(expected), "%s: a label reading %r" % (page, expected), 20)


def run_page(page: str) -> None:
    spec = PAGES[page]
    crops: dict[str, bytes] = {}

    def record(state: str, node) -> None:
        raw, ink = widget_crop(node, "%s-%s" % (page, state))
        require(ink >= 40, "%s %s: the painted status widget is blank (%d ink px)" % (page, state, ink))
        require(node.getRoleName() == "label" and showing(node), "%s %s: not a showing label" % (page, state))
        for earlier, other in crops.items():
            require(raw != other, "%s: the painted pixels of %r and %r are identical" % (page, state, earlier))
        crops[state] = raw

    # ---- baseline + denied + busy on a working provider ----------------------
    CALLS.write_text("", encoding="utf-8")
    set_mode("ok")
    start_app(page, "ok")
    control = wait_for(lambda: button(spec["control"]), "%s: control %r" % (page, spec["control"]), 30)
    base = spec["base"]
    record("ok", page_status_label(page, base))
    if page == "taskbar":
        # Save stays disabled until something changes: an AT-SPI action on a check box.
        require(not sensitive(control), "taskbar save is enabled before any change")
        find("check box", "Show Quick Launch buttons")[0].queryAction().doAction(0)
        wait_for(lambda: sensitive(button(spec["control"])), "taskbar save enabled by the toggle")
        control = button(spec["control"])
    require(sensitive(control), "%s: control starts disabled" % page)
    passed("%s: baseline status %r; control %r is present and enabled" % (page, base, spec["control"]))

    # denied
    set_mode("denied")
    press(control)
    denied_text = DENIED_TYPED if spec["typed"] else DENIED_FILE
    record("denied", page_status_label(page, denied_text))
    wait_for(lambda: not button(spec["control"]) is None and sensitive(button(spec["control"])),
             "%s: control stays usable after a denial" % page)
    time.sleep(0.4)
    require(len(calls()) == 1, "%s: a denied write was replayed: %r" % (page, calls()))
    passed("%s: denied -> status %r painted (distinct, inked crop); control still enabled; "
           "exactly one provider call, none replayed" % (page, denied_text))

    # busy: hold the write in flight, press again
    set_mode("hold")
    press(button(spec["control"]))
    record("busy", page_status_label(page, WORKING))
    wait_for(lambda: len(calls()) == 2, "%s: the held write reaches the provider" % page)
    press(button(spec["control"]))
    record("busy-refused", page_status_label(page, REFUSED))
    time.sleep(0.5)
    require(len(calls()) == 2, "%s: a click during a held write reached the provider: %r" % (page, calls()))
    passed("%s: busy -> %r then second real click -> %r painted; the provider saw 1 call, not 2"
           % (page, WORKING, REFUSED))
    set_mode("ok")
    done = spec["done"]
    if done:
        page_status_label(page, done)
    wait_for(lambda: label_with(WORKING) is None and label_with(REFUSED) is None,
             "%s: busy status clears when the write finishes" % page)
    time.sleep(0.4)
    require(len(calls()) == 2, "%s: the finished write was replayed: %r" % (page, calls()))
    passed("%s: released write completes once (%s); busy text gone; no replay"
           % (page, ("readback %r" % done) if done else "status cleared"))

    # ---- unavailable provider ------------------------------------------------
    start_app(page, "unavailable")
    unavailable = page_status_label(page, spec["unavail"])
    wait_for(lambda: label_with(WORKING) is None, "%s: unavailable page settled" % page)
    require(not find("push button", spec["absent"], visible=False),
            "%s: control %r is offered while its provider is unavailable" % (page, spec["absent"]))
    record("unavailable", unavailable)
    passed("%s: unavailable -> %r painted; %r withheld" % (page, spec["unavail"], spec["absent"]))
    passed("%s: %d states have pairwise-different painted crops (%s)" % (page, len(crops), ", ".join(crops)))
    stop_app()


def main() -> int:
    try:
        wanted = [name for name in PAGES if name in os.environ.get("SG2G_PAGES", " ".join(PAGES)).split()]
        for page in wanted:
            run_page(page)
    except Fail as failure:
        print("SG2 settings GUI smoke FAILED: %s" % failure, file=sys.stderr)
        try:
            subprocess.run(["grim", str(SHOTS / "failure.png")], timeout=10)
            for node in list(walk(application() or pyatspi.Registry.getDesktop(0), 7))[:120]:
                print("  %s %r" % (node.getRoleName(), node.name), file=sys.stderr)
        except Exception as error:  # diagnostics only
            print("diagnostics failed: %r" % error, file=sys.stderr)
        return 1
    finally:
        try:
            stop_app()
        except Fail:
            pass
    print("SG2 settings GUI: %d receipts PASS" % len(receipts))
    return 0


if __name__ == "__main__":
    sys.exit(main())

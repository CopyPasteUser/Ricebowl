#!/usr/bin/env python3
"""Scenario driver for smoke_sg3_ricepop_native_labwc.sh (SG3 WP3.1/3.2).

SG3_RICE=luna (default): native inbox, volume OSD, rendered-text/localization
matrix. SG3_RICE=chrome: volume OSD and the RiceSpice GTK RicePop inbox (the
only inbox of a rice without a native Notifications entry).

Runs only inside that script's disposable labwc + private D-Bus + private HOME.
It starts and stops the ONE Mako host itself (so a host restart is real), posts
real freedesktop notifications, and observes the native RicePop inbox only
through the public AT-SPI bus, real compositor keyboard/pointer input and the
notification bus. Every receipt line is "PASS: <cell>". Notification text in
this file is synthetic; it is the private-text canary for the privacy checks.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pyatspi

ROOT = Path(os.environ["SG3_ROOT"])
RUNTIME = Path(os.environ["SG3_RUNTIME"])
CLICKER = os.environ["SG3_CLICKER"]
RICE = os.environ.get("SG3_RICE", "luna")  # luna|chrome; SG3_MODE adds luna-de|luna-nofonts
PLATE_ARGS = shlex.split(os.environ.get("SG3_PLATE_ARGS", ""))
AUDIO = RUNTIME / "audio"
MAKO_CONFIG = os.environ["SG3_MAKO_CONFIG"]
APP = "SG3 Native"
# Private-text canaries: they must be visible only while the owner-verified
# inbox is open, and must never reach a file, an accessible name or a log.
CANARY = "sg3-private-" + secrets.token_hex(6)
OPEN_REFRESH = 3.0  # ricepop.rs OPEN_REFRESH_INTERVAL
RETRY_REFRESH = 12.0  # ricepop.rs RETRY_REFRESH_INTERVAL

mako: subprocess.Popen | None = None
monitor: subprocess.Popen | None = None
gtk: subprocess.Popen | None = None     # the RiceSpice window (chrome)
receipts: list[str] = []


class Fail(Exception):
    pass


def passed(cell: str) -> None:
    receipts.append(cell)
    print("PASS: " + cell, flush=True)


def require(condition, message: str) -> None:
    if not condition:
        raise Fail(message)


def wait_for(predicate, message: str, timeout: float = 8.0, step: float = 0.15):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
        except (LookupError, RuntimeError, OSError, subprocess.SubprocessError):
            last = None
        if last:
            return last
        time.sleep(step)
    raise Fail("timeout: " + message)


# ---------------------------------------------------------------- input ----
def wtype(*args: str) -> None:
    subprocess.run(["wtype", *args], check=True, timeout=10)


def key(name: str, pause: float = 0.25) -> None:
    wtype("-k", name)
    time.sleep(pause)


# --------------------------------------------------------------- AT-SPI ----
def _children(node, limit=200):
    for index in range(min(node.childCount, limit)):
        child = node.getChildAtIndex(index)
        if child is not None:
            yield child


def application(name: str = "riceplate-native"):
    desktop = pyatspi.Registry.getDesktop(0)
    for app in _children(desktop, 40):
        if app.name == name:
            return app
    return None


def walk(node, depth=0, maximum=7):
    yield node, depth
    if depth < maximum:
        for child in _children(node):
            yield from walk(child, depth + 1, maximum)


def snapshot(name: str = "riceplate-native", maximum: int = 7) -> list[dict]:
    """Every accessible node of one application: role, name, description, focus."""
    app = application(name)
    if app is None:
        return []
    rows = []
    for node, _ in walk(app, 0, maximum):
        try:
            rows.append({
                "role": node.getRoleName(), "name": node.name,
                "description": node.description,
                "focused": node.getState().contains(pyatspi.STATE_FOCUSED),
                "node": node})
        except (LookupError, RuntimeError):
            continue
    return rows


def inbox():
    rows = snapshot()
    if not any(r["role"] == "dialog" and r["name"] == "Notifications" for r in rows):
        return None
    return rows


def row_names(rows) -> list[str]:
    prefix = "View notification from " + APP + ": "
    return [r["name"][len(prefix):] for r in rows
            if r["role"] == "push button" and r["name"].startswith(prefix)]


def find_button(rows, name):
    matches = [r for r in rows if r["role"] == "push button" and r["name"] == name]
    return matches[0] if len(matches) == 1 else None


def rows_now() -> list[str]:
    rows = inbox()
    return row_names(rows) if rows else []


def tab_label() -> str:
    rows = inbox() or []
    labels = [r["name"] for r in rows if r["role"] == "page tab"
              and r["name"].startswith("Active notifications")]
    return labels[0] if labels else ""


def focused_name(rows=None) -> str:
    for row in (rows if rows is not None else inbox() or []):
        if row["focused"]:
            return row["name"]
    return ""


def select_row(summary: str) -> None:
    select_named("View notification from %s: %s" % (APP, summary))


def select_named(target: str) -> None:
    """Bounded keyboard walk to a control (Down then Up); never an unbounded loop."""
    for direction in ["Down"] * 6 + ["Up"] * 6:
        if focused_name() == target:
            return
        key(direction)
    require(focused_name() == target, "could not keyboard-select " + target)


def detail_view():
    rows = inbox()
    if rows and any(r["role"] in ("panel", "grouping") and r["name"] == "Notification from " + APP
                    for r in rows):
        return rows
    return None


def act(name: str) -> None:
    """AT-SPI doAction on the uniquely named button, once it is accessible."""
    row = wait_for(lambda: find_button(inbox() or [], name), "accessible button " + name)
    do_action(row)


def do_action(row) -> None:
    action = row["node"].queryAction()
    require(action.nActions >= 1, "accessible node exposes no action: " + row["name"])
    require(action.doAction(0), "AT-SPI doAction refused: " + row["name"])


def whole_desktop_text() -> str:
    """Every accessible name/description/text of EVERY application, for canary checks."""
    chunks = []
    for node, _ in walk(pyatspi.Registry.getDesktop(0), 0, 9):
        try:
            chunks.append(node.name or "")
            chunks.append(node.description or "")
            try:
                text = node.queryText()
                chunks.append(text.getText(0, min(text.characterCount, 4096)))
            except (NotImplementedError, LookupError, RuntimeError):
                pass
        except (LookupError, RuntimeError):
            continue
    return "\n".join(chunks)


# ------------------------------------------------------------- notifier ----
def start_mako() -> int:
    global mako
    log = open(RUNTIME / "mako.log", "ab")
    mako = subprocess.Popen(["mako", "--config", MAKO_CONFIG], stdout=log, stderr=log)
    wait_for(lambda: subprocess.run(
        ["busctl", "--user", "status", "org.freedesktop.Notifications"],
        capture_output=True).returncode == 0, "Mako claims the notification name", 10)
    return mako.pid


def stop_mako(sig=signal.SIGKILL) -> None:
    global mako
    if mako is not None and mako.poll() is None:
        mako.send_signal(sig)
        mako.wait(timeout=5)
    wait_for(lambda: subprocess.run(
        ["busctl", "--user", "status", "org.freedesktop.Notifications"],
        capture_output=True).returncode != 0, "Mako releases the notification name", 5)


def notify(summary: str, body: str = CANARY, replace: int = 0,
           actions=("open", "Open synthetic")) -> int:
    action_list = "[" + ",".join("'%s'" % item for item in actions) + "]"
    reply = subprocess.run(
        ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
         "--object-path", "/org/freedesktop/Notifications",
         "--method", "org.freedesktop.Notifications.Notify", APP, str(replace), "",
         summary, body, action_list, "{}", "120000"],
        capture_output=True, text=True, timeout=8, check=True).stdout
    match = re.search(r"uint32 (\d+)", reply)
    require(match is not None, "Notify returned no ID")
    return int(match.group(1))


def makoctl(*args: str) -> str:
    return subprocess.run(["makoctl", *args], capture_output=True, text=True,
                          timeout=8, check=True).stdout


def start_monitor() -> None:
    global monitor
    monitor = subprocess.Popen(
        ["dbus-monitor", "--session",
         "type='signal',interface='org.freedesktop.Notifications',member='ActionInvoked'"],
        stdout=open(RUNTIME / "action-monitor.log", "wb"), stderr=subprocess.DEVNULL)
    time.sleep(0.6)


def action_events() -> list[tuple[int, str]]:
    text = (RUNTIME / "action-monitor.log").read_text(errors="replace")
    return [(int(i), k) for i, k in re.findall(
        r"member=ActionInvoked\s+uint32 (\d+)\s+string \"([^\"]*)\"", text)]


def mako_rows(method: str = "ListNotifications") -> list[dict]:
    """Mako's own inventory (independent of RicePop): id, summary, body, actions."""
    reply = subprocess.run(
        ["busctl", "--user", "--json=short", "call", "org.freedesktop.Notifications",
         "/fr/emersion/Mako", "fr.emersion.Mako", method],
        capture_output=True, text=True, timeout=8, check=True).stdout
    rows = json.loads(reply)["data"][0]
    return [{"id": row["id"]["data"], "summary": row["summary"]["data"],
             "body": row["body"]["data"], "actions": row.get("actions", {}).get("data", {})}
            for row in rows]


def active_ids() -> list[int]:
    return [row["id"] for row in mako_rows()]


def recycle_id(target: int) -> None:
    """Post sequential notifications on the (new) owner until `target` is reissued
    with identical text. An ID consumed by another client shifts the sequence, so
    a filler can land on `target` (or overshoot it): the reissued row is verified
    by its text, and the owner is replaced again (bounded) until it is exact."""
    for _attempt in range(4):
        recycled = 0
        while recycled < target:
            recycled = notify("Foxtrot" if (recycled + 1 == target) else "filler")
        if recycled == target and any(
                row["id"] == target and row["summary"] == "Foxtrot" for row in mako_rows()):
            return
        stop_mako()
        start_mako()
    raise Fail("could not recycle ID %d" % target)


# --------------------------------------------------------- inbox control ----
def open_inbox() -> None:
    """Real pointer on the panel's Start button, then real keys: type-to-search."""
    subprocess.run([CLICKER, "35", "748", "1366", "768"], check=True, timeout=10)
    wait_for(lambda: any(r["role"] == "menu" and r["name"] == "RiceBowl Luna"
                         for r in snapshot()), "Start menu mapped")
    key("slash")
    wtype("notif")
    time.sleep(0.4)
    key("Return", 0.5)
    wait_for(inbox, "native RicePop inbox opened")


def shell_popup_open() -> bool:
    return any(r["role"] == "dialog" and r["name"] == "Notifications"
               or r["role"] == "menu" for r in snapshot())


def close_inbox() -> None:
    """Escape leaves a detail, then the inbox (back to the Start menu), then the menu."""
    for _ in range(4):
        if not shell_popup_open():
            return
        key("Escape", 0.6)
    wait_for(lambda: not shell_popup_open(), "native RicePop inbox and menu closed")


def capture_popup(label: str) -> bytes:
    """Pixels of the Start-menu popup column (clock/toasts are outside it)."""
    from PIL import Image
    path = RUNTIME / ("popup-%s.png" % label)
    time.sleep(0.5)
    subprocess.run(["grim", "-g", "0,272 480x456", str(path)], check=True, timeout=10)
    image = Image.open(path).convert("RGB")
    keep = os.environ.get("SG3_KEEP_DIR")
    if keep:
        image.save(Path(keep) / path.name)
    # Only the first row card: the "Past (n)" counter legitimately differs.
    return image.crop((0, 135, 480, 215)).tobytes()


# ---------------------------------------------------------- privacy scan ----
def file_inventory() -> dict[str, tuple[int, int]]:
    result = {}
    for base in {Path(os.environ["HOME"]), RUNTIME}:
        for directory, _, files in os.walk(base):
            for name in files:
                path = Path(directory) / name
                try:
                    info = path.lstat()
                except OSError:
                    continue
                if path.is_symlink() or not path.is_file():
                    continue
                result[str(path)] = (info.st_size, info.st_mtime_ns)
    return result


def files_containing(token: str) -> list[str]:
    needle = token.encode()
    hits = []
    for path in file_inventory():
        try:
            with open(path, "rb") as stream:
                if needle in stream.read(16 * 1024 * 1024):
                    hits.append(path)
        except OSError:
            continue
    return hits


# -------------------------------------------------------------- scenario ----
def scenario_luna_inbox() -> None:
    start_monitor()
    owner = start_mako()
    require_modern_mako()
    baseline = file_inventory()
    require(not files_containing(CANARY), "canary present before any notification")

    first = notify("Alpha")
    open_inbox()
    wait_for(lambda: rows_now() == ["Alpha"], "real Mako row in the native inbox")
    rows = inbox()
    alpha = find_button(rows, "View notification from %s: Alpha" % APP)
    require(alpha is not None and CANARY in (alpha["description"] or ""),
            "row exposes the body only through its accessible description")
    passed("native inbox lists a real Mako notification (AT-SPI label, body in description)")

    # Live update with the inbox open: no key, no click, no refresh request.
    second = notify("Bravo", actions=("open", "Open synthetic", "reply", "Reply synthetic"))
    wait_for(lambda: set(rows_now()) == {"Alpha", "Bravo"}, "live arrival", OPEN_REFRESH + 6)
    wait_for(lambda: tab_label() == "Active notifications: 2", "active count follows live")
    passed("live arrival while the inbox is open (no manual refresh)")
    require(notify("Bravo updated", replace=second,
                   actions=("open", "Open synthetic", "reply", "Reply synthetic")) == second,
            "Mako did not reuse the ID on replacement")
    wait_for(lambda: set(rows_now()) == {"Alpha", "Bravo updated"},
             "live same-ID replacement", OPEN_REFRESH + 6)
    require(tab_label() == "Active notifications: 2", "replacement changed the count")
    passed("live same-ID replacement drops the old row and label")
    makoctl("dismiss", "-n", str(first))
    wait_for(lambda: rows_now() == ["Bravo updated"], "live external close", OPEN_REFRESH + 6)
    require(tab_label() == "Active notifications: 1", "count after external close")
    passed("live external close removes exactly that row")

    # Fail-closed selection: the row Alpha was selected when it vanished, so
    # nothing may stay selected (focus parks on the safe Back control) and a
    # Delete must NOT retarget the surviving notification.
    require(focused_name() == "Back to menu",
            "selection did not fail closed after its row vanished: " + focused_name())
    survivors = len(active_ids())
    key("Delete", 1.0)
    require(len(active_ids()) == survivors and rows_now() == ["Bravo updated"],
            "Delete retargeted a notification after the selected row vanished")
    passed("selected row closed externally leaves no selection; Delete cannot retarget")

    # Keyboard navigation with a real compositor keyboard.
    third = notify("Charlie")
    wait_for(lambda: set(rows_now()) == {"Bravo updated", "Charlie"}, "third row",
             OPEN_REFRESH + 6)
    key("Down")
    last = focused_name()
    require(last.startswith("View notification from"), "Down did not select a row: " + last)
    key("Up")
    first = focused_name()
    require(first.startswith("View notification from") and first != last,
            "Up did not move the selection")
    key("Tab")
    require(focused_name() == last, "Tab did not select the next row")
    moved = last
    passed("Up/Down/Tab move the real keyboard selection (AT-SPI focus follows)")

    # Delete dismisses exactly the selected row.
    doomed = moved[len("View notification from %s: " % APP):]
    key("Delete", 0.5)
    wait_for(lambda: doomed not in rows_now() and len(rows_now()) == 1,
             "keyboard dismissal", OPEN_REFRESH + 6)
    require(len(active_ids()) == 1, "Mako still holds the dismissed notification")
    passed("Delete dismisses exactly the selected notification (Mako agrees)")

    # Return opens the detail; Down moves between actions; Return invokes one.
    delta = notify("Delta", actions=("open", "Open synthetic", "reply", "Reply synthetic"))
    wait_for(lambda: "Delta" in rows_now(), "multi-action row", OPEN_REFRESH + 6)
    select_row("Delta")
    key("Return", 0.6)
    detail = wait_for(detail_view, "native detail view")
    labels = [r["name"] for r in detail if r["role"] == "label"]
    require("Delta" in labels and CANARY in labels, "detail lacks summary/body: %r" % labels)
    actions = sorted(r["name"] for r in detail if r["name"] in ("Open synthetic", "Reply synthetic"))
    require(actions == ["Open synthetic", "Reply synthetic"], "detail action labels: %r" % actions)
    # Mako's action map is unordered, so assert reachability, not position.
    visited = {focused_name()}
    key("Down")
    visited.add(focused_name())
    key("Up")
    visited.add(focused_name())
    require(visited == {"Open synthetic", "Reply synthetic"},
            "Up/Down did not move between the two actions: %r" % visited)
    select_named("Reply synthetic")
    before = len(action_events())
    key("Return", 0.5)
    wait_for(lambda: len(action_events()) == before + 1, "real ActionInvoked", 6)
    require(action_events()[-1][1] == "reply", "wrong action key invoked")
    passed("keyboard action invoke emits exactly one real ActionInvoked for the selected key")

    # The same operations through the PUBLIC accessibility API (what a screen
    # reader or switch device calls), not the keyboard.
    key("Escape", 0.5)  # leave the detail, back to the list
    echo = notify("Echo")
    wait_for(lambda: "Echo" in rows_now(), "Echo row", OPEN_REFRESH + 6)
    act("View notification from %s: Echo" % APP)
    detail = wait_for(detail_view, "detail opened by AT-SPI doAction")
    before = len(action_events())
    act("Open synthetic")
    wait_for(lambda: len(action_events()) == before + 1, "ActionInvoked via AT-SPI", 6)
    require(action_events()[-1] == (echo, "open"), "AT-SPI invoke used the wrong ID/key")
    passed("AT-SPI doAction opens the detail and invokes the labelled action (one ActionInvoked)")
    act("Dismiss selected notification")
    wait_for(lambda: echo not in active_ids(), "AT-SPI dismissal reaches Mako", 8)
    wait_for(lambda: "Echo" not in rows_now() and detail_view() is None,
             "dismissed row and its detail disappear", OPEN_REFRESH + 6)
    passed("AT-SPI doAction dismisses exactly the selected notification")

    # Rendered-text fallback: Tifinagh is outside the native font. The
    # accessible name keeps the true text, the pixels must show the visible
    # replacement glyphs (same pixels as literal "?"), never blank space.
    script = "\u2d30\u2d63\u2d53\u2d4d"
    shots = {}
    for label, summary in (("script", script), ("question", "?" * len(script)), ("blank", ".")):
        makoctl("dismiss", "-a")
        wait_for(lambda: active_ids() == [], "Mako cleared", 5)
        close_inbox()
        notify(summary, body="", actions=())
        open_inbox()
        wait_for(lambda: rows_now() == [summary], "row for " + label, OPEN_REFRESH + 6)
        if label == "script":
            require(find_button(inbox(), "View notification from %s: %s" % (APP, script)) is not None,
                    "accessible name lost the original script")
        shots[label] = capture_popup(label)
    require(shots["script"] == shots["question"],
            "unsupported script did not render the replacement glyphs")
    require(shots["script"] != shots["blank"], "unsupported script rendered as nothing")
    passed("unsupported script: accessible text intact, pixels show the visible '?' fallback")
    makoctl("dismiss", "-a")
    close_inbox()

    # Host restart while open + stale-ID protection, end to end.
    for _ in range(2):
        notify("filler")
    target = notify("Foxtrot")
    open_inbox()
    wait_for(lambda: "Foxtrot" in rows_now(), "Foxtrot row", OPEN_REFRESH + 6)
    select_row("Foxtrot")
    key("Return", 0.6)
    wait_for(detail_view, "detail of Foxtrot before the crash")
    old_owner = mako.pid
    stop_mako()
    wait_for(lambda: any(r["name"] == "Notification host unavailable; retrying"
                         for r in inbox() or []), "unavailable status after host loss",
             OPEN_REFRESH + 6)
    require(rows_now() == [] and detail_view() is None, "rows or detail survived host loss")
    text = whole_desktop_text()
    require(CANARY not in text and "Foxtrot" not in text,
            "private text still accessible after host loss")
    passed("host SIGKILL while open: honest unavailable state, rows/detail/bodies cleared")
    new_owner = start_mako()
    require(new_owner != old_owner, "Mako was not replaced")
    require(mako_rows() == [] and mako_rows("ListHistory") == [],
            "restarted Mako carried old notifications or history")
    passed("restarted Mako starts with empty active list and in-memory-only history")
    # Recycle the numeric ID with identical text on the NEW owner.
    recycle_id(target)
    # Only three rows fit the list; keep the recycled ID the sole row so the
    # fresh selection below cannot depend on Mako's listing order.
    for filler_id in active_ids():
        if filler_id != target:
            makoctl("dismiss", "-n", str(filler_id))
    events = len(action_events())
    key("Return", 1.0)   # stale selection must not reach the new owner
    key("Delete", 1.0)
    time.sleep(1.5)
    require(len(action_events()) == events, "stale native selection invoked on the new owner")
    require(target in active_ids(), "stale native selection dismissed on the new owner")
    passed("recycled ID + identical text on a new owner: stale Return/Delete reach nothing")
    key("r", 1.0)  # explicit refresh authorizes the new owner's rows
    wait_for(lambda: "Foxtrot" in rows_now(), "new owner rows after refresh", 8)
    select_row("Foxtrot")
    key("Return", 0.6)
    wait_for(detail_view, "fresh detail on the new owner")
    key("Return", 0.5)
    wait_for(lambda: len(action_events()) == events + 1, "fresh invoke on the new owner", 6)
    require(action_events()[-1] == (target, "open"), "fresh invoke hit the wrong target")
    passed("after refresh + fresh selection the new owner's action works exactly once")

    # Privacy: leaving the inbox clears bodies; nothing private reaches disk.
    close_inbox()
    require(CANARY not in whole_desktop_text(), "body still accessible after closing the inbox")
    passed("closing the inbox removes every private body from the accessibility tree")
    leaked = files_containing(CANARY)
    require(not leaked, "private text persisted in %d file(s)" % len(leaked))
    created = sorted(set(file_inventory()) - set(baseline))
    harness = {str(RUNTIME / name) for name in
               ("labwc.log", "native.log", "mako.log", "action-monitor.log",
                "keeper.log", "keyboard-keeper.log")}
    suspicious = [path for path in created if path not in harness and re.search(
        r"notif|ricepop|history|mako|inbox", path, re.I)]
    require(not suspicious, "unexpected notification-related files: %r" % suspicious)
    passed("no private text and no notification state files on disk (HOME, XDG, runtime scanned)")


# ------------------------------------------------------------------ OSD ----
OSD_GEOM = "1102,16 248x68"   # top-right 248x68 layer surface, 16 px margins
OSD_BAR_ROW = 56              # bar row inside the OSD (osd.rs paint_osd)
OSD_BAR_PIXELS = 216          # width - 32
osd_blank = None
osd_shots: dict[str, object] = {}


def audio_event(level, muted: bool = False, event: str = "Event 'change' on sink #0") -> None:
    """Change the private default sink and wake the pactl-subscribe observer."""
    volume = AUDIO / "volume"
    if level is None:
        volume.unlink(missing_ok=True)
    else:
        temporary = AUDIO / "volume.new"
        temporary.write_text("Volume: %.2f%s\n" % (level, " [MUTED]" if muted else ""))
        os.replace(temporary, volume)
    if event:
        with open(AUDIO / "events", "a") as stream:
            stream.write(event + "\n")


def osd_image(label: str = ""):
    from PIL import Image
    path = RUNTIME / "osd.png"
    subprocess.run(["grim", "-g", OSD_GEOM, str(path)], check=True, timeout=10)
    image = Image.open(path).convert("RGB")
    image.load()
    keep = os.environ.get("SG3_KEEP_DIR")
    if keep and label:
        image.save(Path(keep) / ("osd-%s-%s.png" % (RICE, label)))
    return image


def changed_pixels(first, second, box=None) -> int:
    from PIL import ImageChops
    if box is not None:
        first, second = first.crop(box), second.crop(box)
    return sum(max(px) > 20 for px in ImageChops.difference(first, second).getdata())


def osd_visible(image) -> bool:
    """The OSD signature: a full-height accent stripe and an opaque, uniform body.

    (A blank-screen comparison is not usable: other shell surfaces such as the
    desktop or a restarted panel legitimately change pixels in this corner.)
    """
    stripe = {image.getpixel((x, y)) for x in range(0, 4) for y in range(4, 64)}
    if len(stripe) != 1:
        return False
    body = image.getpixel((8, 5))
    return body == image.getpixel((240, 5)) == image.getpixel((8, 40)) and body not in stripe


def osd_fill(image) -> int:
    """Filled bar pixels (of 216) read back from the real compositor output."""
    y = OSD_BAR_ROW
    left = image.getpixel((16, y))
    if left == image.getpixel((1, 30)):   # accent-coloured bar: nothing filled
        return 0
    count, x = 0, 16
    while x < image.size[0] - 16 and image.getpixel((x, y)) == left:
        count += 1
        x += 1
    return count


def osd_wait(visible: bool, message: str, timeout: float = 4.0, label: str = ""):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        image = osd_image(label)
        if osd_visible(image) == visible:
            return image
        time.sleep(0.1)
    raise Fail("timeout: " + message)


def osd_stays_absent(message: str, seconds: float = 1.4) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        image = osd_image()
        if osd_visible(image):
            osd_image("unexpected")
            raise Fail("OSD appeared: " + message)
        time.sleep(0.15)


def osd_wait_fill(expected: int, message: str, timeout: float = 4.0, label: str = ""):
    deadline = time.monotonic() + timeout
    image = None
    while time.monotonic() < deadline:
        image = osd_image(label)
        if osd_visible(image) and abs(osd_fill(image) - expected) <= 2:
            return image
        time.sleep(0.1)
    raise Fail("timeout: %s (last fill %s)" % (message, osd_fill(image) if image else None))


def osd_matrix() -> None:
    """Live volume OSD from an external sink change: value, update, expiry, negatives."""
    global osd_blank
    osd_blank = osd_image("blank")
    audio_event(0.50, event="")           # level moves, no event: nothing may appear
    osd_stays_absent("with no observer event")
    audio_event(0.50)                     # first real event at an unchanged level
    osd_stays_absent("for an unchanged level")
    passed("%s OSD: idle panel and an unchanged-level event show nothing" % RICE)

    audio_event(0.80)
    osd_shots["80"] = osd_wait_fill(172, "OSD 80% bar", label="v80")
    audio_event(0.20)
    osd_shots["20"] = osd_wait_fill(43, "OSD updates live to 20%", label="v20")
    require(changed_pixels(osd_shots["80"], osd_shots["20"], (16, 27, 232, 46)) > 8,
            "OSD value text did not change with the level")
    passed("%s OSD: external volume change shows value+bar (80%%->20%%) with no input" % RICE)
    after = osd_wait(False, "OSD expiry", 4.0)
    require(changed_pixels(after, osd_blank) < 100, "OSD left pixels behind after expiry")
    passed("%s OSD: expires by itself (1.8 s) and restores the screen" % RICE)

    audio_event(0.20)                     # duplicate level
    osd_stays_absent("for a duplicate readback")
    audio_event(0.30, event="Event 'change' on source #3")   # unrelated device
    osd_stays_absent("for a non-sink event")
    audio_event(0.30)                     # the earlier level change was never read
    osd_wait_fill(64, "OSD shows 30% only after a sink event", label="v30")
    passed("%s OSD negatives: duplicate level and non-sink events show nothing" % RICE)
    osd_wait(False, "OSD expiry", 4.0)

    audio_event(0.30, muted=True)
    osd_shots["muted"] = osd_wait(True, "muted OSD", label="muted")
    require(osd_fill(osd_shots["muted"]) == 0, "muted OSD still shows a filled bar")
    require(changed_pixels(osd_shots["muted"], osd_shots["20"], (16, 27, 232, 46)) > 20,
            "muted OSD shows the same value text as a level")
    osd_wait(False, "OSD expiry", 4.0)
    audio_event(None)                     # provider unavailable
    osd_stays_absent("for an unavailable provider")
    audio_event(0.55)                     # recovery from unavailable
    osd_stays_absent("on recovery from unavailable")
    audio_event(0.45)
    osd_wait_fill(97, "OSD shows again after the provider recovered", label="v45")
    passed("%s OSD: Muted state, unavailable provider never flashes, live again after recovery" % RICE)
    osd_wait(False, "OSD expiry", 4.0)


def osd_keyboard_transparency() -> None:
    """The OSD must not take focus: keys still reach the open inbox beneath it."""
    notify("Kilo")
    notify("Lima")
    open_inbox()
    wait_for(lambda: {"Kilo", "Lima"} <= set(rows_now()), "two rows before the OSD", OPEN_REFRESH + 6)
    key("Down")
    before = focused_name()
    require(before.startswith("View notification from"), "no row selected before the OSD")
    audio_event(0.70)
    osd_wait(True, "OSD above the open inbox", label="over-inbox")
    require(focused_name() == before, "the OSD changed the keyboard focus")
    key("Down", 0.3)
    require(osd_visible(osd_image()), "OSD expired before the key was observed")
    moved = focused_name()
    require(moved.startswith("View notification from") and moved != before,
            "Down did not reach the inbox while the OSD was visible: %r" % moved)
    require(inbox() is not None, "inbox closed by the OSD")
    passed("OSD over the open inbox: focus unchanged, real Down key still moves the inbox selection")
    osd_wait(False, "OSD expiry", 4.0)
    makoctl("dismiss", "-a")
    close_inbox()


def ink_extent(image, box) -> int:
    """Width of the painted (non-background) text inside a crop of the OSD."""
    crop = image.crop(box)
    background = crop.getpixel((0, 0))
    columns = [x for x in range(crop.size[0])
               if any(crop.getpixel((x, y)) != background for y in range(crop.size[1]))]
    return (columns[-1] - columns[0] + 1) if columns else 0


def osd_german() -> None:
    """Panel started with LC_ALL=de_DE: OSD labels are German; value and bar are readback."""
    global osd_blank
    osd_blank = osd_image("de-blank")
    osd_stays_absent("on a freshly started panel (initial sink reading)", 1.5)
    audio_event(0.80)
    german = osd_wait_fill(172, "German OSD 80%", label="de80")
    title, value = (16, 6, 232, 26), (16, 27, 232, 46)
    # English "Volume" measures 37 px in the Luna face, "Lautst\u00e4rke" 51 px.
    width = ink_extent(german, title)
    require(width >= 46, "OSD title is not the German 'Lautst\u00e4rke' (ink width %d)" % width)
    require(ink_extent(german, value) <= 40, "OSD value is not just the readback percentage")
    osd_wait(False, "OSD expiry", 4.0)
    audio_event(0.80, muted=True)
    muted = osd_wait(True, "German muted OSD", label="de-muted")
    require(osd_fill(muted) == 0, "muted OSD shows a filled bar")
    require(changed_pixels(muted, german, title) < 10, "German title differs between states")
    require(changed_pixels(muted, german, value) > 20, "German 'Stumm' not rendered")
    passed("German locale: OSD title is translated (fresh panel shows no OSD), value and bar are readback")
    osd_wait(False, "OSD expiry", 4.0)



# ------------------------------------------ OSD: announcement, brightness ----
BACKLIGHT = Path(os.environ["SG3_BACKLIGHT_DIR"]) / "panel" if os.environ.get("SG3_BACKLIGHT_DIR") else None
OSD_NAME = re.compile(r"^(Volume|Brightness|Lautst\u00e4rke|Helligkeit): ")


def osd_nodes() -> list[dict]:
    """Accessible nodes of the panel whose name is OSD text (Volume:/Brightness:)."""
    found = []
    for row in snapshot():
        if not OSD_NAME.match(row["name"] or ""):
            continue
        try:
            attributes = dict(a.split(":", 1) for a in row["node"].getAttributes() if ":" in a)
        except (LookupError, RuntimeError):
            attributes = {}
        found.append(dict(row, attributes=attributes))
    return found


def osd_node_named(name: str, timeout: float = 4.0):
    return wait_for(lambda: next((n for n in osd_nodes() if n["name"] == name), None),
                    "accessible OSD node %r" % name, timeout, 0.1)


def a11y_monitor(log: Path) -> subprocess.Popen:
    """Black-box listener on the accessibility bus for AT-SPI `Announcement` signals,
    the event a screen reader speaks for a live region (no cooperation from the app)."""
    address = subprocess.run(
        ["dbus-send", "--session", "--print-reply", "--dest=org.a11y.Bus", "/org/a11y/bus",
         "org.a11y.Bus.GetAddress"], capture_output=True, text=True, timeout=8,
        check=True).stdout.split('"')[1]
    process = subprocess.Popen(
        ["dbus-monitor", "--address", address,
         "type='signal',interface='org.a11y.atspi.Event.Object',member='Announcement'"],
        stdout=open(log, "wb"), stderr=subprocess.DEVNULL)
    time.sleep(0.6)
    return process


def announcements(log: Path) -> list[tuple[str, int]]:
    """(spoken text, politeness) of every Announcement seen so far, oldest first."""
    text = log.read_text(errors="replace") if log.exists() else ""
    found = []
    for block in text.split("signal ")[1:]:
        if "member=Announcement" not in block:
            continue
        strings = re.findall(r'string "([^"]*)"', block)
        integers = re.findall(r"int32 (-?\d+)", block)
        spoken = next((t for t in strings if OSD_NAME.match(t)), None)
        if spoken is not None:
            found.append((spoken, int(integers[0]) if integers else -1))
    return found


def osd_announcement() -> None:
    """The OSD is exposed over AT-SPI exactly while it is painted (status role, live)."""
    require(osd_nodes() == [], "an OSD node exists although nothing is shown")
    osd_wait(False, "no OSD before the announcement check", 3.0)
    audio_event(0.55)
    node = osd_node_named("Volume: 55%")
    osd_wait(True, "OSD painted while announced")
    require(node["role"] == "status bar",
            "volume OSD is exposed as %r, not a status node" % node["role"])
    require(len(osd_nodes()) == 1, "more than one OSD node: %r" % [n["name"] for n in osd_nodes()])
    passed("%s OSD announcement: a 'status bar' node 'Volume: 55%%' exists on the accessibility bus "
           "exactly while the OSD is painted" % RICE)
    audio_event(0.25)
    osd_node_named("Volume: 25%")
    require(len(osd_nodes()) == 1, "the update left a stale OSD node")
    passed("%s OSD announcement: a level change updates the one node to 'Volume: 25%%'" % RICE)
    audio_event(0.25, muted=True)
    osd_node_named("Volume: Muted")
    wait_for(lambda: osd_nodes() == [], "OSD node removed after expiry", 4.0, 0.1)
    require(not osd_visible(osd_image()), "OSD still painted after its node was removed")
    passed("%s OSD announcement: 'Volume: Muted' is announced, and the node leaves the tree when the OSD expires" % RICE)


def osd_announcement_events() -> None:
    """An assistive technology is TOLD (Announcement events), not only able to poll the tree."""
    log = RUNTIME / "a11y-announcements.log"
    log.unlink(missing_ok=True)
    listener = a11y_monitor(log)
    try:
        audio_event(0.65)
        wait_for(lambda: ("Volume: 65%", 1) in announcements(log),
                 "polite 'Volume: 65%' Announcement on the accessibility bus", 5, 0.1)
        osd_node_named("Volume: 65%")
        audio_event(0.15)
        wait_for(lambda: announcements(log)[-1:] == [("Volume: 15%", 1)],
                 "a level change while the OSD is up is announced again", 5, 0.1)
        got = announcements(log)
        require(got == [("Volume: 65%", 1), ("Volume: 15%", 1)],
                "unexpected Announcement sequence: %r" % got)
        osd_wait(False, "OSD expiry", 4.0)
        time.sleep(0.8)
        require(announcements(log) == got, "an expiring OSD announced something")
    finally:
        listener.terminate()
        listener.wait(timeout=5)
    passed("%s OSD announcement: an external listener on the AT-SPI bus receives a polite live "
           "Announcement ('Volume: 65%%', then '15%%' on update); expiry announces nothing"
           % RICE)


def write_backlight(value) -> None:
    temporary = BACKLIGHT.parent / "brightness.new"
    temporary.write_text(str(value) + "\n")
    os.replace(temporary, BACKLIGHT / "brightness")


def osd_brightness() -> None:
    """Live backlight readback (sysfs fixture tree; this host has no panel backlight)."""
    require(BACKLIGHT is not None, "SG3_BACKLIGHT_DIR missing")
    log = RUNTIME / "a11y-brightness.log"
    log.unlink(missing_ok=True)
    listener = a11y_monitor(log)
    try:
        osd_wait(False, "idle before brightness", 3.0)
        osd_stays_absent("for the initial backlight reading and an unchanged level", 1.8)
        write_backlight(500)
        osd_stays_absent("when the same value is written again", 1.8)
        write_backlight(800)
        shot = osd_wait_fill(173, "Brightness OSD 80% bar", 5.0, "b80")
        osd_node_named("Brightness: 80%")
        wait_for(lambda: ("Brightness: 80%", 1) in announcements(log),
                 "polite 'Brightness: 80%' Announcement", 5, 0.1)
        passed("%s brightness OSD: an external backlight change shows 'Brightness: 80%%' (bar %d/216 px "
               "read from compositor pixels, AT-SPI status node, polite Announcement)"
               % (RICE, osd_fill(shot)))
        write_backlight(200)
        updated = osd_wait_fill(43, "Brightness OSD updates live to 20%", 5.0, "b20")
        osd_node_named("Brightness: 20%")
        require(changed_pixels(shot, updated, (16, 27, 232, 46)) > 8, "value text did not change")
        passed("%s brightness OSD: live update 80%% -> 20%% (pixels and AT-SPI name)" % RICE)
        osd_wait(False, "brightness OSD expiry", 4.0)
        require(osd_nodes() == [], "brightness node outlived the OSD")
        (BACKLIGHT / "brightness").write_text("not-a-number\n")
        osd_stays_absent("for an unreadable brightness value", 2.0)
        write_backlight(1001)
        osd_stays_absent("for an out-of-range value (above max_brightness)", 2.0)
        write_backlight(300)
        osd_wait_fill(65, "Brightness OSD recovers after bad readings", 5.0, "b30")
        passed("%s brightness OSD negatives: unreadable and out-of-range readings show nothing; "
               "it recovers on the next valid change" % RICE)
        osd_wait(False, "brightness OSD expiry", 4.0)
        # End to end like the hardware key: labwc runs the shipped
        # `brightnessctl --class=backlight set 5%+`, the (shim) backlight moves,
        # and the panel reads the new level back. 30% -> 35% -> 40%.
        calls = Path(os.environ["SG3_BACKLIGHT_DIR"]) / "calls.log"
        calls.unlink(missing_ok=True)
        key("XF86MonBrightnessUp", 0.3)
        osd_wait_fill(76, "Brightness OSD after the real XF86MonBrightnessUp key", 5.0, "bkey1")
        osd_node_named("Brightness: 35%")
        osd_wait(False, "brightness OSD expiry", 4.0)
        key("XF86MonBrightnessUp", 0.3)
        osd_node_named("Brightness: 40%")
        osd_wait(False, "brightness OSD expiry", 4.0)
        key("XF86MonBrightnessDown", 0.3)
        osd_wait_fill(76, "Brightness OSD after XF86MonBrightnessDown", 5.0, "bkey2")
        osd_node_named("Brightness: 35%")
        require(calls.read_text().splitlines() == [
            "brightnessctl --class=backlight set 5%+",
            "brightnessctl --class=backlight set 5%+",
            "brightnessctl --class=backlight set 5%-"], "unexpected brightnessctl calls: %r"
            % calls.read_text())
        passed("%s brightness OSD end to end: real XF86MonBrightnessUp/Down keys -> labwc -> "
               "brightnessctl (shim) -> sysfs level -> OSD 35%%/40%%/35%%" % RICE)
        osd_wait(False, "brightness OSD expiry", 4.0)
    finally:
        listener.terminate()
        listener.wait(timeout=5)


# Inside the 248x68 OSD at (1102,16) and clear of the pixels osd_visible() samples
# (the real pointer image is composited into grim frames).
POINTS = ((1226, 50), (1160, 40), (1300, 60))


def osd_pointer_passthrough() -> None:
    """A real click inside the OSD area reaches the window beneath (empty input region)."""
    ready, log = RUNTIME / "click-target.ready", RUNTIME / "click-target.log"
    for path in (ready, log):
        path.unlink(missing_ok=True)
    env = dict(os.environ, GDK_BACKEND="wayland")
    target = subprocess.Popen(
        ["/usr/bin/python3", str(ROOT / "scripts/sg3_click_target.py"), str(ready), str(log)],
        env=env, stdout=open(RUNTIME / "click-target.out", "ab"), stderr=subprocess.STDOUT)
    try:
        wait_for(ready.exists, "fullscreen click target mapped", 20)
        osd_wait(False, "OSD idle before the click test", 4.0)

        def clicks() -> list[tuple[int, int]]:
            return [tuple(map(int, line.split())) for line in
                    (log.read_text().splitlines() if log.exists() else [])]

        subprocess.run([CLICKER, "400", "400", "1366", "768"], check=True, timeout=10)
        wait_for(lambda: clicks() == [(400, 400)], "control click reaches the window", 5)
        # OSD area: 248x68 at (1102,16). Keep it alive with a changing level.
        results = []
        for index, (x, y) in enumerate(POINTS):
            audio_event(0.30 + index * 0.1)
            osd_wait(True, "OSD painted before the click %d" % index)
            subprocess.run([CLICKER, str(x), str(y), "1366", "768"], check=True, timeout=10)
            still = osd_visible(osd_image("click%d" % index))
            results.append(still)
            expected = [(400, 400)] + list(POINTS[:index + 1])
            wait_for(lambda e=expected: clicks() == e, "click inside the OSD reaches the window", 5)
            osd_wait(False, "OSD expiry", 4.0)
        require(all(results), "the OSD was not painted at the moment of a click: %r" % results)
        passed("%s OSD pointer pass-through: real clicks at three points inside the painted OSD "
               "(centre, left, right of the bar row) reach the fullscreen window beneath" % RICE)
    finally:
        target.terminate()
        try:
            target.wait(timeout=5)
        except subprocess.TimeoutExpired:
            target.kill()

# ----------------------------------------------- rendered text / localization ----
SCRIPTS = {
    "hindi": ("हिन्दी", "??"),
    "cjk": ("日本語", "???"),
    "arabic": ("مرحبا", "?????"),
    "hangul": ("한국어", "???"),
}


def show_only(summary: str, body: str = "", actions=()) -> None:
    """Exactly one active notification, listed in the (already open) inbox."""
    makoctl("dismiss", "-a")
    wait_for(lambda: active_ids() == [], "Mako cleared", 5)
    notify(summary, body=body, actions=actions)
    key("r", 0.5)
    wait_for(lambda: rows_now() == [summary], "row for " + summary, OPEN_REFRESH + 6)


def script_shots(replacement_too: bool) -> dict:
    shots = {}
    close_inbox()
    notify(".", body="", actions=())
    open_inbox()
    for name, (text, replacement) in SCRIPTS.items():
        show_only(text)
        row = find_button(inbox(), "View notification from %s: %s" % (APP, text))
        require(row is not None, "accessible name lost the %s text" % name)
        shots[(name, "script")] = capture_popup(name)
        if replacement_too:
            show_only(replacement)
            shots[(name, "question")] = capture_popup(name + "-q")
    show_only(".")
    shots["blank"] = capture_popup("blank")
    return shots


def script_matrix_positive() -> dict:
    shots = script_shots(True)
    for name in SCRIPTS:
        require(shots[(name, "script")] != shots[(name, "question")],
                "%s drew the replacement glyphs although the system font is installed" % name)
        require(shots[(name, "script")] != shots["blank"], "%s rendered as nothing" % name)
    passed("inbox rows: Hindi, CJK, Arabic and Hangul render real glyphs (not '?', not blank); "
           "AT-SPI keeps the exact text")
    return shots


def script_matrix_negative() -> None:
    """System fonts hidden (kill switch only): one visible '?' per grapheme, never blank."""
    shots = script_shots(True)
    for name in SCRIPTS:
        require(shots[(name, "script")] == shots[(name, "question")],
                "%s without fonts is not the visible '?' replacement" % name)
        require(shots[(name, "script")] != shots["blank"], "%s vanished without fonts" % name)
    passed("negative: system fonts hidden -> every script shows one visible '?' per grapheme, never blank")
    makoctl("dismiss", "-a")
    close_inbox()


def detail_cjk_wrap() -> None:
    """A full CJK body wraps inside the popup (regression: the tail ran off the edge)."""
    from PIL import Image
    body = "日本語のテキストです。" * 6
    close_inbox()
    notify("Wrap", body=body, actions=("open", "Open synthetic"))
    open_inbox()
    wait_for(lambda: "Wrap" in rows_now(), "Wrap row", OPEN_REFRESH + 6)
    select_row("Wrap")
    key("Return", 0.6)
    detail = wait_for(detail_view, "detail with a CJK body")
    labels = [r["name"] for r in detail if r["role"] == "label"]
    require(body in labels, "AT-SPI detail lost part of the CJK body")
    time.sleep(0.5)
    path = RUNTIME / "popup-wrap.png"
    subprocess.run(["grim", "-g", "0,272 480x456", str(path)], check=True, timeout=10)
    image = Image.open(path).convert("RGB")
    keep = os.environ.get("SG3_KEEP_DIR")
    if keep:
        image.save(Path(keep) / path.name)
    margin = {image.getpixel((x, y)) for x in range(466, 480) for y in range(100, 215)}
    text = {image.getpixel((x, y)) for x in range(14, 300) for y in range(100, 215)}
    require(len(text) > 1, "no body text painted in the detail view")
    require(len(margin) == 1, "CJK body text runs into the popup's right edge: %d colours" % len(margin))
    passed("detail view: a CJK body wraps inside the popup, full text intact in AT-SPI")
    makoctl("dismiss", "-a")
    close_inbox()


# ------------------------------------------------------------ GTK inbox ----
GTK_APP = "launcher.py"


def gsnap() -> list[dict]:
    return snapshot(GTK_APP, 10)


def gfind(name: str, role: str = "push button"):
    matches = [r for r in gsnap() if r["role"] == role and r["name"] == name]
    return matches[0] if len(matches) == 1 else None


def gnames(prefix: str) -> list[str]:
    return [r["name"][len(prefix):] for r in gsnap()
            if r["role"] == "push button" and r["name"].startswith(prefix)]


def launch_gtk(**environment: str) -> None:
    global gtk
    stop_gtk()
    env = dict(os.environ)
    env.update(environment)
    gtk = subprocess.Popen(["ricebowl", "de", "settings", "--page", "notifications"], env=env,
                           stdout=open(RUNTIME / "gtk.log", "ab"), stderr=subprocess.STDOUT)
    wait_for(lambda: any(r["role"] == "frame" and "RiceSpice" in r["name"] for r in gsnap()),
             "RiceSpice window on the accessibility bus", 20)


def stop_gtk() -> None:
    global gtk
    if gtk is not None and gtk.poll() is None:
        gtk.terminate()
        try:
            gtk.wait(timeout=5)
        except subprocess.TimeoutExpired:
            gtk.kill()
    gtk = None


def gtk_do(name: str, role: str = "push button") -> None:
    row = wait_for(lambda: gfind(name, role), "accessible control " + name)
    do_action(row)


def gtk_text() -> str:
    return "\n".join(r["name"] or "" for r in gsnap())


def scenario_chrome() -> None:
    start_monitor()
    owner = start_mako()
    require_modern_mako()
    baseline = file_inventory()
    require(not files_containing(CANARY), "canary present before any notification")

    # Chrome's native panel has no Notifications entry by design: its inbox is
    # the RiceSpice page. Assert that honestly instead of claiming one.
    panel = wait_for(snapshot, "Chrome native panel on the accessibility bus")
    require(not any("notif" in (r["name"] or "").lower() for r in panel),
            "the Chrome panel unexpectedly offers a notification entry")
    require(inbox() is None, "a native inbox exists on the Chrome panel")
    passed("chrome: the native panel exposes no inbox entry (RiceSpice is its inbox)")

    osd_matrix()
    osd_announcement()
    osd_announcement_events()
    osd_brightness()
    osd_pointer_passthrough()

    first = notify("Alpha")
    launch_gtk()
    gtk_do("Show RicePop inbox")
    prefix = "Dismiss notification from %s: " % APP
    wait_for(lambda: gnames(prefix) == ["Alpha"], "real Mako row in the GTK inbox", 10)
    require(any(r["role"] == "label" and r["name"] == "%s · Alpha" % APP for r in gsnap()),
            "row heading missing")
    require(CANARY in gtk_text(), "row body missing while the inbox is open")
    passed("chrome RiceSpice inbox lists a real Mako notification (AT-SPI label, body, named buttons)")

    second = notify("Bravo", actions=("open", "Open synthetic", "reply", "Reply synthetic"))
    wait_for(lambda: set(gnames(prefix)) == {"Alpha", "Bravo"}, "live arrival", 10)
    passed("chrome inbox: live arrival with the page open (no refresh)")
    require(notify("Bravo updated", replace=second,
                   actions=("open", "Open synthetic", "reply", "Reply synthetic")) == second,
            "Mako did not reuse the ID")
    wait_for(lambda: set(gnames(prefix)) == {"Alpha", "Bravo updated"}, "live replacement", 10)
    passed("chrome inbox: same-ID replacement drops the old row")
    makoctl("dismiss", "-n", str(first))
    wait_for(lambda: gnames(prefix) == ["Bravo updated"], "live external close", 10)
    passed("chrome inbox: external close removes exactly that row")

    # AT-SPI doAction on the labelled action button (what a screen reader or
    # switch device calls). Keyboard traversal of this GTK page is an OPEN
    # item: a real `wtype -k Tab`/Return is not delivered to GTK3 toplevels in
    # this harness (verified with a plain two-button Gtk.Window as well).
    reply = "Reply synthetic notification from %s: Bravo updated" % APP
    before = len(action_events())
    gtk_do(reply)
    wait_for(lambda: len(action_events()) == before + 1, "real ActionInvoked", 8)
    require(action_events()[-1] == (second, "reply"), "wrong notification/action invoked")
    passed("chrome inbox: AT-SPI doAction on the labelled action emits exactly one real ActionInvoked")
    makoctl("dismiss", "-a")   # Mako keeps an invoked notification unless it is told to close
    wait_for(lambda: gnames(prefix) == [] and active_ids() == [], "all closed", 10)

    charlie = notify("Charlie")
    wait_for(lambda: gnames(prefix) == ["Charlie"], "Charlie row", 10)
    gtk_do(prefix + "Charlie")
    wait_for(lambda: charlie not in active_ids() and gnames(prefix) == [], "AT-SPI dismissal", 10)
    passed("chrome inbox: AT-SPI doAction on Dismiss closes exactly that notification")
    # Host SIGKILL while open, recycled ID with identical text on the new owner.
    for _ in range(2):
        notify("filler")
    target = notify("Foxtrot")
    wait_for(lambda: "Foxtrot" in gnames(prefix), "Foxtrot row", 10)
    stale = wait_for(lambda: gfind("Open synthetic notification from %s: Foxtrot" % APP),
                     "Foxtrot action control")["node"]
    old_owner = mako.pid
    stop_mako()
    wait_for(lambda: any(r["role"] == "label" and
                         r["name"].startswith("RicePop notification host disconnected")
                         for r in gsnap()), "disconnected state after host loss", 12)
    require(gnames(prefix) == [], "rows survived host loss")
    require(CANARY not in whole_desktop_text() and "Foxtrot" not in gtk_text(),
            "private text still accessible after host loss")
    passed("chrome inbox: host SIGKILL -> disconnected state, rows and bodies gone from AT-SPI")
    new_owner = start_mako()
    require(new_owner != old_owner, "Mako was not replaced")
    recycle_id(target)
    events = len(action_events())
    try:   # the old owner's control must be dead, not merely hidden
        action = stale.queryAction()
        action.doAction(0)
    except Exception:
        pass
    time.sleep(1.0)
    require(len(action_events()) == events and target in active_ids(),
            "a stale control reached the new owner's notification")
    passed("chrome inbox: recycled ID + identical text on a new owner: the old owner's control reaches nothing")
    wait_for(lambda: "Foxtrot" in gnames(prefix), "new owner rows", 12)
    gtk_do("Open synthetic notification from %s: Foxtrot" % APP)
    wait_for(lambda: len(action_events()) == events + 1, "fresh invoke on the new owner", 8)
    require(action_events()[-1] == (target, "open"), "fresh invoke hit the wrong target")
    passed("chrome inbox: after the owner is re-verified the new owner's action works exactly once")

    # Leaving the page removes every private body from the accessibility tree.
    notify("Hotel")
    wait_for(lambda: "Hotel" in gnames(prefix), "Hotel row", 10)
    require(CANARY in gtk_text(), "body not accessible while open")
    gtk_do("RiceSpice Network settings", "toggle button")
    wait_for(lambda: CANARY not in whole_desktop_text() and gnames(prefix) == [],
             "private bodies leave the tree on navigation", 8)
    passed("chrome inbox: leaving the page clears every private body from the accessibility tree")

    # German accessible names on the real GTK controls (separate window).
    makoctl("dismiss", "-a")
    notify("Golf")
    launch_gtk(LC_ALL="de_DE.UTF-8")
    gtk_do("RicePop-Posteingang anzeigen")
    german = "Schließen – Benachrichtigung von %s: Golf" % APP
    wait_for(lambda: gfind(german) is not None, "German accessible dismiss name", 10)
    wait_for(lambda: gfind("Open synthetic – Benachrichtigung von %s: Golf" % APP) is not None,
             "German accessible action name", 10)
    require(gfind("Dismiss notification from %s: Golf" % APP) is None, "English name leaked")
    passed("chrome inbox: German locale gives German accessible names; the app's own action label is untouched")
    stop_gtk()

    leaked = files_containing(CANARY)
    require(not leaked, "private text persisted in %d file(s)" % len(leaked))
    created = sorted(set(file_inventory()) - set(baseline))
    harness = {str(RUNTIME / name) for name in (
        "labwc.log", "native.log", "mako.log", "action-monitor.log", "keeper.log",
        "keyboard-keeper.log", "gtk.log", "osd.png", "native-restart.log")}
    suspicious = [path for path in created if path not in harness and re.search(
        r"notif|ricepop|history|mako|inbox", path, re.I)]
    require(not suspicious, "unexpected notification-related files: %r" % suspicious)
    passed("chrome: no private text and no notification state files on disk (HOME, XDG, runtime scanned)")


def scenario_luna() -> None:
    scenario_luna_inbox()
    osd_matrix()
    osd_keyboard_transparency()
    osd_announcement()
    osd_announcement_events()
    osd_brightness()
    detail_cjk_wrap()
    script_matrix_positive()
    osd_pointer_passthrough()
    leaked = files_containing(CANARY)
    require(not leaked, "private text persisted in %d file(s)" % len(leaked))
    passed("luna: no private text on disk after the OSD and localization phases either")


def osd_brightness_german() -> None:
    """German locale: the brightness OSD and its accessible/announced text are German."""
    osd_wait(False, "idle before the German brightness OSD", 4.0)
    write_backlight(500)
    osd_stays_absent("for the initial backlight reading", 1.5)
    write_backlight(800)
    osd_wait_fill(173, "German brightness OSD 80%", 5.0, "de-b80")
    osd_node_named("Helligkeit: 80%")
    require(not any(n["name"].startswith("Brightness") for n in osd_nodes()),
            "an English accessible name leaked")
    passed("German locale: brightness OSD reads 'Helligkeit: 80%' (accessible name), bar from readback")
    osd_wait(False, "brightness OSD expiry", 4.0)


def scenario_luna_de() -> None:
    start_mako()
    require_modern_mako()
    osd_german()
    osd_brightness_german()


def scenario_luna_nofonts() -> None:
    start_mako()
    require_modern_mako()
    script_matrix_negative()


def require_modern_mako() -> None:
    # Mako 1.8 never emits ActionInvoked for `makoctl invoke` (observed), so
    # these smokes' invoke receipts need the 1.11 D-Bus surface. Refuse loudly
    # rather than degrade to a weaker check.
    modern = subprocess.run(
        ["busctl", "--user", "get-property", "org.freedesktop.Notifications",
         "/fr/emersion/Mako", "fr.emersion.Mako", "Notifications"],
        capture_output=True).returncode == 0
    require(modern, "requires Mako >= 1.11 on PATH (see scripts/smoke_real_mako_111.sh)")


def main() -> int:
    try:
        {"chrome": scenario_chrome, "luna": scenario_luna, "luna-de": scenario_luna_de,
         "luna-nofonts": scenario_luna_nofonts}[os.environ.get("SG3_MODE", RICE)]()
    except Fail as failure:
        print("SG3 native RicePop smoke FAILED: %s" % failure, file=sys.stderr)
        keep = os.environ.get("SG3_KEEP_DIR")
        if keep:
            subprocess.run(["grim", str(Path(keep) / "failure-screen.png")], timeout=10)
        rows = inbox() or []
        start = next((i for i, r in enumerate(rows) if r["role"] == "dialog"), 0)
        print("accessible dialog now: %r" % [
            (r["role"], r["name"], r["focused"]) for r in rows[start:start + 24]],
            file=sys.stderr)
        return 1
    finally:
        for process in (monitor, mako, gtk):
            if process is not None and process.poll() is None:
                process.kill()
    print("SG3 native RicePop inbox: %d receipts PASS" % len(receipts))
    return 0


if __name__ == "__main__":
    sys.exit(main())

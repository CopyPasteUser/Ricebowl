#!/usr/bin/env python3
"""Scenario driver for smoke_sg3_ricepop_native_labwc.sh (SG3 WP3.1/3.2).

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
import signal
import subprocess
import sys
import time
from pathlib import Path

import pyatspi

ROOT = Path(os.environ["SG3_ROOT"])
RUNTIME = Path(os.environ["SG3_RUNTIME"])
CLICKER = os.environ["SG3_CLICKER"]
MAKO_CONFIG = os.environ["SG3_MAKO_CONFIG"]
APP = "SG3 Native"
# Private-text canaries: they must be visible only while the owner-verified
# inbox is open, and must never reach a file, an accessible name or a log.
CANARY = "sg3-private-" + secrets.token_hex(6)
OPEN_REFRESH = 3.0  # ricepop.rs OPEN_REFRESH_INTERVAL
RETRY_REFRESH = 12.0  # ricepop.rs RETRY_REFRESH_INTERVAL

mako: subprocess.Popen | None = None
monitor: subprocess.Popen | None = None
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


def application():
    desktop = pyatspi.Registry.getDesktop(0)
    for app in _children(desktop, 40):
        if app.name == "riceplate-native":
            return app
    return None


def walk(node, depth=0, maximum=7):
    yield node, depth
    if depth < maximum:
        for child in _children(node):
            yield from walk(child, depth + 1, maximum)


def snapshot() -> list[dict]:
    """Every accessible node of the native panel: role, name, description, focus."""
    app = application()
    if app is None:
        return []
    rows = []
    for node, _ in walk(app):
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
def scenario() -> None:
    start_monitor()
    owner = start_mako()
    # Mako 1.8 never emits ActionInvoked for `makoctl invoke` (observed), so
    # this smoke's invoke receipts need the 1.11 D-Bus surface. Refuse loudly
    # rather than degrade to a weaker check.
    modern = subprocess.run(
        ["busctl", "--user", "get-property", "org.freedesktop.Notifications",
         "/fr/emersion/Mako", "fr.emersion.Mako", "Notifications"],
        capture_output=True).returncode == 0
    require(modern, "requires Mako >= 1.11 on PATH (see scripts/smoke_real_mako_111.sh)")
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
    recycled = 0
    while recycled != target:
        recycled = notify("Foxtrot" if (recycled + 1 == target) else "filler")
        require(recycled <= target, "could not recycle ID %d" % target)
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


def main() -> int:
    try:
        scenario()
    except Fail as failure:
        print("SG3 native RicePop smoke FAILED: %s" % failure, file=sys.stderr)
        rows = inbox() or []
        start = next((i for i, r in enumerate(rows) if r["role"] == "dialog"), 0)
        print("accessible dialog now: %r" % [
            (r["role"], r["name"], r["focused"]) for r in rows[start:start + 24]],
            file=sys.stderr)
        return 1
    finally:
        for process in (monitor, mako):
            if process is not None and process.poll() is None:
                process.kill()
    print("SG3 native RicePop inbox: %d receipts PASS" % len(receipts))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Real-keyboard helpers for GTK3 toplevels under a real labwc (shared by the SG2/SG3/SG4 smokes).

Why every GTK key carries a pad key (measured 27 Nov 2026 with a plain two-button ``Gtk.Window``
under labwc 0.7.1 and 0.7.2, closed in WP3.1): the key IS delivered to the toplevel
(``wl_keyboard.enter``, ``key-press-event`` with the right keyval) and the window is
Wayland-native, but ``wtype`` uploads a throw-away keymap holding ONLY the keysyms of that
invocation (``<K1>=9, <K2>=10, ...``) and GDK3's Wayland keymap
(``gdk_keymap_get_entries_for_keyval``) never reports the HIGHEST keycode of a keymap. GTK3 key
bindings (Tab -> ``move-focus``, Return -> ``activate-default``, space -> ``activate``,
Escape -> a dialog's ``close``) are matched through that lookup, so the last key of every
``wtype`` call reaches the widget as a plain event and then does nothing. A normal keyboard
keymap has hundreds of keycodes, so real hardware is unaffected. The real-input fix is to send
every GTK key with one trailing, unbound pad key in the SAME ``wtype`` keymap, so the key
under test is never the highest keycode. The pad key goes through the same real labwc virtual
keyboard and is ignored by the page.

The helpers take their *observation* from the caller: ``focused()`` (the accessibles that hold
keyboard focus, from AT-SPI; ``focused_stops(root)`` below is the shared reader) and ``busy()``
(True while the product shows its own visible "request in progress" refusal).
"""
from __future__ import annotations

import subprocess
import time
from typing import Callable

# F35 is an unbound keysym in every GTK3 widget and in the shipped labwc rc.xml.
GTK_PAD_KEY = "F35"


class Fail(Exception):
    """A smoke assertion failed (shared by the drivers so the helpers can raise it)."""


def wtype(*args: str) -> None:
    subprocess.run(["wtype", *args], check=True, timeout=10)


def gtk_key(name: str, pause: float = 0.2) -> None:
    """One real compositor key that GTK3 acts on: ``wtype -k <name> -k F35``."""
    wtype("-k", name, "-k", GTK_PAD_KEY)
    time.sleep(pause)


def unpadded_key(name: str) -> None:
    """The negative control that pins the cause: the one key of this keymap is its highest
    keycode, so GTK3 receives it as a plain event and does nothing."""
    wtype("-k", name)


def focused_stops(root) -> list[str]:
    """The keyboard-focused accessibles (AT-SPI FOCUSED + SHOWING) below ``root``, every window of
    the application included, as "name|role|x,y". Some stops (scroll panes, spin buttons) have an
    empty name, so the role and screen position tell two consecutive stops apart. Hidden subtrees
    are not walked: they cannot hold the focus and are slow to read."""
    import pyatspi
    from gi.repository import GLib
    found: list[str] = []
    if root is None:
        return found
    stack = [root]
    while stack:
        node = stack.pop()
        try:
            state = node.getState()
            if not state.contains(pyatspi.STATE_SHOWING) and node is not root:
                continue
            if state.contains(pyatspi.STATE_FOCUSED):
                box = node.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
                found.append("%s|%s|%d,%d" % (node.name or "", node.getRoleName(), box.x, box.y))
            for index in range(min(node.childCount, 400)):
                child = node.getChildAtIndex(index)
                if child is not None:
                    stack.append(child)
        except (LookupError, RuntimeError, GLib.Error, NotImplementedError):
            continue
    return found


def stop_name(stop: str) -> str:
    return stop.split("|", 1)[0]


def wait_for(predicate, message: str, timeout: float = 8.0, step: float = 0.15,
             tolerated: tuple = (LookupError, RuntimeError, OSError, subprocess.SubprocessError)):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
        except tolerated:
            value = None
        if value:
            return value
        time.sleep(step)
    raise Fail("timeout: " + message)


def tab_to(name: str, focused: Callable[[], list], *, limit: int = 90,
           describe: Callable[[], str] | None = None,
           matches: Callable[[str], bool] | None = None) -> int:
    """Real Tab key presses until an accessible named ``name`` (or one for which ``matches``
    holds) has keyboard focus; returns the number of presses. Every press must change the
    focused accessible; some stops (a combo box's inner widget) expose no accessible of
    their own and read as empty focus, which is itself a change. A live update can rebuild
    the page under the focused widget and drop focus: one more real Tab then continues from
    the page start."""
    def hit(names: list) -> bool:
        return any((matches(n) if matches else n == name) for n in names)

    trail: list[str] = []
    focus = focused()
    for count in range(limit + 1):
        trail.append("/".join(focus))
        if hit(focus):
            return count
        gtk_key("Tab")
        previous = focus
        if previous:
            for retry in range(3):
                try:
                    # The first reading that differs is the next stop (and the next iteration's
                    # starting point, so each press costs one accessibility-tree walk).
                    focus = wait_for(lambda: (lambda now: [now] if now != previous else None)(focused()),
                                     "focus moved by Tab", 3.0)[0]
                    break
                except Fail:
                    if retry == 2:
                        raise Fail("a real Tab did not move GTK focus from %r towards %r%s" % (
                            previous, name, ("; tree: " + describe()) if describe else "")) from None
                    gtk_key("Tab")
        else:
            time.sleep(0.3)
            focus = focused()
    raise Fail("Tab never reached %r within %d presses; focus trail: %r" % (name, limit, trail[-40:]))


def activate(key: str, done: Callable[[], object], message: str, *, busy: Callable[[], bool],
             describe: Callable[[], str] | None = None, attempts: int = 4) -> int:
    """Real ``key`` on the focused control until ``done()`` holds. The one tolerated miss is the
    product's own visible refusal (``busy()``): a window that is mid-readback answers a
    state-changing action with a status text instead of acting, so the key is repeated once the
    request ended. Any other silent miss fails. Returns the number of key presses."""
    for attempt in range(1, attempts + 1):
        gtk_key(key)
        try:
            wait_for(done, message, 2.5)
            return attempt
        except Fail:
            if not busy():
                raise Fail("%s: the key neither acted nor produced the busy refusal%s" % (
                    message, ("; tree: " + describe()) if describe else "")) from None
            time.sleep(0.6)
    raise Fail("%s: still refused as busy after %d presses" % (message, attempts))

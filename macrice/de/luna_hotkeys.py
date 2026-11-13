"""Private labwc XP Luna shortcuts routed to the real native RicePlate actions.

Never installs global shortcuts, mutates ~/.config/labwc, or shells out. Only the
opt-in full native XP Luna session enables these fixed commands. A Waybar
fallback and every other rice retain labwc's standard bindings (including its
own default W-d ToggleShowDesktop).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

# labwc's documented keybind syntax: W = Super. Do not use recipe-provided
# executable strings or allow an arbitrary command to cross the IPC socket.
_SHORTCUTS = (
    ("W-d", "show-desktop"),
    ("W-e", "explorer"),
    ("W-r", "run"),
)
_COMMAND_PREFIX = "riceplate-native --desktop-command "


def _root(source: str) -> ET.Element:
    if len(source) > 65_536:
        raise ValueError("Private labwc rc.xml exceeds maximum size")
    root = ET.fromstring(source)
    if root.tag != "labwc_config":
        raise ValueError("Unexpected labwc XML document")
    return root


def _remove_owned(root: ET.Element) -> bool:
    keyboard = root.find("keyboard")
    if keyboard is None:
        return False
    removed = False
    for binding in list(keyboard.findall("keybind")):
        key = binding.get("key")
        command = next((value for name, value in _SHORTCUTS if name == key), None)
        if command is None:
            continue
        actions = list(binding.findall("action"))
        if len(actions) == 1 and actions[0].get("name") == "Execute" and \
                actions[0].get("command") == _COMMAND_PREFIX + command:
            keyboard.remove(binding)
            removed = True
    return removed


def without_shortcuts(source: str) -> str:
    """Remove only our exact bindings; preserve unrelated user/session settings."""
    root = _root(source)
    if not _remove_owned(root):
        return source
    return ET.tostring(root, encoding="unicode")


def render(source: str, enabled: bool) -> str:
    """Compile the three bindings into an already private, validated labwc rc.

    This is idempotent; any previous RicePlate hotkeys are removed first.
    Disabled profiles get the original labwc defaults, never dead IPC actions.
    """
    if not enabled:
        return without_shortcuts(source)
    root = _root(source)
    _remove_owned(root)
    keyboard = root.find("keyboard")
    if keyboard is None:
        keyboard = ET.SubElement(root, "keyboard")
    for key, request in _SHORTCUTS:
        for binding in list(keyboard.findall("keybind")):
            if binding.get("key") == key:
                # This is a disposable RiceBowl-owned config, not the user's
                # ~/.config/labwc. The live controller keeps the exact baseline
                # for rollback and for switching away from Luna.
                keyboard.remove(binding)
        ET.SubElement(
            ET.SubElement(keyboard, "keybind", key=key),
            "action", name="Execute", command=_COMMAND_PREFIX + request,
        )
    return ET.tostring(root, encoding="unicode")


def commands(source: str) -> dict[str, str]:
    """Inspect the effective explicit keybinds (useful for UI and CI QA)."""
    root = _root(source)
    keyboard = root.find("keyboard")
    if keyboard is None:
        return {}
    return {
        node.get("key", ""): action.get("command", "")
        for node in keyboard.findall("keybind")
        for action in node.findall("action")
        if action.get("name") == "Execute"
    }

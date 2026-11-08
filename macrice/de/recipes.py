"""Data-only RicePlate panel recipes with a temporary Waybar rendering adapter.

Recipe files are deliberately not executable plugins. The v1 layout vocabulary
is independent of Waybar so a future native RicePlate renderer can consume it.
"""

from __future__ import annotations

import json
import fcntl
import os
import re
import stat
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_RECIPE_BYTES = 64 * 1024
MAX_SELECTION_BYTES = 2048
WIDGETS = frozenset(("launcher", "tasks", "clock", "network", "audio", "battery", "tray"))
SECTIONS = ("start", "center", "end")
COLORS = ("background", "foreground", "active")
METRIC_DEFAULTS = (104, 164, 96)
METRIC_FIELDS = ("launcher_width", "task_width", "clock_width")
METRIC_LIMITS = ((64, 256), (96, 256), (64, 256))
MAX_LAYOUT_NODES = 24
MAX_LAYOUT_LABELS = 8
MAX_LAYOUT_ACTIONS = 6
MAX_LAYOUT_DEPTH = 3
MAX_LAYOUT_ROOTS = 8
MAX_LAYOUT_CHILDREN = 6
MAX_DESKTOP_ICONS = 8
MAX_DESKTOP_WIDGETS = 4
MAX_COMPONENT_DEFINITIONS = 8
COMPONENT_STATUS_BINDINGS = frozenset(("clock", "network", "audio", "battery"))
DESKTOP_WIDGET_KINDS = frozenset(("clock", "date", "system", "text"))
DESKTOP_WIDGET_WIDTH = 200
DESKTOP_WIDGET_HEIGHT = 96
DESIGN_TOKEN_LIMITS = {
    "panel_opacity": (80, 100),
    "menu_radius": (0, 16),
    "widget_radius": (0, 18),
    "widget_padding": (8, 16),
}
ICON_WIDTH = 104
ICON_HEIGHT = 88
ICON_ACTIONS = frozenset(("applications", "terminal", "lock"))
MENU_ACTIONS = frozenset(("applications", "terminal", "lock", "logout",
                          "wifi-toggle", "audio-mute", "audio-up", "audio-down",
                          "notifications", "settings"))
# A deliberately smaller set than menu quick controls: all four work from a
# panel without requiring a menu feedback surface or a custom command parser.
PANEL_ACTIONS = frozenset(("applications", "terminal", "settings", "lock"))
PANEL_CONTROLS = frozenset(("wifi-toggle", "audio-mute", "audio-up", "audio-down"))
PANEL_ACTION_COMMANDS = {
    "applications": "fuzzel", "terminal": "foot",
    "settings": "ricebowl de settings", "lock": "swaylock -f",
}
WALLPAPERS = frozenset(("aero-seven-blue", "aero-seven-night", "luna-hills",
                        "classic-teal", "ten-blue", "ten-midnight", "chrome-pastel",
                        "frutiger-future", "aurora-day", "aurora-night"))
BUILTINS = {
    "classic": Path(__file__).resolve().parent / "resources/recipes/classic.json",
    "chrome": Path(__file__).resolve().parent / "resources/recipes/chrome.json",
}


class RecipeError(ValueError):
    """Invalid or unsupported RicePlate recipe; no desktop changes made."""


class SelectionConflict(RecipeError):
    """Next-login selection changed since the caller last inspected it."""


class RecipeFingerprintMismatch(RecipeError):
    """Recipe changed since Creator's semantic review."""


@dataclass(frozen=True)
class LayoutNode:
    """A bounded, typed, non-executable horizontal panel composition node."""

    kind: str
    value: str | int = ""
    gap: int = 0
    children: tuple[LayoutNode, ...] = ()
    label: str = ""


@dataclass(frozen=True)
class MenuContent:
    kind: str
    title: str
    limit: int


@dataclass(frozen=True)
class MenuGroup:
    title: str
    actions: tuple[str, ...]
    content: tuple[MenuContent, ...] | None = None


@dataclass(frozen=True)
class DesktopIcon:
    label: str
    action: str
    x: int
    y: int


@dataclass(frozen=True)
class DesktopWidget:
    widget_id: str
    kind: str
    x: int
    y: int
    component_ref: str | None = None
    text: str = ""


@dataclass(frozen=True)
class ComponentDefinition:
    component_id: str
    role: str
    binding: str
    label: str


@dataclass(frozen=True)
class WindowRegion:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class DesktopComposition:
    widgets: tuple[DesktopWidget, ...]
    window_region: WindowRegion
    compact_hide_widgets: tuple[str, ...]


@dataclass(frozen=True)
class PanelRecipe:
    recipe_id: str
    name: str
    position: str
    height: int
    sections: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]
    colors: tuple[str, str, str]
    metrics: tuple[int, int, int] | None = None
    layout: tuple[tuple[LayoutNode, ...], ...] | None = None
    schema_version: int = 1
    menu: tuple[str, tuple[MenuGroup, ...]] | None = None
    wallpaper: str | None = None
    tokens: tuple[int, int] | None = None
    compact: tuple[int, tuple[tuple[LayoutNode, ...], ...]] | None = None
    desktop_icons: tuple[DesktopIcon, ...] | None = None
    menu_presentation: str = "tabs"
    composition: DesktopComposition | None = None
    components: tuple[ComponentDefinition, ...] = ()
    design: tuple[int, int, int, int] | None = None


def _parse_components(raw: Any) -> dict[str, ComponentDefinition]:
    """A bounded per-rice registry of bindings to existing native capabilities."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_COMPONENT_DEFINITIONS:
        raise RecipeError("Component library needs 1–8 definitions")
    result: dict[str, ComponentDefinition] = {}
    for entry in raw:
        entry = _strict_keys(entry, {"id", "role", "binding", "label"}, "Component definition")
        identifier, role, binding, label = (entry[key] for key in
                                             ("id", "role", "binding", "label"))
        if (type(identifier) is not str or
                re.fullmatch(r"[a-z][a-z0-9-]{1,23}", identifier) is None or
                type(role) is not str or type(binding) is not str or
                type(label) is not str or not _safe_label(label, 16) or
                (role == "status" and binding not in COMPONENT_STATUS_BINDINGS) or
                (role == "action" and binding not in PANEL_ACTIONS | PANEL_CONTROLS) or
                role not in ("status", "action") or identifier in result):
            raise RecipeError("Invalid or duplicate component capability binding")
        result[identifier] = ComponentDefinition(identifier, role, binding, label)
    return result


def _parse_composition(raw: Any, *, components: dict[str, ComponentDefinition] | None = None,
                       schema_version: int = 8
                       ) -> DesktopComposition:
    """Bounded desktop composition with safe v9 presentation-only labels."""
    data = _strict_keys(raw, {"widgets", "window_region", "compact_hide_widgets"},
                        "Desktop composition")
    raw_widgets = data["widgets"]
    if not isinstance(raw_widgets, list) or len(raw_widgets) > MAX_DESKTOP_WIDGETS:
        raise RecipeError("Desktop composition supports at most four widgets")
    widgets: list[DesktopWidget] = []
    for item in raw_widgets:
        component = type(item) is dict and item.get("kind") == "component"
        text = type(item) is dict and item.get("kind") == "text" and schema_version >= 9
        keys = ({"id", "kind", "ref", "x", "y"} if component else
                {"id", "kind", "text", "x", "y"} if text else {"id", "kind", "x", "y"})
        item = _strict_keys(item, keys, "Desktop widget")
        bound = components.get(item["ref"]) if component and components is not None \
            and type(item["ref"]) is str else None
        if (type(item["id"]) is not str or
                re.fullmatch(r"[a-z][a-z0-9-]{1,23}", item["id"]) is None or
                type(item["kind"]) is not str or
                not (item["kind"] in (DESKTOP_WIDGET_KINDS if schema_version >= 9 else
                                     ("clock", "date", "system")) or
                     component and bound is not None and bound.role == "status") or
                (text and not _safe_label(item["text"], 22)) or
                type(item["x"]) is not int or type(item["y"]) is not int or
                not 0 <= item["x"] <= 16_384 or not 0 <= item["y"] <= 16_384):
            raise RecipeError("Invalid declarative desktop widget")
        if any(widget.widget_id == item["id"] for widget in widgets):
            raise RecipeError("Duplicate desktop widget ID")
        widgets.append(DesktopWidget(item["id"], bound.binding if component else item["kind"],
                                     item["x"], item["y"], item["ref"] if component else None,
                                     item["text"] if text else ""))
    region = _strict_keys(data["window_region"], {"x", "y", "width", "height"},
                          "Reserved window region")
    if (any(type(region[key]) is not int for key in ("x", "y", "width", "height")) or
            not 0 <= region["x"] <= 99 or not 0 <= region["y"] <= 99 or
            not 1 <= region["width"] <= 100 or not 1 <= region["height"] <= 100 or
            region["x"] + region["width"] > 100 or
            region["y"] + region["height"] > 100):
        raise RecipeError("Reserved window region must fit within 0–100 percent")
    hidden = data["compact_hide_widgets"]
    ids = {widget.widget_id for widget in widgets}
    if (not isinstance(hidden, list) or len(hidden) > MAX_DESKTOP_WIDGETS or
            any(type(item) is not str or item not in ids for item in hidden) or
            len(set(hidden)) != len(hidden)):
        raise RecipeError("Compact widget IDs must be unique members of the layout")
    return DesktopComposition(tuple(widgets), WindowRegion(**region), tuple(hidden))


def _safe_label(value: Any, limit: int = 24) -> bool:
    return type(value) is str and re.fullmatch(
        rf"[A-Za-z0-9 ._:+-]{{1,{limit}}}", value) is not None


def _parse_menu(value: Any, *, schema_version: int = 4) -> tuple[str, tuple[MenuGroup, ...]]:
    if schema_version >= 6 and isinstance(value, dict):
        if "presentation" in value:
            if type(value["presentation"]) is not str or value["presentation"] not in ("tabs", "sidebar"):
                raise RecipeError("Menu presentation must be tabs or sidebar")
            _strict_keys(value, {"title", "groups", "presentation"}, "Menu")
        else:
            _strict_keys(value, {"title", "groups"}, "Menu")
        data = value
    else:
        data = _strict_keys(value, {"title", "groups"}, "Menu")
    if not _safe_label(data["title"], 32):
        raise RecipeError("Menu title must be safe printable ASCII")
    groups = data["groups"]
    if not isinstance(groups, list) or not 1 <= len(groups) <= 4:
        raise RecipeError("Menu requires 1-4 groups")
    result: list[MenuGroup] = []
    seen: set[str] = set()
    for value in groups:
        if isinstance(value, dict) and "content" in value and schema_version >= 6:
            group = _strict_keys(value, {"title", "actions", "content"}, "Menu group")
        else:
            group = _strict_keys(value, {"title", "actions"}, "Menu group")
        actions = group["actions"]
        if (not _safe_label(group["title"]) or not isinstance(actions, list)
                or not 1 <= len(actions) <= 4 or any(type(action) is not str
                or action not in MENU_ACTIONS or action in seen for action in actions)
                or len(actions) != len(set(actions))):
            raise RecipeError("Menu group uses unsupported or duplicate actions")
        seen.update(actions)
        content = None
        if "content" in group:
            sections = group["content"]
            if not isinstance(sections, list) or not 1 <= len(sections) <= 2:
                raise RecipeError("Menu content requires one or two sections")
            parsed: list[MenuContent] = []
            sources: set[str] = set()
            for section in sections:
                section = _strict_keys(section, {"type", "title", "limit"}, "Menu content")
                kind = section["type"]
                if (type(kind) is not str or kind not in
                    ("actions", "favorites", "apps-list", "apps-grid")
                    or kind in sources or not _safe_label(section["title"])
                    or type(section["limit"]) is not int or not 1 <= section["limit"] <= 4):
                    raise RecipeError("Invalid or repeated menu content source")
                sources.add(kind)
                parsed.append(MenuContent(kind, section["title"], section["limit"]))
            if sum(section.limit for section in parsed) > 4:
                raise RecipeError("Menu content exceeds four visible items")
            content = tuple(parsed)
        result.append(MenuGroup(group["title"], tuple(actions), content))
    return data["title"], tuple(result)


def _parse_desktop_icons(value: Any) -> tuple[DesktopIcon, ...]:
    """Only known actions and bounded, non-overlapping 104x88 icon regions."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_DESKTOP_ICONS:
        raise RecipeError("Desktop icon list must have 1-8 entries")
    result: list[DesktopIcon] = []
    for raw in value:
        icon = _strict_keys(raw, {"label", "action", "x", "y"}, "Desktop icon")
        if (not _safe_label(icon["label"], 12)
                or type(icon["action"]) is not str or icon["action"] not in ICON_ACTIONS
                or type(icon["x"]) is not int or not 0 <= icon["x"] <= 4096
                or type(icon["y"]) is not int or not 72 <= icon["y"] <= 4096):
            raise RecipeError("Unsupported desktop icon action, label or position")
        item = DesktopIcon(icon["label"], icon["action"], icon["x"], icon["y"])
        if any(abs(other.x - item.x) < ICON_WIDTH
               and abs(other.y - item.y) < ICON_HEIGHT for other in result):
            raise RecipeError("Desktop icon hit regions overlap")
        result.append(item)
    return tuple(result)


def _object_without_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise RecipeError("Duplicate recipe key")
        result[key] = value
    return result


def _strict_keys(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RecipeError(f"{context} must contain exactly: {', '.join(sorted(keys))}")
    return value


def _parse_layout_node(raw: Any, depth: int, counts: list[int], widgets: list[str],
                       actions: dict[str, str], *, schema_version: int,
                       components: dict[str, ComponentDefinition] | None = None) -> LayoutNode:
    """Validate one reusable primitive; never interpret fields as commands."""
    counts[0] += 1
    if depth > MAX_LAYOUT_DEPTH or counts[0] > MAX_LAYOUT_NODES:
        raise RecipeError("Panel layout exceeds bounded depth or node count")
    if not isinstance(raw, dict) or type(raw.get("type")) is not str:
        raise RecipeError("Panel layout node needs a known type")
    kind = raw["type"]
    if kind == "component":
        _strict_keys(raw, {"type", "ref"}, "Component reference")
        ref = raw["ref"]
        bound = components.get(ref) if type(ref) is str and components else None
        if schema_version < 9 or bound is None:
            raise RecipeError("Unknown or unsupported component reference")
        if bound.role == "status":
            widgets.append(bound.binding)
        else:
            if bound.binding in actions or len(actions) >= MAX_LAYOUT_ACTIONS:
                raise RecipeError("Duplicate or excessive component action binding")
            actions[bound.binding] = bound.label
        return LayoutNode(kind, ref)
    if kind == "widget":
        _strict_keys(raw, {"type", "id"}, "Widget node")
        if type(raw["id"]) is not str or raw["id"] not in WIDGETS:
            raise RecipeError("Unsupported panel widget ID")
        widgets.append(raw["id"])
        return LayoutNode(kind, raw["id"])
    if kind == "gap":
        _strict_keys(raw, {"type", "width"}, "Gap node")
        if type(raw["width"]) is not int or not 4 <= raw["width"] <= 64:
            raise RecipeError("Panel gap width must be 4-64 logical pixels")
        return LayoutNode(kind, raw["width"])
    if kind == "divider":
        _strict_keys(raw, {"type", "width"}, "Divider node")
        if type(raw["width"]) is not int or not 6 <= raw["width"] <= 32:
            raise RecipeError("Panel divider width must be 6-32 logical pixels")
        return LayoutNode(kind, raw["width"])
    if kind == "label":
        _strict_keys(raw, {"type", "text"}, "Label node")
        text = raw["text"]
        if (type(text) is not str or not re.fullmatch(r"[A-Za-z0-9 ._:+-]{1,24}", text)):
            raise RecipeError("Panel label must be 1-24 safe printable ASCII characters")
        counts[1] += 1
        if counts[1] > MAX_LAYOUT_LABELS:
            raise RecipeError("Too many panel labels")
        return LayoutNode(kind, text)
    if kind in ("action", "control"):
        _strict_keys(raw, {"type", "id", "label"}, "Panel button node")
        action_id, label = raw["id"], raw["label"]
        minimum = 7 if kind == "control" else 6
        allowed = PANEL_CONTROLS if kind == "control" else PANEL_ACTIONS
        if (schema_version < minimum or type(action_id) is not str
                or action_id not in allowed or not _safe_label(label, 16)):
            raise RecipeError("Panel button needs a supported schema, known ID and safe label")
        if action_id in actions:
            raise RecipeError("Duplicate panel button ID")
        if len(actions) >= MAX_LAYOUT_ACTIONS:
            raise RecipeError("Too many panel actions")
        actions[action_id] = label
        return LayoutNode(kind, action_id, label=label)
    if kind == "group":
        _strict_keys(raw, {"type", "gap", "children"}, "Group node")
        children = raw["children"]
        if (depth >= MAX_LAYOUT_DEPTH or type(raw["gap"]) is not int
                or not 0 <= raw["gap"] <= 32 or not isinstance(children, list)
                or not 1 <= len(children) <= MAX_LAYOUT_CHILDREN):
            raise RecipeError("Group needs 1-6 children, 0-32px gap and bounded depth")
        return LayoutNode(kind, gap=raw["gap"], children=tuple(
            _parse_layout_node(child, depth + 1, counts, widgets, actions,
                               schema_version=schema_version, components=components)
            for child in children))
    raise RecipeError("Unsupported panel layout node or action")


def _parse_layout(raw: Any, *, schema_version: int = 3,
                  components: dict[str, ComponentDefinition] | None = None
                  ) -> tuple[tuple[tuple[LayoutNode, ...], ...], list[str]]:
    layout = _strict_keys(raw, set(SECTIONS), "Panel layout")
    counts = [0, 0]
    widgets: list[str] = []
    actions: dict[str, str] = {}
    result = []
    for section in SECTIONS:
        entries = layout[section]
        if not isinstance(entries, list) or len(entries) > MAX_LAYOUT_ROOTS:
            raise RecipeError("Panel layout section has more than eight roots")
        result.append(tuple(_parse_layout_node(entry, 1, counts, widgets, actions,
                            schema_version=schema_version, components=components)
                            for entry in entries))
    return (result[0], result[1], result[2]), widgets


def layout_node_json(node: LayoutNode) -> dict[str, Any]:
    """Canonical data representation consumed by Creator review and Waybar."""
    if node.kind == "group":
        return {"type": "group", "gap": node.gap,
                "children": [layout_node_json(child) for child in node.children]}
    if node.kind == "widget":
        return {"type": "widget", "id": node.value}
    if node.kind == "component":
        return {"type": "component", "ref": node.value}
    if node.kind in ("action", "control"):
        return {"type": node.kind, "id": node.value, "label": node.label}
    if node.kind == "label":
        return {"type": "label", "text": node.value}
    if node.kind == "divider":
        return {"type": "divider", "width": node.value}
    return {"type": "gap", "width": node.value}


def parse(raw: bytes) -> PanelRecipe:
    """Validate a bounded, declarative schema with no commands or asset paths."""
    if len(raw) > MAX_RECIPE_BYTES:
        raise RecipeError("RicePlate recipe exceeds the 64 KiB limit")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_without_duplicates)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise RecipeError(f"Invalid RicePlate recipe JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RecipeError("Recipe must be a JSON object")
    version = data.get("schema_version")
    if type(version) is not int or version not in range(1, 11):
        raise RecipeError("Unsupported RicePlate recipe schema version")
    expected = {"schema_version", "id", "name", "panel", "colors"}
    if version >= 4:
        expected.update(("menu", "desktop", "tokens", "responsive"))
    if version >= 8:
        expected.add("composition")
    if version >= 9:
        expected.add("components")
    data = _strict_keys(data, expected, "Recipe")
    components = _parse_components(data["components"]) if version >= 9 else {}
    recipe_id = data["id"]
    if not isinstance(recipe_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", recipe_id):
        raise RecipeError("Recipe ID must contain 2-32 lowercase ASCII characters")
    name = data["name"]
    if (not isinstance(name, str) or not 1 <= len(name) <= 60
            or any(unicodedata.category(character) == "Cc" for character in name)):
        raise RecipeError("Recipe name must be 1-60 printable characters")
    panel_keys = {"position", "height", "layout" if version >= 3 else "sections"}
    if version >= 2:
        panel_keys.add("metrics")
    panel = _strict_keys(data["panel"], panel_keys, "Panel")
    if panel["position"] not in ("top", "bottom"):
        raise RecipeError("Panel position must be top or bottom")
    if type(panel["height"]) is not int or not 28 <= panel["height"] <= 64:
        raise RecipeError("Panel height must be an integer between 28 and 64")
    metrics: tuple[int, int, int] | None = None
    if version >= 2:
        sizes = _strict_keys(panel["metrics"], set(METRIC_FIELDS), "Panel metrics")
        if any(type(sizes[key]) is not int or not lower <= sizes[key] <= upper
               for key, (lower, upper) in zip(METRIC_FIELDS, METRIC_LIMITS)):
            raise RecipeError("Panel metrics must be bounded integer widths in pixels")
        metrics = tuple(sizes[key] for key in METRIC_FIELDS)
    selected: list[tuple[str, ...]] = []
    all_widgets: list[str] = []
    layout_nodes = None
    if version >= 3:
        layout_nodes, all_widgets = _parse_layout(panel["layout"], schema_version=version,
                                                components=components)
        def widget_ids(nodes: tuple[LayoutNode, ...]) -> tuple[str, ...]:
            return tuple(item for node in nodes for item in (
                (node.value,) if node.kind == "widget" else
                (components[node.value].binding,) if node.kind == "component" and
                components[node.value].role == "status" else
                widget_ids(node.children) if node.kind == "group" else ()))
        selected = [widget_ids(nodes) for nodes in layout_nodes]
    else:
        sections = _strict_keys(panel["sections"], set(SECTIONS), "Panel sections")
        for section in SECTIONS:
            widgets = sections[section]
            if (not isinstance(widgets, list) or len(widgets) > 7
                    or any(not isinstance(widget, str) or widget not in WIDGETS
                           for widget in widgets)):
                raise RecipeError(f"Invalid widget list in panel section {section}")
            selected.append(tuple(widgets))
            all_widgets.extend(widgets)
    if len(all_widgets) != len(set(all_widgets)):
        raise RecipeError("A panel widget may appear only once")
    if not {"tasks", "launcher"} & set(all_widgets):
        raise RecipeError("Panel must provide tasks or an application launcher")
    colors = _strict_keys(data["colors"], set(COLORS), "Colors")
    for color in COLORS:
        if not isinstance(colors[color], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", colors[color]):
            raise RecipeError(f"Invalid six-digit hexadecimal color: {color}")
    menu = None
    wallpaper = None
    tokens = None
    design = None
    compact = None
    desktop_icons = None
    composition = None
    if version >= 4:
        if version >= 8:
            composition = _parse_composition(data["composition"], components=components,
                                             schema_version=version)
        menu = _parse_menu(data["menu"], schema_version=version)
        desktop = _strict_keys(data["desktop"],
                               {"wallpaper", "icons"} if version >= 5 else {"wallpaper"},
                               "Desktop")
        from .assets import ASSET_ID
        if (type(desktop["wallpaper"]) is not str
                or not (desktop["wallpaper"] in WALLPAPERS
                        or version >= 6 and ASSET_ID.fullmatch(desktop["wallpaper"]))):
            raise RecipeError("Desktop wallpaper must name a bundled or v6 content-addressed asset")
        wallpaper = desktop["wallpaper"]
        if version >= 5:
            desktop_icons = _parse_desktop_icons(desktop["icons"])
        visual = _strict_keys(data["tokens"],
                              {"label_padding", "task_radius"} |
                              (set(DESIGN_TOKEN_LIMITS) if version >= 10 else set()), "Tokens")
        if (type(visual["label_padding"]) is not int
                or not 0 <= visual["label_padding"] <= 16
                or type(visual["task_radius"]) is not int
                or not 0 <= visual["task_radius"] <= 12):
            raise RecipeError("Visual tokens must be bounded integer pixel values")
        tokens = visual["label_padding"], visual["task_radius"]
        if version >= 10:
            if any(type(visual[key]) is not int or not lower <= visual[key] <= upper
                   for key, (lower, upper) in DESIGN_TOKEN_LIMITS.items()):
                raise RecipeError("Schema v10 design tokens must be bounded integers")
            design = tuple(visual[key] for key in DESIGN_TOKEN_LIMITS)
        responsive = _strict_keys(data["responsive"], {"compact_max_width", "compact_layout"},
                                  "Responsive layout")
        threshold = responsive["compact_max_width"]
        if type(threshold) is not int or not 480 <= threshold <= 1440:
            raise RecipeError("Compact breakpoint must be 480-1440 logical pixels")
        alternate, alternate_widgets = _parse_layout(responsive["compact_layout"],
                                                     schema_version=version,
                                                     components=components)
        if (len(alternate_widgets) != len(set(alternate_widgets))
                or not {"tasks", "launcher"} & set(alternate_widgets)):
            raise RecipeError("Compact layout requires unique widgets and launcher/tasks")
        def action_labels(sections: tuple[tuple[LayoutNode, ...], ...]) -> dict[str, str]:
            result: dict[str, str] = {}
            def visit(node: LayoutNode) -> None:
                if node.kind in ("action", "control"):
                    result[str(node.value)] = node.label
                if node.kind == "component" and components[node.value].role == "action":
                    binding = components[node.value]
                    result[binding.binding] = binding.label
                for child in node.children:
                    visit(child)
            for section in sections:
                for node in section:
                    visit(node)
            return result
        standard_actions = action_labels(layout_nodes)
        if any(standard_actions.get(action_id, label) != label
               for action_id, label in action_labels(alternate).items()):
            raise RecipeError("Panel action labels must match across responsive layouts")
        compact = threshold, alternate
    return PanelRecipe(recipe_id, name, panel["position"], panel["height"],
                       (selected[0], selected[1], selected[2]),
                       (colors["background"], colors["foreground"], colors["active"]),
                       metrics, layout_nodes, version, menu, wallpaper, tokens, compact,
                       desktop_icons,
                       data["menu"].get("presentation", "tabs") if version >= 6 else "tabs",
                       composition, tuple(components.values()), design)


def load(token: str) -> PanelRecipe:
    """Read a bundled recipe or an explicit owner-private absolute JSON file."""
    if token in BUILTINS:
        raw = BUILTINS[token].read_bytes()
        result = parse(raw)
        if result.recipe_id != token:
            raise RecipeError("Bundled recipe ID does not match its name")
        return result
    installed_id = bool(re.fullmatch(r"[a-z][a-z0-9-]{1,31}", token))
    path = _private_recipe_dir(create=False) / f"{token}.json" if installed_id else Path(token)
    if not path.is_absolute():
        raise RecipeError("Use a bundled recipe name or an absolute JSON file path")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as file:
            meta = os.fstat(file.fileno())
            if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                    or meta.st_mode & 0o077):
                raise RecipeError("Custom recipe must be a private owner-only regular file")
            if meta.st_size > MAX_RECIPE_BYTES:
                raise RecipeError("RicePlate recipe exceeds the 64 KiB limit")
            raw = file.read(MAX_RECIPE_BYTES + 1)
    except OSError as exc:
        raise RecipeError("Custom recipe could not be opened safely") from exc
    result = parse(raw)
    if installed_id and result.recipe_id != token:
        raise RecipeError("Imported recipe ID does not match its filename")
    return result


def _read_import_source(source: Path) -> bytes:
    """Read a bounded, owner-controlled data file once, without following links.

    Unlike an active recipe, an offline import may be world-readable (0644).
    Group/world-writable files and files owned by another user are rejected.
    """
    if not source.is_absolute() or source.suffix != ".json":
        raise RecipeError("Import requires an absolute .json file path")
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as file:
            meta = os.fstat(file.fileno())
            if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                    or meta.st_mode & 0o022):
                raise RecipeError("Import source must be an owner-controlled regular file")
            if meta.st_size > MAX_RECIPE_BYTES:
                raise RecipeError("RicePlate recipe exceeds the 64 KiB limit")
            return file.read(MAX_RECIPE_BYTES + 1)
    except OSError as exc:
        raise RecipeError("Import source could not be opened safely") from exc


def _write_private_new(destination: Path, payload: bytes, *, suffix: str = ".json") -> None:
    """Publish a complete 0600 file atomically, refusing any existing target."""
    if not destination.is_absolute() or destination.suffix != suffix:
        raise RecipeError(f"Output must be an absolute {suffix} file path")
    descriptor, temporary = tempfile.mkstemp(prefix=".ricebowl-recipe-",
                                              dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, destination)
    finally:
        os.unlink(temporary)


def _private_recipe_dir(*, create: bool) -> Path:
    """Find the dedicated user-owned collection, never changing its permissions."""
    configured = os.environ.get("XDG_CONFIG_HOME")
    root = Path(configured) if configured else Path.home() / ".config"
    if not root.is_absolute():
        raise RecipeError("XDG_CONFIG_HOME must be an absolute directory")
    directory = root / "ricebowl" / "recipes"
    for path in (root, root / "ricebowl", directory):
        if create and not path.exists() and not path.is_symlink():
            path.mkdir(mode=0o700)
        try:
            meta = path.lstat()
        except FileNotFoundError:
            if not create:
                return directory
            raise RecipeError(f"Recipe directory is unavailable: {path}") from None
        if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o022):
            raise RecipeError(f"Unsafe recipe configuration directory: {path}")
        # The collection itself must be private. An existing ~/.config/ricebowl
        # (created by older releases) may legitimately be 0755: it is safe as
        # long as others cannot WRITE it and the recipes subdir is 0700.
        if path == directory and meta.st_mode & 0o077:
            raise RecipeError(f"Recipe directory must be owner-only: {path}")
    return directory


def import_recipe(source: Path) -> tuple[PanelRecipe, Path]:
    """Import validated offline JSON into the user collection, without applying it."""
    payload = _read_import_source(source)
    recipe = parse(payload)
    if recipe.recipe_id in BUILTINS:
        raise RecipeError("Cannot import a recipe with a reserved built-in ID")
    destination = _private_recipe_dir(create=True) / f"{recipe.recipe_id}.json"
    _write_private_new(destination, payload)
    return recipe, destination


def export_recipe(token: str, destination: Path) -> PanelRecipe:
    """Export a validated recipe as owner-private portable JSON; never overwrite."""
    if token in BUILTINS:
        payload = BUILTINS[token].read_bytes()
    else:
        installed_id = bool(re.fullmatch(r"[a-z][a-z0-9-]{1,31}", token))
        source = (_private_recipe_dir(create=False) / f"{token}.json"
                  if installed_id else Path(token))
        payload = _read_import_source(source)
    recipe = parse(payload)
    if token not in BUILTINS and installed_id and recipe.recipe_id != token:
        raise RecipeError("Imported recipe ID does not match its filename")
    _write_private_new(destination, payload)
    return recipe


def imported_recipes() -> list[tuple[PanelRecipe, Path]]:
    """Discover installed private recipes without creating files or directories."""
    directory = _private_recipe_dir(create=False)
    if not directory.exists():
        return []
    # RicePack import keeps data-only `.ricepack-provenance` receipts next to
    # recipes. They are not recipe candidates and must not consume the 128
    # validated-recipe slots or be accidentally parsed as recipe JSON.
    entries = sorted(path for path in directory.iterdir() if path.suffix == ".json")
    if len(entries) > 128:
        raise RecipeError("Too many imported recipes (limit 128)")
    found = []
    for path in entries:
        recipe = load(str(path))
        if recipe.recipe_id != path.stem or recipe.recipe_id in BUILTINS:
            raise RecipeError(f"Imported recipe ID does not match its filename: {path.name}")
        found.append((recipe, path))
    return found


def native_token(token: str) -> str:
    """Resolve an imported ID for native Rust, which accepts private abs paths."""
    if token in BUILTINS:
        return token
    if re.fullmatch(r"[a-z][a-z0-9-]{1,31}", token):
        return str(_private_recipe_dir(create=False) / f"{token}.json")
    return token


def _read_selection(directory: Path) -> dict[str, Any] | None:
    path = directory / ".active-recipe"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RecipeError("Cannot safely read the selected RicePlate recipe") from exc
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o077 or meta.st_size > MAX_SELECTION_BYTES):
            raise RecipeError("Selected recipe state is not an owner-private bounded file")
        raw = stream.read(MAX_SELECTION_BYTES + 1)
    try:
        data = json.loads(raw, object_pairs_hook=_object_without_duplicates)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise RecipeError("Invalid selected recipe state") from exc
    if type(data) is not dict or type(data.get("schema_version")) is not int:
        raise RecipeError("Unsupported recipe selection version")
    version = data["schema_version"]
    if version == 1:
        fields = {"schema_version", "active", "previous"}
    elif version == 2:
        fields = {"schema_version", "active", "previous", "active_sha256", "previous_sha256"}
    else:
        raise RecipeError("Unsupported recipe selection version")
    _strict_keys(data, fields, "Selection")
    for field in ("active", "previous"):
        if (not isinstance(data[field], str)
                or not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", data[field])):
            raise RecipeError("Recipe selection must contain only built-in/imported IDs")
    if version == 2:
        for field in ("active_sha256", "previous_sha256"):
            value = data[field]
            if value is not None and (type(value) is not str or
                                      not re.fullmatch(r"[0-9a-f]{64}", value)):
                raise RecipeError("Invalid pinned recipe selection fingerprint")
    return data


def current_selection() -> tuple[str, str | None]:
    """Read the next Wayland session's preference without any filesystem writes."""
    directory = _private_recipe_dir(create=False)
    if not directory.exists():
        return "classic", None
    state = _read_selection(directory)
    return (state["active"], state["previous"]) if state else ("classic", None)


def selected_recipe() -> str | None:
    """Return None for the unchanged default session, or a saved recipe ID."""
    directory = _private_recipe_dir(create=False)
    if not directory.exists():
        return None
    state = _read_selection(directory)
    if state is None:
        return None
    if state["schema_version"] == 2 and state["active_sha256"] is not None:
        from . import review
        actual = review._semantic_hash(review._manifest(load(state["active"])))
        if actual != state["active_sha256"]:
            raise RecipeFingerprintMismatch("Saved recipe changed since Creator review")
    return state["active"]


def change_selection(token: str | None = None, *, restore: bool = False,
                     expected_active: str | None = None,
                     expected_semantic_sha256: str | None = None) -> tuple[str, str]:
    """Change only the *next* Wayland session's recipe, with one-level undo.

    The active compositor and every XFCE setting remain untouched. The
    collection lock serializes concurrent authors before reading/writing.
    """
    if (restore and token is not None) or (not restore and token is None):
        raise RecipeError("Provide exactly one of a recipe ID or restore")
    if (expected_active is not None and
            (type(expected_active) is not str or
             not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", expected_active))):
        raise RecipeError("Expected active selection must be a valid recipe ID")
    if (expected_semantic_sha256 is not None and
            (restore or type(expected_semantic_sha256) is not str or
             not re.fullmatch(r"[0-9a-f]{64}", expected_semantic_sha256))):
        raise RecipeError("Expected recipe fingerprint must be a lowercase SHA-256")
    directory = _private_recipe_dir(create=True)
    lock = directory / ".active-recipe.lock"
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, "wb") as locked:
        meta = os.fstat(locked.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o077):
            raise RecipeError("Selected recipe lock is not owner-private")
        fcntl.flock(locked.fileno(), fcntl.LOCK_EX)
        state = _read_selection(directory)
        active = state["active"] if state else "classic"
        if expected_active is not None and active != expected_active:
            raise SelectionConflict("Next-login rice selection changed; review the current state")
        if restore:
            if not state:
                raise RecipeError("No previous RicePlate recipe selection to restore")
            target = state["previous"]
        else:
            assert token is not None
            target = token
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", target):
            raise RecipeError("Select a built-in or imported recipe ID, not a file path")
        target_recipe = load(target)  # Refuse missing/corrupt recipes before changing state.
        expected_target_hash = expected_semantic_sha256
        if restore and state and state["schema_version"] == 2:
            expected_target_hash = state["previous_sha256"]
        if expected_target_hash is not None:
            # Check under the same selection lock as the write. This prevents
            # racing Creator stages from silently using a stale review.
            from . import review
            actual = review._semantic_hash(review._manifest(target_recipe))
            if actual != expected_target_hash:
                raise RecipeFingerprintMismatch("Recipe differs from the reviewed fingerprint")
        if target == active and (expected_semantic_sha256 is None or
                                state and state.get("active_sha256") == expected_semantic_sha256):
            return target, active
        if expected_semantic_sha256 is not None or (restore and state and
                                                      state["schema_version"] == 2):
            if restore:
                next_hash = state["previous_sha256"]
                previous_hash = state["active_sha256"]
            else:
                next_hash = expected_semantic_sha256
                previous_hash = (state.get("active_sha256") if state and target != active
                                 else state.get("previous_sha256") if state else None)
            previous = (state["previous"] if target == active and state else active)
            new_state = {"schema_version": 2, "active": target, "previous": previous,
                         "active_sha256": next_hash, "previous_sha256": previous_hash}
        else:
            new_state = {"schema_version": 1, "active": target, "previous": active}
        payload = (json.dumps(new_state, separators=(",", ":")) + "\n").encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(prefix=".ricebowl-selection-", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, directory / ".active-recipe")
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return target, active


def create_from_template(
    *, source: str, destination: Path, recipe_id: str, name: str,
    schema_version: int = 1,
) -> PanelRecipe:
    """Create one private editable recipe atomically, never replacing a file.

    Templates can change layout, but cannot inject commands, executable assets
    or unknown keys. Both native RicePlate and the Waybar adapter validate the
    same schema before using an authored recipe.
    """
    if source not in BUILTINS:
        raise RecipeError("Choose a bundled classic or chrome template")
    if not destination.is_absolute() or destination.suffix != ".json":
        raise RecipeError("New recipe output must be an absolute .json file path")
    data = json.loads(BUILTINS[source].read_text(encoding="utf-8"))
    if schema_version in range(2, 11):
        data["schema_version"] = schema_version
        data["panel"]["metrics"] = dict(zip(METRIC_FIELDS, METRIC_DEFAULTS))
        if schema_version >= 3:
            sections = data["panel"].pop("sections")
            data["panel"]["layout"] = {
                section: [{"type": "widget", "id": widget} for widget in sections[section]]
                for section in SECTIONS
            }
        if schema_version >= 4:
            data["menu"] = {"title": "RiceBowl", "groups": [
                {"title": "Applications", "actions": ["applications", "terminal"]},
                {"title": "Session", "actions": ["lock", "logout"]},
            ]}
            data["desktop"] = {"wallpaper": "aero-seven-blue"}
            if schema_version >= 5:
                data["desktop"]["icons"] = [
                    {"label": "Applications", "action": "applications", "x": 32, "y": 96},
                    {"label": "Terminal", "action": "terminal", "x": 32, "y": 208},
                ]
            data["tokens"] = {"label_padding": 8, "task_radius": 4}
            if schema_version >= 10:
                data["tokens"].update({"panel_opacity": 100, "menu_radius": 4,
                                       "widget_radius": 10, "widget_padding": 12})
            data["responsive"] = {
                "compact_max_width": 720,
                "compact_layout": {"start": [{"type": "widget", "id": "launcher"}],
                                   "center": [{"type": "widget", "id": "tasks"}],
                                   "end": [{"type": "widget", "id": "clock"}]},
            }
            if schema_version >= 8:
                data["composition"] = {
                    "widgets": [
                        {"id": "desk-clock", "kind": "clock", "x": 32, "y": 320},
                        {"id": "desk-system", "kind": "system", "x": 32, "y": 432},
                    ],
                    "window_region": {"x": 30, "y": 8, "width": 66, "height": 84},
                    "compact_hide_widgets": ["desk-system"],
                }
            if schema_version >= 9:
                data["components"] = [
                    {"id": "net-status", "role": "status", "binding": "network",
                     "label": "Network"},
                    {"id": "wifi-switch", "role": "action", "binding": "wifi-toggle",
                     "label": "Wi-Fi"},
                ]
                data["panel"]["layout"]["start"].append(
                    {"type": "component", "ref": "wifi-switch"})
                data["panel"]["layout"]["end"] = [
                    {"type": "component", "ref": "net-status"}
                    if node.get("id") == "network" else node
                    for node in data["panel"]["layout"]["end"]]
                data["responsive"]["compact_layout"]["end"].append(
                    {"type": "component", "ref": "net-status"})
                data["composition"]["widgets"][1] = {
                    "id": "desk-system", "kind": "component", "ref": "net-status",
                    "x": 32, "y": 432,
                }
    elif schema_version != 1:
        raise RecipeError("Unsupported RicePlate template schema version")
    data["id"] = recipe_id
    data["name"] = name
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    result = parse(payload)  # Validate *before* any filesystem mutation.

    # The temp file and destination share a directory/filesystem; os.link()
    # publishes a fully written file only when its final name is still free.
    # This does not overwrite existing files or follow a destination symlink.
    _write_private_new(destination, payload)
    return result


def waybar_config(recipe: PanelRecipe, *, screen_width: int | None = None) -> tuple[str, str]:
    """Translate safe UI structure into Waybar's temporary JSON/CSS backend."""
    module_names = {
        "launcher": "custom/rice-launcher", "tasks": "wlr/taskbar",
        "clock": "clock", "network": "network", "audio": "pulseaudio",
        "battery": "battery", "tray": "tray",
    }
    generated_modules: dict[str, Any] = {}
    generated_css: list[str] = []
    layout = recipe.layout
    if (recipe.compact is not None and screen_width is not None
            and screen_width <= recipe.compact[0]):
        layout = recipe.compact[1]
    padding, radius = recipe.tokens if recipe.tokens is not None else (8, 4)
    if layout is None:
        section_modules = [[module_names[widget] for widget in widgets]
                           for widgets in recipe.sections]
    else:
        counter = [0]
        definitions = {component.component_id: component for component in recipe.components}

        def generate_node(node: LayoutNode) -> list[str]:
            if node.kind == "component":
                bound = definitions[str(node.value)]
                return generate_node(LayoutNode(
                    "widget" if bound.role == "status" else
                    "control" if bound.binding in PANEL_CONTROLS else "action",
                    bound.binding, label=bound.label))
            if node.kind == "widget":
                return [module_names[str(node.value)]]
            if node.kind == "group":
                result: list[str] = []
                for index, child in enumerate(node.children):
                    if index and node.gap:
                        result.extend(generate_node(LayoutNode("gap", node.gap)))
                    result.extend(generate_node(child))
                return result
            index = counter[0]
            counter[0] += 1
            if node.kind == "gap":
                key = f"custom/rice-gap-{index}"
                generated_modules[key] = {"format": "", "tooltip": False}
                generated_css.append(f"#custom-rice-gap-{index} {{ min-width: {node.value}px; padding: 0; }}")
            elif node.kind == "divider":
                key = f"custom/rice-divider-{index}"
                generated_modules[key] = {"format": "", "tooltip": False}
                generated_css.append(
                    f"#custom-rice-divider-{index} {{ min-width: {node.value}px; "
                    f"border-left: 1px solid {recipe.colors[1]}; margin: 8px 0; padding: 0; }}")
            elif node.kind == "action":
                key = f"custom/rice-action-{index}"
                generated_modules[key] = {
                    "format": node.label, "tooltip": False,
                    "on-click": PANEL_ACTION_COMMANDS[str(node.value)],
                }
                generated_css.append(
                    f"#custom-rice-action-{index} {{ background: {recipe.colors[2]}; "
                    f"border-radius: {radius}px; min-width: {len(node.label) * 8 + 8}px; "
                    f"padding: 0 {padding}px; }}")
            elif node.kind == "control":
                # Waybar cannot share RicePlate's verified worker or its result
                # feedback. This is visibly disabled, never a fake toggle.
                key = f"custom/rice-control-{index}"
                generated_modules[key] = {
                    "format": f"{node.label} (N/A)",
                    "tooltip": True,
                    "tooltip-format": "Requires native RicePlate (Wayland)",
                }
                generated_css.append(
                    f"#custom-rice-control-{index} {{ opacity: 0.55; "
                    f"padding: 0 {padding}px; }}")
            else:
                key = f"custom/rice-label-{index}"
                generated_modules[key] = {"format": str(node.value), "tooltip": False}
                generated_css.append(f"#custom-rice-label-{index} {{ min-width: {len(str(node.value)) * 8}px; padding: 0 {padding}px; }}")
            return [key]

        section_modules = [[name for node in nodes for name in generate_node(node)]
                           for nodes in layout]
    config: dict[str, Any] = {
        "layer": "top", "position": recipe.position, "height": recipe.height,
        "spacing": 0 if layout is not None else 8,
        **{f"modules-{side}": names
           for side, names in zip(("left", "center", "right"), section_modules)},
        "wlr/taskbar": {"format": "{icon}", "icon-size": 22,
                        "on-click": "minimize-raise", "tooltip-format": "{title}"},
        "custom/rice-launcher": {"format": "◈", "on-click": "fuzzel",
                                 "tooltip": True, "tooltip-format": "Applications"},
        "clock": {"format": "{:%a %d %b  %H:%M}"},
        **generated_modules,
    }
    background, foreground, active = recipe.colors
    if recipe.design is not None:
        opacity = recipe.design[0]
        rgb = tuple(int(background[i:i+2], 16) for i in (1, 3, 5))
        background = f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {opacity / 100:.2f})"
    css = (
        "* { font-family: sans-serif; font-size: 12px; }\n"
        f"window#waybar {{ background: {background}; color: {foreground}; }}\n"
        f"#taskbar button {{ border-radius: {radius}px; padding: 2px 7px; }}\n"
        f"#taskbar button.active {{ background: {active}; }}\n"
        "#clock, #network, #pulseaudio, #battery, #tray, #custom-rice-launcher "
        "{ padding: 0 8px; }\n"
    )
    if recipe.metrics is not None:
        launcher_width, task_width, clock_width = recipe.metrics
        css += (
            # GTK min-width excludes padding; account for padding already set above.
            f"#custom-rice-launcher {{ min-width: {launcher_width - 16}px; }}\n"
            f"#taskbar button {{ min-width: {task_width - 14}px; }}\n"
            f"#clock {{ min-width: {clock_width - 16}px; }}\n"
        )
    if generated_css:
        css += "\n".join(generated_css) + "\n"
    return json.dumps(config, ensure_ascii=False, indent=2), css


def wallpaper_path(recipe: PanelRecipe) -> Path:
    """Resolve bundled or private SHA-256 artwork, never recipe-supplied paths."""
    name = recipe.wallpaper or "aero-seven-blue"
    if recipe.schema_version >= 6:
        from . import assets
        if assets.ASSET_ID.fullmatch(name):
            try:
                return assets.read(name)[0]  # Re-verify bytes before use by swaybg.
            except assets.AssetError as exc:
                raise RecipeError("Private wallpaper asset is missing or unsafe") from exc
    if name not in WALLPAPERS:
        raise RecipeError("Unknown bundled wallpaper")
    return Path(__file__).resolve().parents[2] / "assets" / "wallpapers" / f"{name}.jpg"


def labwc_menu(recipe: PanelRecipe) -> str:
    """Compile the restricted menu vocabulary into real labwc root-menu XML.

    No string from a rice is ever interpreted as a command or XML markup.
    """
    if recipe.menu is None:
        raise RecipeError("Legacy panel recipe has no custom labwc menu")
    title, groups = recipe.menu
    root = ET.Element("openbox_menu")
    menu = ET.SubElement(root, "menu", {"id": "root-menu", "label": title})
    action_specs = {
        "applications": ("Applications", "Execute", "fuzzel"),
        "terminal": ("Terminal", "Execute", "foot"),
        "settings": ("RiceSpice settings", "Execute", "ricebowl de settings"),
        "lock": ("Lock screen", "Execute", "swaylock -f"),
        "logout": ("Log out of RiceBowl", "Exit", None),
    }
    for index, group in enumerate(groups):
        # RiceSpice quick actions belong to native RicePlate's bounded worker;
        # Waybar/labwc fallback does not pretend to provide an equivalent.
        supported = [action for action in group.actions if action in action_specs]
        if not supported:
            continue
        if menu.findall("menu"):
            ET.SubElement(menu, "separator")
        submenu = ET.SubElement(menu, "menu", {"id": f"rice-group-{index}",
                                                 "label": group.title})
        for action_id in supported:
            label, action, command = action_specs[action_id]
            item = ET.SubElement(submenu, "item", {"label": label})
            attributes = {"name": action}
            if command is not None:
                attributes["command"] = command
            ET.SubElement(item, "action", attributes)
    if not any("logout" in group.actions for group in groups):
        # A broken/mockup menu must never remove the only visible safe exit.
        ET.SubElement(menu, "separator")
        emergency = ET.SubElement(menu, "item", {"label": "Log out of RiceBowl"})
        ET.SubElement(emergency, "action", {"name": "Exit"})
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode", short_empty_elements=True) + "\n"

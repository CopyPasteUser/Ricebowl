"""Pure, validated 2-D authoring operations for the optional Rice Creator.

The GTK canvas is a schematic input surface, not a second shell renderer. All
changes go through the same versioned recipe parser used by native RicePlate.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from . import recipes


class LayoutError(ValueError):
    """A requested desktop edit does not satisfy the Runtime contract."""


@dataclass(frozen=True)
class Viewport:
    x: float
    y: float
    width: float
    height: float
    scale: float

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        return (round((x - self.x) / self.scale),
                round((y - self.y) / self.scale))

    def to_canvas(self, x: int, y: int) -> tuple[float, float]:
        return self.x + x * self.scale, self.y + y * self.scale


def fit_viewport(width: int, height: int, screen_width: int, screen_height: int,
                 *, margin: int = 18) -> Viewport:
    """Letterbox a real output geometry without distorting recipe coordinates."""
    if min(width, height, screen_width, screen_height) <= 0 or margin < 0:
        raise LayoutError("Canvas and output dimensions must be positive")
    inset = min(margin, (width - 1) / 2, (height - 1) / 2)
    scale = min((width - inset * 2) / screen_width,
                (height - inset * 2) / screen_height)
    w, h = screen_width * scale, screen_height * scale
    return Viewport((width - w) / 2, (height - h) / 2, w, h, scale)


def _validate(manifest: dict[str, Any]) -> dict[str, Any]:
    try:
        recipes.parse(json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
    except (recipes.RecipeError, TypeError, ValueError) as exc:
        raise LayoutError(str(exc)) from exc
    return manifest


def layer_label(manifest: dict[str, Any], layer: str, index: int) -> str:
    if layer == "region":
        return "▧  Reserved application area"
    if layer == "icon":
        item = manifest["desktop"]["icons"][index]
        return f"◇  {item['label']} · {item['action']}"
    item = manifest["composition"]["widgets"][index]
    if item["kind"] == "text":
        return f"▤  {item['text']}"
    if item["kind"] == "component":
        role = next((component["role"] for component in manifest.get("components", [])
                     if component["id"] == item["ref"]), "component")
        return f"◈  {item['ref']} · {role}"
    return f"▣  {item['id']} · {item['kind']}"


def hit_test(manifest: dict[str, Any], x: int, y: int,
             screen_width: int, screen_height: int) -> tuple[str, int] | None:
    """Prefer small selectable layers to the larger reserved window rectangle."""
    for index in reversed(range(len(manifest["composition"]["widgets"]))):
        widget = manifest["composition"]["widgets"][index]
        if (widget["x"] <= x <= widget["x"] + recipes.DESKTOP_WIDGET_WIDTH and
                widget["y"] <= y <= widget["y"] + recipes.DESKTOP_WIDGET_HEIGHT):
            return "widget", index
    for index in reversed(range(len(manifest["desktop"]["icons"]))):
        icon = manifest["desktop"]["icons"][index]
        if (icon["x"] <= x <= icon["x"] + recipes.ICON_WIDTH and
                icon["y"] <= y <= icon["y"] + recipes.ICON_HEIGHT):
            return "icon", index
    region = manifest["composition"]["window_region"]
    left, top = region["x"] * screen_width / 100, region["y"] * screen_height / 100
    right = left + region["width"] * screen_width / 100
    bottom = top + region["height"] * screen_height / 100
    return ("region", 0) if left <= x <= right and top <= y <= bottom else None


def edit_layer(manifest: dict[str, Any], layer: str, index: int,
               changes: dict[str, Any]) -> dict[str, Any]:
    """Copy, update an allowlisted layer property and validate the *whole* rice."""
    permitted = ({"widget": {"x", "y", "text"},
                  "icon": {"x", "y", "label", "action"},
                  "region": {"x", "y", "width", "height"}}).get(layer)
    if permitted is None or not changes or not changes.keys() <= permitted:
        raise LayoutError("Unsupported desktop layer property")
    if index < 0 or (layer == "region" and index != 0):
        raise LayoutError("Layer no longer exists")
    result = copy.deepcopy(manifest)
    try:
        item = (result["composition"]["window_region"] if layer == "region" else
                result["composition"]["widgets"][index] if layer == "widget" else
                result["desktop"]["icons"][index])
    except (IndexError, KeyError, TypeError) as exc:
        raise LayoutError("Layer no longer exists") from exc
    if layer == "widget" and "text" in changes and item["kind"] != "text":
        raise LayoutError("Only static text widgets can change their text")
    item.update(changes)
    return _validate(result)


def set_compact_hidden(manifest: dict[str, Any], index: int, hidden: bool) -> dict[str, Any]:
    result = copy.deepcopy(manifest)
    try:
        widget_id = result["composition"]["widgets"][index]["id"]
    except (IndexError, KeyError, TypeError) as exc:
        raise LayoutError("Layer no longer exists") from exc
    hidden_ids = result["composition"]["compact_hide_widgets"]
    if hidden and widget_id not in hidden_ids:
        hidden_ids.append(widget_id)
    elif not hidden and widget_id in hidden_ids:
        hidden_ids.remove(widget_id)
    return _validate(result)


def add_layer(manifest: dict[str, Any], kind: str) -> dict[str, Any]:
    """Add an implemented static/status widget or known desktop action only."""
    result = copy.deepcopy(manifest)
    if kind.startswith("icon:"):
        action = kind.partition(":")[2]
        if action not in recipes.ICON_ACTIONS:
            raise LayoutError("Unknown desktop shortcut action")
        icons = result["desktop"]["icons"]
        if len(icons) >= recipes.MAX_DESKTOP_ICONS:
            raise LayoutError("This rice already has eight desktop shortcuts")
        for row in range(12):
            for col in range(7):
                x, y = 24 + col * 140, 92 + row * 116
                if all(abs(x - icon["x"]) >= recipes.ICON_WIDTH or
                       abs(y - icon["y"]) >= recipes.ICON_HEIGHT for icon in icons):
                    label = {"applications": "Apps", "terminal": "Terminal",
                             "lock": "Lock", "trash": "Recycle Bin"}[action]
                    # Keep desktop labels distinct for easy layer selection.
                    labels = {icon["label"] for icon in icons}
                    if label in labels:
                        label = f"{label} {len(icons) + 1}"
                    icons.append({"label": label, "action": action, "x": x, "y": y})
                    return _validate(result)
        raise LayoutError("No free desktop shortcut position")
    widgets = result["composition"]["widgets"]
    if len(widgets) >= recipes.MAX_DESKTOP_WIDGETS:
        raise LayoutError("This rice already has four desktop widgets")
    if kind.startswith("component:"):
        ref = kind.partition(":")[2]
        definitions = {item["id"]: item for item in result["components"]}
        if ref not in definitions or definitions[ref]["role"] not in ("status", "action"):
            raise LayoutError("Only validated status/action components can appear on the desktop")
        new = {"kind": "component", "ref": ref}
        stem = definitions[ref]["role"]
    elif kind in recipes.DESKTOP_WIDGET_KINDS:
        new = {"kind": kind}
        if kind == "text":
            new["text"] = "NEW TEXT"
        stem = kind
    else:
        raise LayoutError("Unsupported desktop widget")
    names = {item["id"] for item in widgets}
    for index in range(1, 100):
        candidate = f"desk-{stem}-{index}"
        if candidate not in names:
            new["id"] = candidate
            break
    new["x"], new["y"] = 24, 304 + len(widgets) * 112
    widgets.append(new)
    return _validate(result)


def remove_layer(manifest: dict[str, Any], layer: str, index: int) -> dict[str, Any]:
    if layer not in ("widget", "icon"):
        raise LayoutError("Reserved application area cannot be deleted")
    result = copy.deepcopy(manifest)
    target = result["composition"]["widgets"] if layer == "widget" else result["desktop"]["icons"]
    if not 0 <= index < len(target):
        raise LayoutError("Layer no longer exists")
    if layer == "icon" and len(target) <= 1:
        raise LayoutError("At least one desktop shortcut is required")
    removed = target.pop(index)
    if layer == "widget":
        hidden = result["composition"]["compact_hide_widgets"]
        if removed["id"] in hidden:
            hidden.remove(removed["id"])
    return _validate(result)


def move_layer(manifest: dict[str, Any], layer: str, index: int,
               x: float, y: float, screen_width: int, screen_height: int,
               *, snap: int = 1) -> dict[str, Any]:
    """Move on the schematic screen; keep all positions inside output geometry."""
    if layer not in ("widget", "icon", "region") or snap <= 0:
        raise LayoutError("Unknown movable desktop layer")
    if layer == "region":
        region = manifest["composition"]["window_region"]
        nx = round(x / screen_width * 100)
        ny = round(y / screen_height * 100)
        return edit_layer(manifest, layer, 0, {
            "x": max(0, min(nx, 100 - region["width"])),
            "y": max(0, min(ny, 100 - region["height"])),
        })
    w, h = ((recipes.ICON_WIDTH, recipes.ICON_HEIGHT) if layer == "icon" else
            (recipes.DESKTOP_WIDGET_WIDTH, recipes.DESKTOP_WIDGET_HEIGHT))
    min_y = 72 if layer == "icon" else 0
    nx = max(0, min(round(x / snap) * snap, min(4096 if layer == "icon" else 16_384,
                                                  screen_width - w)))
    ny = max(min_y, min(round(y / snap) * snap, min(4096 if layer == "icon" else 16_384,
                                                      max(min_y, screen_height - h))))
    return edit_layer(manifest, layer, index, {"x": nx, "y": ny})

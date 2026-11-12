"""JSON Schema 2020-12 for the bounded, data-only Creator edit vocabulary.

The full RicePlate parser remains authoritative for global invariants such as
cross-region widget uniqueness, existing component references and icon overlap.
No network, executable code or extra runtime dependency is needed to emit the
schema. Optional JSON Schema tooling can validate proposals before preflight.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import recipes
from .creator_contract import EDIT_VERSION, MAX_OPERATIONS

SCHEMA_VERSION = 1
_SAFE_LABEL_CHARACTERS = r"[^A-Za-z0-9 ._:+-]"


def _integer(lower: int, upper: int) -> dict[str, Any]:
    return {"type": "integer", "minimum": lower, "maximum": upper}


def _label(maximum: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": maximum,
            "not": {"pattern": _SAFE_LABEL_CHARACTERS}}


def _identifier() -> dict[str, Any]:
    return {"type": "string", "minLength": 2, "maxLength": 24,
            "pattern": "^[a-z]", "not": {"pattern": "[^a-z0-9-]"}}


def _color() -> dict[str, Any]:
    return {"type": "string", "minLength": 7, "maxLength": 7,
            "pattern": r"^#[0-9a-fA-F]{6}"}


def _content_addressed(prefix: str, *, luna: bool = False,
                       luna_font: bool = False) -> dict[str, Any]:
    length = len(prefix) + 1 + 64
    choices: list[dict[str, Any]] = [{"const": "builtin"}]
    if luna:
        choices.append({"const": "builtin-luna"})
    if luna_font:
        choices.append({"const": "builtin-luna-ui"})
    choices.append({"type": "string", "minLength": length, "maxLength": length,
                    "pattern": f"^{prefix}-[0-9a-f]{{64}}"})
    return {"anyOf": choices}


def _object(properties: dict[str, Any], *, required: tuple[str, ...] | None = None
            ) -> dict[str, Any]:
    return {"type": "object", "properties": properties,
            "required": list(required if required is not None else properties),
            "additionalProperties": False}


def _array(item: dict[str, Any], lower: int, upper: int, *, unique: bool = False
           ) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "array", "items": item,
                              "minItems": lower, "maxItems": upper}
    if unique:
        result["uniqueItems"] = True
    return result


def _layout_definitions(schema_version: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for depth in (3, 2, 1):
        nodes = [
            _object({"type": {"const": "widget"}, "id": {"enum": sorted(recipes.WIDGETS)}}),
            _object({"type": {"const": "gap"}, "width": _integer(4, 64)}),
            _object({"type": {"const": "divider"}, "width": _integer(6, 32)}),
            _object({"type": {"const": "label"}, "text": _label(24)}),
        ]
        if schema_version >= 6:
            nodes.append(_object({"type": {"const": "action"},
                                  "id": {"enum": sorted(recipes.PANEL_ACTIONS)},
                                  "label": _label(16)}))
        if schema_version >= 7:
            nodes.append(_object({"type": {"const": "control"},
                                  "id": {"enum": sorted(recipes.PANEL_CONTROLS)},
                                  "label": _label(16)}))
        if schema_version >= 9:
            nodes.append(_object({"type": {"const": "component"},
                                  "ref": _identifier()}))
        if depth < recipes.MAX_LAYOUT_DEPTH:
            nodes.append(_object({"type": {"const": "group"}, "gap": _integer(0, 32),
                                  "children": _array({"$ref": f"#/$defs/layout{depth + 1}"},
                                                     1, recipes.MAX_LAYOUT_CHILDREN)}))
        result[f"layout{depth}"] = {"oneOf": nodes}
    return result


def _properties(schema_version: int) -> dict[str, dict[str, Any]]:
    properties: dict[str, dict[str, Any]] = {
        "/name": {"type": "string", "minLength": 1, "maxLength": 60,
                  "not": {"pattern": r"[\x00-\x1F\x7F-\x9F]"}},
        "/panel/position": {"enum": ["top", "bottom"]},
        "/panel/height": _integer(28, 64),
    }
    for color in recipes.COLORS:
        properties[f"/colors/{color}"] = _color()
    if schema_version <= 2:
        for section in recipes.SECTIONS:
            properties[f"/panel/sections/{section}"] = _array(
                {"enum": sorted(recipes.WIDGETS)}, 0, 7, unique=True)
    if schema_version >= 2:
        for field, (minimum, maximum) in zip(recipes.METRIC_FIELDS, recipes.METRIC_LIMITS):
            properties[f"/panel/metrics/{field}"] = _integer(minimum, maximum)
    if schema_version >= 3:
        for section in recipes.SECTIONS:
            properties[f"/panel/layout/{section}"] = _array(
                {"$ref": "#/$defs/layout1"}, 0, recipes.MAX_LAYOUT_ROOTS)
    if schema_version < 4:
        return properties

    menu_content = _object({"type": {"enum": ["actions", "favorites", "apps-list", "apps-grid"]},
                            "title": _label(24), "limit": _integer(1, 4)})
    menu_fields: dict[str, Any] = {
        "title": _label(24),
        "actions": _array({"enum": sorted(recipes.MENU_ACTIONS)}, 1, 4, unique=True),
    }
    if schema_version >= 6:
        menu_fields["content"] = _array(menu_content, 1, 2)
    properties["/menu/groups"] = _array(_object(
        menu_fields, required=("title", "actions")), 1, 4)
    properties["/menu/title"] = _label(32)
    if schema_version >= 6:
        properties["/menu/presentation"] = {"enum": ["tabs", "sidebar"]
                                            + (["columns"] if schema_version >= 12 else [])}
    wallpaper: dict[str, Any] = {"enum": sorted(recipes.WALLPAPERS)}
    if schema_version >= 6:
        wallpaper = {"anyOf": [wallpaper, {"type": "string",
                                         "minLength": 70, "maxLength": 70,
                                         "pattern": r"^asset-[0-9a-f]{64}"}]}
    properties["/desktop/wallpaper"] = wallpaper
    properties["/tokens/label_padding"] = _integer(0, 16)
    properties["/tokens/task_radius"] = _integer(0, 12)
    properties["/responsive/compact_max_width"] = _integer(480, 1440)
    for section in recipes.SECTIONS:
        properties[f"/responsive/compact_layout/{section}"] = _array(
            {"$ref": "#/$defs/layout1"}, 0, recipes.MAX_LAYOUT_ROOTS)
    if schema_version >= 5:
        properties["/desktop/icons"] = _array(_object({
            "label": _label(12), "action": {"enum": sorted(recipes.ICON_ACTIONS)},
            "x": _integer(0, 4096), "y": _integer(72, 4096),
        }), 1, recipes.MAX_DESKTOP_ICONS)
    if schema_version >= 8:
        fields = {"id": _identifier(),
                  "x": _integer(0, 16384), "y": _integer(0, 16384)}
        nodes: list[dict[str, Any]] = [
            _object({**fields, "kind": {"enum": ["clock", "date", "system"]}}),
        ]
        if schema_version >= 9:
            nodes.extend((
                _object({**fields, "kind": {"const": "text"}, "text": _label(22)}),
                _object({**fields, "kind": {"const": "component"},
                         "ref": _identifier()}),
            ))
        properties["/composition/widgets"] = _array(
            {"oneOf": nodes}, 0, recipes.MAX_DESKTOP_WIDGETS)
        properties["/composition/window_region"] = _object({
            "x": _integer(0, 99), "y": _integer(0, 99),
            "width": _integer(1, 100), "height": _integer(1, 100),
        })
        properties["/composition/compact_hide_widgets"] = _array(
            _identifier(),
            0, recipes.MAX_DESKTOP_WIDGETS, unique=True)
    if schema_version >= 9:
        component = _object({
            "id": _identifier(),
            "role": {"enum": ["status", "action"]},
            "binding": {"type": "string"}, "label": _label(16),
        })
        component["allOf"] = [{"if": {"properties": {"role": {"const": "status"}}},
                               "then": {"properties": {"binding": {
                                   "enum": sorted(recipes.COMPONENT_STATUS_BINDINGS)}}},
                               "else": {"properties": {"binding": {
                                   "enum": sorted(recipes.PANEL_ACTIONS | recipes.PANEL_CONTROLS)}}}}]
        properties["/components"] = _array(component, 1, recipes.MAX_COMPONENT_DEFINITIONS)
    if schema_version >= 10:
        for token in ("hover", "focus", "disabled"):
            properties[f"/appearance/{token}"] = _color()
        properties["/appearance/font_scale"] = {"enum": [1, 2]}
        properties["/appearance/font_weight"] = {"enum": ["regular", "bold"]}
        properties["/appearance/item_spacing"] = _integer(0, 16)
    if schema_version >= 11:
        font = _content_addressed("font", luna_font=schema_version >= 12)
        icon = _content_addressed("icon", luna=schema_version >= 12)
        properties["/artwork/font"] = font
        # Desktop action IDs and importable artwork slots are separate:
        # trash uses original in-engine art, while the three existing icon
        # imports keep their fixed-size/native Rust loading contract.
        from .style_assets import ICON_ACTIONS as ARTWORK_ICON_ACTIONS
        properties["/artwork/icons"] = _object({key: icon for key in ARTWORK_ICON_ACTIONS})
        for key in ARTWORK_ICON_ACTIONS:
            properties[f"/artwork/icons/{key}"] = icon
    if schema_version >= 12:
        launcher = {"label": _label(16), "background": _color(),
                    "foreground": _color(), "radius": _integer(0, 20)}
        properties["/panel/launcher"] = _object(launcher)
        for key, spec in launcher.items():
            properties[f"/panel/launcher/{key}"] = spec
        menu_palette = {key: _color() for key in
                        ("background", "foreground", "header", "header_foreground", "selection")}
        properties["/menu/colors"] = _object(menu_palette)
        for key, spec in menu_palette.items():
            properties[f"/menu/colors/{key}"] = spec
    return properties


def describe(schema_version: int) -> dict[str, Any]:
    """Return a standalone, read-only edit JSON Schema for one recipe version."""
    if type(schema_version) is not int or not 1 <= schema_version <= 12:
        raise ValueError("Creator edit schema requires recipe schema v1–v12")
    properties = _properties(schema_version)
    alternatives = [_object({"op": {"const": "set"}, "path": {"const": path},
                             "value": constraint})
                    for path, constraint in sorted(properties.items())]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"RiceBowl Creator edit schema for recipe v{schema_version}",
        "type": "object", "properties": {
            "edit_version": {"const": EDIT_VERSION},
            "operations": _array({"oneOf": alternatives}, 1, MAX_OPERATIONS),
        },
        "required": ["edit_version", "operations"],
        "additionalProperties": False,
        "$defs": _layout_definitions(schema_version) if schema_version >= 3 else {},
        "x-ricebowl-schema-contract": SCHEMA_VERSION,
        "x-ricebowl-recipe-version": schema_version,
        "x-ricebowl-runtime-validation": (
            "Required: full recipe parser checks cross-property references, total node limits, "
            "widget/action uniqueness, icon overlap, region bounds and final composition"),
    }


def fingerprint(schema: dict[str, Any]) -> str:
    """Stable digest of the machine-readable authoring contract, not a recipe."""
    canonical = json.dumps(schema, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

"""Read-only Creator-to-RicePlate contract inventory for validated recipes.

This reports *declared* capabilities and logical coordinates. It does not
pretend a Python review executed the Rust parser, compositor or input stack.
The same manifest used for reviewed installation is the sole source of nodes.
"""

from __future__ import annotations

import json
from typing import Any

from . import catalog, recipes, review

PARITY_VERSION = 1
OUTPUT_CASES = (
    ("small", 640, 480, 1.0),
    ("laptop", 1366, 768, 1.0),
    ("desktop", 1920, 1080, 1.0),
    ("fractional", 1366, 768, 1.25),
    ("second-monitor", 1024, 768, 1.0),
)


def describe(recipe_token: str) -> dict[str, Any]:
    """Inventory one validated rice. Never starts preview or changes selection."""
    inspected = review.review(recipe_token)
    recipe = inspected["recipe"]
    support = catalog.describe()
    widgets = {item["id"]: item for item in support["components"]}
    definitions = {item["id"]: item for item in recipe.get("components", [])}
    rows: list[dict[str, Any]] = []

    def add(area: str, path: str, kind: str, binding: str, label: str,
            native: str, waybar: str, role: str) -> None:
        interactive = role in ("button", "conditional-button", "menuitem")
        rows.append({
            "area": area, "path": path, "kind": kind, "binding": binding,
            "label": label, "interactive": interactive,
            "accessibility": role, "native_contract": native,
            "waybar_contract": waybar,
            "runtime_evidence": "contract-only-not-a-render-or-input-test",
            "allowed_action": binding if interactive else None,
            "state_contract": (
                ["unavailable", "ready", "pending", "success", "failed"]
                if role == "conditional-button" else
                ["ready", "unavailable", "failed"] if interactive else
                ["available", "unavailable"] if role == "status" else []
            ),
        })

    def walk(nodes: list[dict], area: str, path: str) -> None:
        for i, node in enumerate(nodes):
            current = f"{path}/{i}"
            kind = node["type"]
            if kind == "group":
                walk(node["children"], area, f"{current}/children")
            elif kind == "component":
                component = definitions[node["ref"]]
                if component["role"] == "status":
                    widget = widgets[component["binding"]]
                    add(area, current, kind, component["binding"], component["label"],
                        widget["native"], widget["waybar"], "status")
                else:
                    bound = component["binding"]
                    role = "conditional-button" if bound in recipes.PANEL_CONTROLS else "button"
                    add(area, current, kind, bound, component["label"],
                        "validated-native-action", "fixed-action-or-disabled", role)
            elif kind == "widget":
                item = widgets[node["id"]]
                role = ("button" if node["id"] in ("launcher", "tasks", "clock", "tray")
                        else "status")
                add(area, current, kind, node["id"], node["id"],
                    item["native"], item["waybar"], role)
            elif kind in ("action", "control"):
                add(area, current, kind, node["id"], node["label"],
                    "validated-native-action", "fixed-action-or-disabled",
                    "conditional-button" if kind == "control" else "button")
            elif kind in ("label", "gap", "divider"):
                add(area, current, kind, "", node.get("text", ""),
                    "static", "static", "text" if kind == "label" else "decorative")

    panel = recipe["panel"]
    if "sections" in panel:
        for section in recipes.SECTIONS:
            for i, widget_id in enumerate(panel["sections"][section]):
                widget = widgets[widget_id]
                add("panel-wide", f"/panel/sections/{section}/{i}", "widget",
                    widget_id, widget_id, widget["native"], widget["waybar"],
                    "button" if widget_id in ("launcher", "tasks", "clock", "tray") else "status")
    else:
        for section in recipes.SECTIONS:
            walk(panel["layout"][section], "panel-wide", f"/panel/layout/{section}")
        for section in recipes.SECTIONS:
            walk(recipe["responsive"]["compact_layout"][section], "panel-compact",
                 f"/responsive/compact_layout/{section}")

    if "menu" in recipe:
        for i, group in enumerate(recipe["menu"]["groups"]):
            for j, action in enumerate(group["actions"]):
                add("menu", f"/menu/groups/{i}/actions/{j}", "menu-action", action,
                    action, "validated-native-menu", "labwc-root-menu", "menuitem")
        for i, icon in enumerate(recipe["desktop"].get("icons", [])):
            add("desktop", f"/desktop/icons/{i}", "shortcut", icon["action"],
                icon["label"], "native-layer-surface", "not-available", "button")

    for i, item in enumerate(recipe.get("composition", {}).get("widgets", [])):
        if item["kind"] == "component":
            component = definitions[item["ref"]]
            action = component["role"] == "action"
            add("desktop", f"/composition/widgets/{i}", "component",
                component["binding"], component["label"],
                "native-status-or-action", "not-available",
                ("conditional-button" if component["binding"] in recipes.PANEL_CONTROLS
                 else "button") if action else "status")
        else:
            add("desktop", f"/composition/widgets/{i}", item["kind"],
                item["kind"], item.get("text", item["kind"]),
                "native-read-only", "not-available",
                "text" if item["kind"] == "text" else "status")

    # These bindings have already passed the authoritative Python validator.
    # Fail closed if a future authoring surface advertises an action not
    # represented in the bounded runtime contract.
    for row in rows:
        if not row["interactive"]:
            continue
        identifier = row["binding"]
        if row["kind"] == "shortcut":
            allowed = recipes.ICON_ACTIONS
        elif row["kind"] == "menu-action":
            allowed = recipes.MENU_ACTIONS
        elif row["kind"] == "widget":
            allowed = {"launcher", "tasks", "clock", "tray"}
        else:
            allowed = recipes.PANEL_ACTIONS | recipes.PANEL_CONTROLS
        if identifier not in allowed:
            raise ValueError("Creator contract contains an unsupported interactive binding")

    outputs = []
    composition = recipe.get("composition")
    icons = recipe.get("desktop", {}).get("icons", [])
    for name, physical_width, physical_height, scale in OUTPUT_CASES:
        logical_width = round(physical_width / scale)
        logical_height = round(physical_height / scale)
        compact = bool("responsive" in recipe and
                       logical_width <= recipe["responsive"]["compact_max_width"])
        hidden = set(composition["compact_hide_widgets"]) if compact and composition else set()
        warnings = []
        declared_items: list[tuple[str, int, int, int, int]] = []

        def bounds(path: str, x: int, y: int, width: int, height: int) -> None:
            declared_items.append((path, x, y, x + width, y + height))
            if x + width > logical_width or y + height > logical_height:
                warnings.append({"path": path, "code": "declared-outside-logical-output"})
            panel_height = panel["height"]
            if ((panel["position"] == "top" and y < panel_height) or
                    (panel["position"] == "bottom" and y + height > logical_height - panel_height)):
                warnings.append({"path": path, "code": "declared-overlaps-panel"})

        for i, icon in enumerate(icons):
            bounds(f"/desktop/icons/{i}", icon["x"], icon["y"],
                   recipes.ICON_WIDTH, recipes.ICON_HEIGHT)
        if composition:
            for i, widget in enumerate(composition["widgets"]):
                if widget["id"] not in hidden:
                    bounds(f"/composition/widgets/{i}", widget["x"], widget["y"],
                           recipes.DESKTOP_WIDGET_WIDTH, recipes.DESKTOP_WIDGET_HEIGHT)
        # Report potential declared overlaps independently of native
        # placement; runtime output reflow may resolve a collision.
        for index, (left_path, left_x1, left_y1, left_x2, left_y2) in enumerate(declared_items):
            for right_path, right_x1, right_y1, right_x2, right_y2 in declared_items[index + 1:]:
                if (left_x1 < right_x2 and right_x1 < left_x2
                        and left_y1 < right_y2 and right_y1 < left_y2):
                    warnings.append({"path": left_path, "other_path": right_path,
                                     "code": "declared-element-overlap"})
        outputs.append({
            "case": name, "physical": [physical_width, physical_height],
            "scale": scale, "logical": [logical_width, logical_height],
            "panel_mode": "compact" if compact else "wide",
            "hidden_desktop_widgets": sorted(hidden),
            "declared_geometry_warnings": warnings,
            "native_reflow_and_visibility": "not_verified_requires_real_capture",
        })

    return {
        "parity_version": PARITY_VERSION,
        "recipe": {"id": recipe["id"], "schema_version": recipe["schema_version"],
                   "semantic_sha256": inspected["summary"]["semantic_sha256"]},
        "python_validation": "passed",
        "rust_parser_execution": "not_performed",
        "native_render_execution": "not_performed",
        "real_input_accessibility_validation": "not_performed",
        "components": rows, "output_cases": outputs,
        "limitations": [
            "No custom shell commands, arbitrary script widgets, or plugin execution",
            "No vertical or floating panels; one logical-width breakpoint",
            "Panel group alignment and overflow must be checked with native captures",
            "Desktop coordinates are declarations; the compositor can reflow them",
            "No physical keyboard, screen reader, multi-monitor hotplug or suspend sign-off",
        ],
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", help="Validated built-in ID or owner-private recipe file")
    args = parser.parse_args()
    try:
        data = describe(args.recipe)
    except (recipes.RecipeError, OSError, ValueError):
        print(json.dumps({"ok": False, "error": "invalid_or_unsupported_recipe"}))
        return 2
    print(json.dumps({"ok": True, "parity": data}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

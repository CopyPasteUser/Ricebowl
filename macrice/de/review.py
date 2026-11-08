"""Deterministic, read-only reviews of the implemented panel recipe schema.

Creator agents can inspect a recipe and compare it to a known-good base before
asking a human to start a nested preview. No untrusted fields are executed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import catalog, recipes

REVIEW_VERSION = 1


def _manifest(recipe: recipes.PanelRecipe) -> dict[str, Any]:
    """Stable semantic representation, independent of JSON whitespace/order."""
    panel: dict[str, Any] = {
        "position": recipe.position,
        "height": recipe.height,
    }
    if recipe.layout is None:
        panel["sections"] = dict(zip(recipes.SECTIONS,
                                     (list(part) for part in recipe.sections)))
    else:
        panel["layout"] = dict(zip(recipes.SECTIONS,
                                   ([recipes.layout_node_json(node) for node in part]
                                    for part in recipe.layout)))
    if recipe.metrics is not None:
        panel["metrics"] = dict(zip(recipes.METRIC_FIELDS, recipe.metrics))
    result = {
        "schema_version": recipe.schema_version,
        "id": recipe.recipe_id,
        "name": recipe.name,
        "panel": panel,
        "colors": dict(zip(recipes.COLORS, recipe.colors)),
    }
    if recipe.schema_version >= 4:
        assert recipe.menu is not None and recipe.tokens is not None
        assert recipe.compact is not None and recipe.wallpaper is not None
        result["menu"] = {"title": recipe.menu[0], "groups": [
            {**{"title": group.title, "actions": list(group.actions)},
             **({"content": [{"type": item.kind, "title": item.title, "limit": item.limit}
                             for item in group.content]} if group.content is not None else {})}
            for group in recipe.menu[1]]}
        if recipe.schema_version >= 6 and recipe.menu_presentation != "tabs":
            result["menu"]["presentation"] = recipe.menu_presentation
        result["desktop"] = {"wallpaper": recipe.wallpaper}
        if recipe.schema_version >= 5:
            assert recipe.desktop_icons is not None
            result["desktop"]["icons"] = [
                {"label": icon.label, "action": icon.action, "x": icon.x, "y": icon.y}
                for icon in recipe.desktop_icons]
        result["tokens"] = dict(zip(("label_padding", "task_radius"), recipe.tokens))
        result["responsive"] = {
            "compact_max_width": recipe.compact[0],
            "compact_layout": dict(zip(recipes.SECTIONS,
                ([recipes.layout_node_json(node) for node in nodes]
                 for nodes in recipe.compact[1]))),
        }
    if recipe.composition is not None:
        composition = recipe.composition
        result["composition"] = {
            "widgets": [{"id": widget.widget_id,
                         "kind": "component" if widget.component_ref else widget.kind,
                         **({"ref": widget.component_ref} if widget.component_ref else {}),
                         **({"text": widget.text} if widget.kind == "text" else {}),
                         "x": widget.x, "y": widget.y} for widget in composition.widgets],
            "window_region": {"x": composition.window_region.x,
                              "y": composition.window_region.y,
                              "width": composition.window_region.width,
                              "height": composition.window_region.height},
            "compact_hide_widgets": list(composition.compact_hide_widgets),
        }
    if recipe.schema_version >= 9:
        result["components"] = [
            {"id": component.component_id, "role": component.role,
             "binding": component.binding, "label": component.label}
            for component in recipe.components]
    if recipe.appearance is not None:
        from dataclasses import asdict
        result["appearance"] = asdict(recipe.appearance)
    return result


def _semantic_hash(manifest: dict[str, Any]) -> str:
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _fields(manifest: dict[str, Any]) -> dict[str, Any]:
    """Small, fixed vocabulary of reviewable JSON Pointer paths."""
    panel = manifest["panel"]
    result = {
        "/schema_version": manifest["schema_version"],
        "/id": manifest["id"],
        "/name": manifest["name"],
        "/panel/position": panel["position"],
        "/panel/height": panel["height"],
    }
    for section in recipes.SECTIONS:
        result[f"/panel/sections/{section}"] = panel.get("sections", {}).get(section)
        result[f"/panel/layout/{section}"] = panel.get("layout", {}).get(section)
    for field in recipes.METRIC_FIELDS:
        # An absent v1 metric differs from a v2 metric at its default.
        result[f"/panel/metrics/{field}"] = panel.get("metrics", {}).get(field)
    for color in recipes.COLORS:
        result[f"/colors/{color}"] = manifest["colors"][color]
    result["/menu/title"] = manifest.get("menu", {}).get("title")
    result["/menu/groups"] = manifest.get("menu", {}).get("groups")
    result["/menu/presentation"] = manifest.get("menu", {}).get("presentation", "tabs")
    result["/desktop/wallpaper"] = manifest.get("desktop", {}).get("wallpaper")
    result["/desktop/icons"] = manifest.get("desktop", {}).get("icons")
    for name in ("widgets", "window_region", "compact_hide_widgets"):
        result[f"/composition/{name}"] = manifest.get("composition", {}).get(name)
    result["/components"] = manifest.get("components")
    if "appearance" in manifest:
        for token in ("font_scale", "font_weight", "item_spacing",
                      "hover", "focus", "disabled"):
            result[f"/appearance/{token}"] = manifest["appearance"][token]
    for token in ("label_padding", "task_radius"):
        result[f"/tokens/{token}"] = manifest.get("tokens", {}).get(token)
    result["/responsive/compact_max_width"] = manifest.get("responsive", {}).get(
        "compact_max_width")
    for section in recipes.SECTIONS:
        result[f"/responsive/compact_layout/{section}"] = manifest.get(
            "responsive", {}).get("compact_layout", {}).get(section)
    return result


def _snapshot(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed = recipes.load(token)
    manifest = _manifest(parsed)
    component_support = {item["id"]: item for item in catalog.describe()["components"]}
    ordered = [widget for section in recipes.SECTIONS
               for widget in parsed.sections[recipes.SECTIONS.index(section)]]
    unavailable = [widget for widget in ordered
                   if component_support[widget]["native"] == "unavailable"]
    summary = {
        "id": manifest["id"],
        "schema_version": manifest["schema_version"],
        "semantic_sha256": _semantic_hash(manifest),
        "widgets": ordered,
        "native_unavailable_widgets": unavailable,
        "native_panel_complete": False,
        "requires_waybar_fallback_for_all_widgets": bool(unavailable),
    }
    return manifest, summary


def semantic_changes(base: dict[str, Any], target: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered, bounded diff shared by read-only reviews and draft authors."""
    old_fields = _fields(base)
    new_fields = _fields(target)
    return [{"path": key, "before": old_fields[key], "after": new_fields[key]}
            for key in old_fields if old_fields[key] != new_fields[key]]


def review(recipe_token: str, compare_token: str | None = None) -> dict[str, Any]:
    """Validate a source/base and report semantic changes without side effects."""
    catalog.validate_catalog_contract()
    target, target_summary = _snapshot(recipe_token)
    result: dict[str, Any] = {
        "review_version": REVIEW_VERSION,
        "scope": "wayland-shell-preview" if target["schema_version"] >= 4
                 else "wayland-panel-preview",
        "ok": True,
        "applied": False,
        "recipe": target,
        "summary": target_summary,
        "comparison": None,
    }
    if compare_token is not None:
        base, base_summary = _snapshot(compare_token)
        changes = semantic_changes(base, target)
        result["comparison"] = {
            "base_id": base["id"],
            "base_semantic_sha256": base_summary["semantic_sha256"],
            "changed": bool(changes),
            "changes": changes,
        }
    return result


def invalid_review() -> dict[str, Any]:
    """Stable, path-free machine response for inaccessible/invalid recipes."""
    return {
        "review_version": REVIEW_VERSION,
        "scope": "wayland-panel-preview",
        "ok": False,
        "applied": False,
        "error": {"code": "invalid_recipe", "message": "Invalid or unsafe panel recipe input"},
    }

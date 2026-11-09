"""Pure structural editing of existing, validated RicePlate v10 primitives.

Both the graphical Creator and AI-produced edit files use the same recipe
contract. All operations return detached data; the caller must explicitly
save a new private draft version before anything is persisted.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from . import recipes


class StructureError(ValueError):
    """An offline change would break the declarative runtime contract."""


def _verify(manifest: dict[str, Any]) -> None:
    try:
        recipes.parse(json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
    except (recipes.RecipeError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise StructureError(f"Unsupported recipe structure: {exc}") from exc


def _components(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema_version", 0) < 9:
        raise StructureError("Component library needs a schema-v9+ recipe")
    return copy.deepcopy(manifest["components"])


def component_uses(manifest: dict[str, Any], identifier: str) -> list[str]:
    """Show every wide/compact/desktop reference before a destructive removal."""
    found: list[str] = []

    def visit(nodes: list[dict[str, Any]], prefix: str) -> None:
        for index, node in enumerate(nodes):
            position = f"{prefix}/{index}"
            if node.get("type") == "component" and node.get("ref") == identifier:
                found.append(position)
            if node.get("type") == "group":
                visit(node["children"], position + "/children")

    for section in recipes.SECTIONS:
        visit(manifest["panel"]["layout"][section], f"panel/{section}")
        visit(manifest["responsive"]["compact_layout"][section], f"compact/{section}")
    for index, widget in enumerate(manifest["composition"]["widgets"]):
        if widget.get("kind") == "component" and widget.get("ref") == identifier:
            found.append(f"desktop/widget/{index}")
    return found


def edit_component(manifest: dict[str, Any], action: str,
                   definition: dict[str, Any] | None = None, *,
                   identifier: str | None = None) -> list[dict[str, Any]]:
    """Add, update or remove a stable component ID, with full reference checks."""
    components = _components(manifest)
    if action in ("add", "update"):
        if type(definition) is not dict:
            raise StructureError("Choose a valid component definition")
        try:
            recipes._parse_components([definition])
        except recipes.RecipeError as exc:
            raise StructureError(str(exc)) from exc
        if action == "add":
            if any(row["id"] == definition["id"] for row in components):
                raise StructureError("Component ID already exists")
            components.append(copy.deepcopy(definition))
        else:
            if identifier is None or definition["id"] != identifier:
                raise StructureError("Component IDs cannot be renamed; add a new ID instead")
            index = next((i for i, row in enumerate(components)
                          if row["id"] == identifier), None)
            if index is None:
                raise StructureError("Component to edit no longer exists")
            # A status can now become a *clickable* desktop action. Never
            # silently elevate an in-use component's interaction role: create
            # a new action ID and explicitly rebind the affected surfaces.
            if (components[index]["role"] != definition["role"]
                    and component_uses(manifest, identifier)):
                raise StructureError("In-use component role cannot change; add a new component")
            components[index] = copy.deepcopy(definition)
    elif action == "remove":
        if type(identifier) is not str or identifier not in {c["id"] for c in components}:
            raise StructureError("Component to remove no longer exists")
        used = component_uses(manifest, identifier)
        if used:
            raise StructureError("Component is still used by: " + ", ".join(used[:4]))
        components = [row for row in components if row["id"] != identifier]
    else:
        raise StructureError("Unsupported component operation")
    proposal = copy.deepcopy(manifest)
    proposal["components"] = components
    _verify(proposal)
    return components


def _parent(nodes: list[dict[str, Any]], path: tuple[int, ...]
            ) -> tuple[list[dict[str, Any]], int]:
    if not path or len(path) > recipes.MAX_LAYOUT_DEPTH:
        raise StructureError("Select a valid panel node")
    current = nodes
    for level, index in enumerate(path):
        if type(index) is not int or not 0 <= index < len(current):
            raise StructureError("Panel node has changed; select it again")
        if level == len(path) - 1:
            return current, index
        node = current[index]
        if node.get("type") != "group":
            raise StructureError("Only a group can contain nested elements")
        current = node["children"]
    raise StructureError("Invalid panel node")


def edit_layout(manifest: dict[str, Any], section: str, path: tuple[int, ...],
                action: str, *, node: dict[str, Any] | None = None,
                compact: bool = False) -> list[dict[str, Any]]:
    """Edit group children and leaves, including reversible grouping/ungrouping.

    `path=()` targets the lane for `add`; otherwise indices identify a node,
    traversing group children at every level. Never accepts JSON pointer text
    or arbitrary code; the runtime parser validates the entire resulting rice.
    """
    if section not in recipes.SECTIONS or type(path) is not tuple:
        raise StructureError("Unknown panel lane or element address")
    if manifest.get("schema_version", 0) < 10:
        raise StructureError("Visual structure editor needs a schema-v10 draft")
    proposal = copy.deepcopy(manifest)
    area = (proposal["responsive"]["compact_layout"] if compact else
            proposal["panel"]["layout"])
    roots = area[section]
    if action == "add":
        if type(node) is not dict:
            raise StructureError("Choose a known panel element")
        if path:
            parent, index = _parent(roots, path)
            group = parent[index]
            if group.get("type") != "group":
                raise StructureError("Select a group to add a child")
            target = group["children"]
        else:
            target = roots
        target.append(copy.deepcopy(node))
    else:
        parent, index = _parent(roots, path)
        current = parent[index]
        if action == "replace":
            if type(node) is not dict:
                raise StructureError("Choose a valid replacement element")
            parent[index] = copy.deepcopy(node)
        elif action == "remove":
            if current.get("type") == "group":
                raise StructureError("Ungroup its children before removing a group")
            parent.pop(index)
        elif action == "up" or action == "down":
            target = index + (-1 if action == "up" else 1)
            if not 0 <= target < len(parent):
                raise StructureError("Element is already at the lane boundary")
            parent[index], parent[target] = parent[target], parent[index]
        elif action == "wrap":
            if current.get("type") == "group":
                raise StructureError("Group is already a container")
            parent[index] = {"type": "group", "gap": 8, "children": [current]}
        elif action == "ungroup":
            if current.get("type") != "group":
                raise StructureError("Selected element is not a group")
            parent[index:index + 1] = current["children"]
        else:
            raise StructureError("Unsupported panel operation")
    _verify(proposal)
    return roots

"""Read-only typed shell bindings for Creator. No backend or command execution."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from . import recipes

CONTRACT_VERSION = 1
class Surface(str, Enum):
    PANEL = "panel"
    MENU = "menu"
    DESKTOP = "desktop"
class Kind(str, Enum):
    LAUNCH = "launch"
    PLACE = "place"
    SETTINGS = "settings"
    SESSION = "session"
    WINDOW = "window"
    CONTROL = "control"
    NOTIFICATION = "notification"
    DIALOG = "dialog"
class State(str, Enum):
    READY = "ready"
    APPLYING = "applying"
    BUSY = "busy"
    UNAVAILABLE = "unavailable"
    DENIED = "denied"
    FAILED = "failed"

_SURFACES = {
    Surface.PANEL: recipes.PANEL_ACTIONS | recipes.PANEL_CONTROLS,
    Surface.MENU: recipes.MENU_ACTIONS,
    Surface.DESKTOP: recipes.ICON_ACTIONS | recipes.PANEL_ACTIONS | recipes.PANEL_CONTROLS,
}
_CONTROL = recipes.PANEL_CONTROLS
_PLACE = frozenset(("documents","computer","pictures","music","network","trash"))
_SESSION = frozenset(("lock","logout"))
_DIALOG = frozenset(("help","run"))

@dataclass(frozen=True)
class Binding:
    action_id: str
    surface: Surface
    kind: Kind
    backend: str
@dataclass(frozen=True)
class Feedback:
    state: State
    @property
    def actionable(self) -> bool:
        return self.state in (State.READY, State.FAILED)

def kind_of(action_id: str) -> Kind:
    if action_id in _CONTROL:
        return Kind.CONTROL
    if action_id in _PLACE:
        return Kind.PLACE
    if action_id in _SESSION:
        return Kind.SESSION
    if action_id in _DIALOG:
        return Kind.DIALOG
    if action_id == "show-desktop":
        return Kind.WINDOW
    if action_id == "settings":
        return Kind.SETTINGS
    if action_id == "notifications":
        return Kind.NOTIFICATION
    return Kind.LAUNCH

def bind(action_id: str, surface: Surface) -> Binding:
    """Resolve a recipe token to an existing owner, rejecting arbitrary argv."""
    if type(action_id) is not str or type(surface) is not Surface:
        raise ValueError("Shell action requires a typed surface and literal ID")
    if action_id not in _SURFACES[surface]:
        raise ValueError("Unknown or unsupported shell action on this surface")
    kind = kind_of(action_id)
    backend = {
        Kind.CONTROL: "riceplate-control-worker",
        Kind.WINDOW: "riceplate-window-owner",
        Kind.SESSION: "ricebowl-session-owner",
        Kind.SETTINGS: "ricespice-gtk",
        Kind.NOTIFICATION: "ricepop-notifications",
    }.get(kind, "riceplate-action-dispatch")
    return Binding(action_id, surface, kind, backend)

def feedback(binding: Binding, *, backend_present: bool, capability_present: bool,
             permitted: bool = True, pending: str | None = None,
             failed: str | None = None) -> Feedback:
    """Project real external backend state; never optimistically claim success."""
    if not isinstance(binding, Binding):
        raise ValueError("Validated binding required")
    if not backend_present or not capability_present:
        return Feedback(State.UNAVAILABLE)
    if not permitted:
        return Feedback(State.DENIED)
    if pending == binding.action_id:
        return Feedback(State.APPLYING)
    if pending is not None:
        return Feedback(State.BUSY)
    if failed == binding.action_id:
        return Feedback(State.FAILED)
    return Feedback(State.READY)

def describe() -> dict[str, object]:
    actions = frozenset.union(*_SURFACES.values())
    return {
        "version": CONTRACT_VERSION,
        "executor": "existing-native-riceplate-dispatch",
        "arbitrary_commands": False,
        "dynamic_desktop_ids": "validated-against-discovered-xdg-apps-only",
        "surfaces": {surface.value: sorted(ids) for surface, ids in _SURFACES.items()},
        "actions": [{"id": name, "kind": kind_of(name).value,
                     "surfaces": sorted(surface.value for surface, ids in _SURFACES.items()
                                        if name in ids),
                     "backend": bind(name, next(surface for surface, ids in _SURFACES.items()
                                                if name in ids)).backend}
                    for name in sorted(actions)],
        "states": [state.value for state in State],
        "status_bindings": sorted(recipes.COMPONENT_STATUS_BINDINGS),
        "backend_state_is_external": True,
    }

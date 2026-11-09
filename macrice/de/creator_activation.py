"""Explicit Creator handoff to installed recipes and an opt-in Wayland session.

Draft editing and offline rendering stay side-effect-free. Callers must obtain
user confirmation before calling install(), apply_live() or restore_live().
All live mutations use the existing supervisor's CAS/rollback contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import creator_workspace as workspace, live, recipes, staging


class ActivationError(ValueError):
    """A guarded Creator activation cannot proceed without a new review."""


@dataclass(frozen=True)
class InstallPlan:
    draft: workspace.DraftInfo
    already_installed: bool


@dataclass(frozen=True)
class LivePlan:
    draft: workspace.DraftInfo
    expected_active: str
    next_login_persisted: bool


@dataclass(frozen=True)
class RestorePlan:
    expected_active: str
    previous: str
    next_login_persisted: bool


def _checked_draft(info: workspace.DraftInfo) -> workspace.DraftInfo:
    if info.path.parent != workspace._private_directory(create=False):
        raise ActivationError("Open a saved version from the private Creator workspace")
    try:
        current = workspace.open_draft(info.path)
    except (workspace.WorkspaceError, recipes.RecipeError, OSError) as exc:
        raise ActivationError("Saved version cannot be reviewed; reopen the draft") from exc
    if current.semantic_sha256 != info.semantic_sha256 or current.recipe_id != info.recipe_id:
        raise ActivationError("Saved version changed; reopen and review it again")
    return current


def _installed_digest(token: str) -> str | None:
    # A pre-existing but broken or symlinked destination is a collision, not
    # permission to overwrite it. Never silently replace an installed rice.
    try:
        destination = recipes._private_recipe_dir(create=False) / f"{token}.json"
    except recipes.RecipeError as exc:
        raise ActivationError("Installed recipe collection has unsafe permissions") from exc
    if not destination.exists() and not destination.is_symlink():
        return None
    try:
        return staging._hash(token)
    except (recipes.RecipeError, OSError) as exc:
        raise ActivationError("Installed recipe is invalid; resolve the ID conflict") from exc


def inspect_install(info: workspace.DraftInfo) -> InstallPlan:
    draft = _checked_draft(info)
    installed = _installed_digest(draft.recipe_id)
    if installed is not None and installed != draft.semantic_sha256:
        raise ActivationError(
            "That rice ID already contains a different version. "
            "Choose a new rice ID; installed recipes are never overwritten")
    return InstallPlan(draft, installed is not None)


def install(plan: InstallPlan) -> bool:
    """Install a reviewed immutable version once; return False if already installed."""
    checked = inspect_install(plan.draft)
    if checked.already_installed:
        return False
    try:
        recipes.import_recipe(checked.draft.path,
                              expected_semantic_sha256=checked.draft.semantic_sha256)
    except FileExistsError:
        # Two windows may try to install the same version. Accept only an
        # identical completed installation; a different one stays untouched.
        if inspect_install(plan.draft).already_installed:
            return False
        raise ActivationError("Installed rice ID changed; review again") from None
    except (recipes.RecipeError, OSError) as exc:
        raise ActivationError(f"Installation blocked: {exc}") from exc
    return True


def _live_status() -> dict:
    try:
        result = live.request("status")
    except live.LiveError as exc:
        raise ActivationError(str(exc)) from exc
    if not result.get("ok"):
        error = result.get("error", {})
        raise ActivationError(error.get("message", "Wayland supervisor is unavailable"))
    if (type(result.get("active")) is not str or
            type(result.get("next_login_persisted")) is not bool):
        raise ActivationError("Wayland supervisor returned incomplete status")
    return result


def inspect_live(info: workspace.DraftInfo) -> LivePlan:
    draft = _checked_draft(info)
    if _installed_digest(draft.recipe_id) != draft.semantic_sha256:
        raise ActivationError("Install this saved version first; live apply never imports a draft")
    status = _live_status()
    return LivePlan(draft, status["active"], status["next_login_persisted"])


def _request(action: str, *, recipe: str | None = None, digest: str | None = None,
             expected: str) -> dict:
    try:
        response = live.request(action, recipe=recipe, sha256=digest, expected=expected)
    except live.LiveError as exc:
        raise ActivationError(f"Live {action} uncertain: {exc}. Check live status before retrying") from exc
    if not response.get("ok"):
        error = response.get("error", {})
        raise ActivationError(error.get("message", "Live change was refused; review again"))
    return response


def apply_live(plan: LivePlan) -> dict:
    checked = _checked_draft(plan.draft)
    if _installed_digest(checked.recipe_id) != checked.semantic_sha256:
        raise ActivationError("Installed rice changed since review; application blocked")
    result = _request("apply", recipe=checked.recipe_id,
                      digest=checked.semantic_sha256, expected=plan.expected_active)
    if (result.get("active") != checked.recipe_id or
            result.get("semantic_sha256") != checked.semantic_sha256):
        raise ActivationError("Supervisor response is inconsistent; check live status now")
    return result


def inspect_restore() -> RestorePlan:
    status = _live_status()
    if (status.get("can_restore") is not True or
            type(status.get("previous")) is not str):
        raise ActivationError("There is no previous live rice to restore")
    return RestorePlan(status["active"], status["previous"],
                       status["next_login_persisted"])


def restore_live(plan: RestorePlan) -> dict:
    result = _request("restore", expected=plan.expected_active)
    if result.get("active") != plan.previous:
        raise ActivationError("Supervisor restored an unexpected rice; check live status")
    return result

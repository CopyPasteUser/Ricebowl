"""Opt-in labwc session runtime; never modifies the user's XFCE installation."""

from __future__ import annotations

import os
import json
import select
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import NoReturn

from . import riceprofile


REQUIRED_TOOLS = ("labwc", "waybar", "foot", "fuzzel", "swaylock")
DESKTOP_NAME = "RiceBowl:labwc:wlroots"
_CONFIG_PREFIX = "ricebowl-labwc-"


class SessionError(RuntimeError):
    """The preview session cannot start without a safe, usable baseline."""


def _waybar_recipe_config(recipe: object, env: Mapping[str, str],
                          which: Callable[[str], str | None]) -> tuple[str, str]:
    """Compile per-output compact rules when wlroots reports reliable geometry.

    Never let a missing/broken optional output utility prevent the rescue bar.
    No polling, background process, privileged operation or display mutation.
    """
    from . import recipes
    binary = which("wlr-randr")
    if binary:
        try:
            result = subprocess.run([binary, "--json"], env=dict(env),
                                    capture_output=True, text=True, timeout=2, check=True)
            if len(result.stdout) <= 65_536:
                raw = json.loads(result.stdout)
                if isinstance(raw, list):
                    outputs = {}
                    for item in raw:
                        if not isinstance(item, dict) or item.get("enabled") is not True:
                            continue
                        modes = item.get("modes", [])
                        current = next((mode for mode in modes if isinstance(mode, dict)
                                        and mode.get("current") is True), None)
                        scale = item.get("scale", 1)
                        if (current and type(current.get("width")) is int
                                and type(scale) in (float, int) and 0.5 <= scale <= 4):
                            width = current["width"]
                            if item.get("transform") in ("90", "270", "flipped-90", "flipped-270"):
                                width = current.get("height", width)
                            outputs[item["name"]] = round(width / scale)
                    if outputs:
                        return recipes.waybar_output_configs(recipe, outputs)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError,
                recipes.RecipeError):
            pass
    return recipes.waybar_config(recipe)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resources() -> Path:
    return Path(__file__).resolve().parent / "resources"


def _check_runtime_dir(environment: Mapping[str, str]) -> None:
    directory = environment.get("XDG_RUNTIME_DIR")
    if not directory or not os.path.isabs(directory):
        raise SessionError("XDG_RUNTIME_DIR is missing; log in through a proper user session.")
    try:
        mode = os.stat(directory)
    except OSError as exc:
        raise SessionError("XDG_RUNTIME_DIR is not accessible.") from exc
    if (not stat.S_ISDIR(mode.st_mode) or mode.st_uid != os.geteuid()
            or mode.st_mode & 0o077):
        raise SessionError("XDG_RUNTIME_DIR must be an owner-only directory.")


def _custom_labwc_config(recipe: object | None, runtime: str,
                         preferences: Mapping | None = None) -> Path:
    """Build private compositor settings without touching installed labwc config."""
    from .recipes import labwc_menu
    from . import preferences as spice_prefs
    directory = Path(tempfile.mkdtemp(prefix=_CONFIG_PREFIX, dir=runtime))
    try:
        source = resources() / "labwc"
        for name in ("rc.xml", "autostart", "shutdown", "menu.xml"):
            shutil.copyfile(source / name, directory / name)
        if recipe is not None:
            (directory / "menu.xml").write_text(labwc_menu(recipe), encoding="utf-8")
        if preferences is not None:
            spice_prefs.configure_labwc(directory / "rc.xml", preferences)
        (directory / ".ricebowl-managed").touch(mode=0o600)
        return directory
    except BaseException:
        shutil.rmtree(directory)
        raise


def _cleanup_labwc_config(env: Mapping[str, str]) -> None:
    """Remove only a marked private session directory under XDG_RUNTIME_DIR."""
    candidate = env.get("RICEBOWL_DE_SESSION_CONFIG")
    runtime = env.get("XDG_RUNTIME_DIR")
    if not candidate or not runtime:
        return
    directory = Path(candidate)
    if (directory.parent != Path(runtime) or not directory.name.startswith(_CONFIG_PREFIX)
            or directory.is_symlink()):
        return
    try:
        info = directory.stat()
        marker = directory / ".ricebowl-managed"
        if (info.st_uid != os.geteuid() or info.st_mode & 0o077
                or not marker.is_file() or marker.is_symlink()):
            return
    except OSError:
        return
    shutil.rmtree(directory)


def start(
    *,
    nested: bool = False,
    recipe: str | None = None,
    panel: str = "waybar",
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    execute: Callable[[str, list[str], dict[str, str]], NoReturn] = os.execvpe,
) -> NoReturn:
    """Replace the current session launcher with labwc; no files are changed."""
    if os.geteuid() == 0:
        raise SessionError("RiceBowl Wayland sessions must run as an unprivileged user.")
    if panel not in ("waybar", "native"):
        raise SessionError("Unsupported RiceBowl panel mode.")
    env = dict(os.environ if environment is None else environment)
    if not nested and not env.get("RICEBOWL_DM_SESSION") and (
        env.get("WAYLAND_DISPLAY") or env.get("DISPLAY")
    ):
        raise SessionError("A desktop is already active. Use --nested to test without replacing it.")
    _check_runtime_dir(env)
    if not nested:
        # A display manager may inherit its greeter's display variables.
        # Do not accidentally make the primary login session a nested client.
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)

    binaries = {name: which(name) for name in REQUIRED_TOOLS}
    missing = [name for name, path in binaries.items() if not path]
    # A full login must never become suspend-capable without its idle /
    # before-sleep lock listener. Nested previews do not own system sleep.
    if not nested and not which("swayidle"):
        missing.append("swayidle")
    if missing:
        raise SessionError("Missing Wayland preview dependencies: " + ", ".join(missing))
    if panel == "native" and not which("riceplate-native"):
        raise SessionError("Native RicePlate is not installed in PATH; Waybar remains available.")

    source = project_root()
    launcher = source / "launcher.py"
    config = resources() / "labwc"
    if not launcher.is_file() or not (config / "rc.xml").is_file():
        raise SessionError("Incomplete RiceBowl installation; reinstall the current checkout.")
    from .recipes import RecipeError, load, native_token, selected_recipe
    explicit_recipe = recipe is not None
    loaded_recipe = None
    if recipe is None:
        try:
            recipe = selected_recipe()
        except RecipeError as error:
            print(f"RiceBowl: ignoring invalid saved recipe selection: {error}", file=sys.stderr)
    if recipe is not None:
        try:
            loaded_recipe = load(recipe)  # Fail closed for explicitly chosen recipes.
        except RecipeError as error:
            if explicit_recipe:
                raise
            print(f"RiceBowl: saved recipe unavailable, using classic: {error}", file=sys.stderr)
            recipe = None
        else:
            recipe = native_token(recipe)  # Rust consumes the same validated private file.

    env.update({
        "XDG_CURRENT_DESKTOP": DESKTOP_NAME,
        "XDG_SESSION_DESKTOP": "ricebowl",
        "XDG_SESSION_TYPE": "wayland",
        "RICEBOWL_DE_SHELL_CHILD": "1",
        "RICEBOWL_DE_NESTED": "1" if nested else "0",
        "RICEBOWL_DE_PANEL": panel,
    })
    if recipe is not None:
        env["RICEBOWL_DE_RECIPE"] = recipe
    else:
        env.pop("RICEBOWL_DE_RECIPE", None)
    if nested:
        # A nested compositor must never replace the active session's D-Bus/
        # systemd Wayland activation environment.
        env["LABWC_UPDATE_ACTIVATION_ENV"] = "0"
    else:
        env.pop("LABWC_UPDATE_ACTIVATION_ENV", None)

    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        bus = which("dbus-run-session")
        if not bus:
            raise SessionError("No D-Bus user session and dbus-run-session is unavailable.")
        if env.get("RICEBOWL_DE_BUS_REEXEC") == "1":
            raise SessionError("D-Bus session setup failed; refusing an unbounded restart.")
        env["RICEBOWL_DE_BUS_REEXEC"] = "1"
        args = [bus, "--", sys.executable, str(launcher), "de", "start"]
        if nested:
            args.append("--nested")
        if recipe is not None:
            args.extend(("--recipe", recipe))
        if panel == "native":
            args.extend(("--panel", "native"))
        execute(bus, args, env)
        raise AssertionError("execvpe unexpectedly returned")

    labwc = binaries["labwc"]
    assert labwc is not None
    shell_command = shlex.join([sys.executable, str(launcher), "de", "shell"])
    # Mint 22's labwc 0.7.1 only supports --startup, not --session. Keep a
    # tiny POSIX shell as the parent of our panel supervisor: it requests a
    # compositor exit even if Python crashes or is killed, not only on an
    # ordinary return from the supervisor.
    session_command = shlex.join([
        "sh", "-c", f'{shell_command}; status=$?; {shlex.quote(labwc)} --exit '
                    '>/dev/null 2>&1; exit "$status"',
    ])
    from . import preferences as spice_prefs
    spice_values = None
    try:
        spice_values = spice_prefs.load_optional()
    except spice_prefs.PreferenceError as error:
        print(f"RiceBowl: ignoring unsafe RiceSpice preferences: {error}", file=sys.stderr)
    if spice_values is not None:
        spice_prefs.apply_session_environment(env, spice_values)
    if (spice_values is not None and spice_values["accessibility_enabled"]
            and spice_values["screen_reader_enabled"] and not nested):
        env["RICEBOWL_DE_SCREEN_READER"] = "1"
    else:
        env.pop("RICEBOWL_DE_SCREEN_READER", None)
    # Always use the marked, disposable config in this opt-in session. Live
    # profile switches must never edit the system or the user's labwc files.
    config = _custom_labwc_config(
        loaded_recipe if loaded_recipe is not None and loaded_recipe.menu is not None else None,
        env["XDG_RUNTIME_DIR"], spice_values)
    env["RICEBOWL_DE_SESSION_CONFIG"] = str(config)
    env["RICEBOWL_DE_LIVE"] = "1"
    try:
        riceprofile.ProfileSession.prepare(config, env, loaded_recipe or load("classic"), which=which)
    except (OSError, riceprofile.ProfileError, ValueError):
        _cleanup_labwc_config(env)
        raise
    try:
        execute(labwc, [labwc, "--config-dir", str(config), "--startup", session_command], env)
    except OSError:
        _cleanup_labwc_config(env)
        raise
    raise AssertionError("execvpe unexpectedly returned")


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
    except ProcessLookupError:
        pass


def _atomic_menu(path: Path, content: str) -> None:
    """Replace only the supervisor's private labwc menu, never edit in place."""
    descriptor, temporary = tempfile.mkstemp(prefix=".ricebowl-menu-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class _OutputEvents:
    """Debounce a Wayland event pipe; never sample displays on a timer.

    Only a change notification schedules a one-shot inventory comparison.
    External/unavailable watchers leave explicit display-refresh operational.
    """

    def __init__(self, stream: object):
        self.stream = stream
        os.set_blocking(stream.fileno(), False)
        self.deadline: float | None = None
        self.partial = b""

    def ready(self, now: float) -> bool:
        if self.stream is not None:
            try:
                if select.select([self.stream], [], [], 0)[0]:
                    data = os.read(self.stream.fileno(), 4096)
                    if data:
                        buffered = (self.partial + data)[-8192:]
                        *messages, self.partial = buffered.split(b"\n")
                        if b"changed" in messages:
                            self.deadline = now + 0.65
                    else:
                        self.stream.close()
                        self.stream = None
            except (OSError, ValueError):
                self.stream = None
        if self.deadline is not None and now >= self.deadline:
            self.deadline = None
            return True
        return False


class _ResumeGap:
    """Detect suspend without trusting wall-clock jumps or a new daemon.

    CLOCK_BOOTTIME advances during Linux suspend; CLOCK_MONOTONIC does not.
    A changed difference reports a wake once. If the kernel lacks BOOTTIME,
    resume detection is unavailable; existing wl_output events still work.
    """

    def __init__(self, reader: Callable[[], tuple[float, float]] | None = None):
        if reader is None and hasattr(time, "CLOCK_BOOTTIME"):
            reader = lambda: (time.monotonic(), time.clock_gettime(time.CLOCK_BOOTTIME))
        self._read = reader
        self._previous: float | None = None

    def resumed(self) -> bool:
        if self._read is None:
            return False
        try:
            monotonic, boottime = self._read()
        except (OSError, ValueError):
            return False
        offset = boottime - monotonic
        prior, self._previous = self._previous, offset
        return prior is not None and offset - prior >= 1.5


def _wait_with_idle_guard(panel: subprocess.Popen[bytes],
                          idle: subprocess.Popen[bytes] | None) -> tuple[int, bool]:
    """Supervise even when live RPC is unavailable or deliberately disabled.

    Return (panel exit status, idle watcher failed). A missing security guard
    is fatal in full sessions; never mistake its death for a panel crash that
    should trigger a Waybar rescue.
    """
    if idle is None:
        return panel.wait(), False
    while True:
        if idle.poll() is not None:
            print("RiceBowl: idle/lock watcher exited; stopping unprotected "
                  "Wayland session", file=sys.stderr)
            _stop_process(panel)
            return 1, True
        try:
            return panel.wait(timeout=0.2), False
        except subprocess.TimeoutExpired:
            continue


class _LiveSwitch:
    """One transaction owner for panel, wallpaper, compositor menu and login state."""

    def __init__(self, *, env: dict[str, str], mode: str,
                 which: Callable[[str], str | None],
                 spawn: Callable[..., subprocess.Popen[bytes]],
                 cleanup: ExitStack, initial_panel: subprocess.Popen[bytes],
                 initial_wallpaper: subprocess.Popen[bytes] | None,
                 background: list[subprocess.Popen[bytes]],
                 stopping: Callable[[], bool] | None = None):
        from . import recipes, staging
        self.env, self.mode, self.which, self.spawn = env, mode, which, spawn
        self.cleanup, self.panel, self.wallpaper = cleanup, initial_panel, initial_wallpaper
        self.background = background
        self.stopping = stopping or (lambda: False)
        self.nested = env.get("RICEBOWL_DE_NESTED") == "1"
        self.active = recipes.load(env.get("RICEBOWL_DE_RECIPE", "classic")).recipe_id
        self.active_digest = staging._hash(self.active)
        self.previous: tuple[str, str] | None = None
        self.expected_selection, previous = recipes.current_selection()
        if self.expected_selection == self.active and previous:
            try:
                # On a fresh login, accept only a previously pinned private
                # recipe or an immutable built-in as a live rollback target.
                state = recipes._read_selection(recipes._private_recipe_dir(create=False))
                pinned = state.get("previous_sha256") if state and state["schema_version"] == 2 else None
                actual = staging._hash(previous)
                if pinned == actual or (pinned is None and previous in recipes.BUILTINS):
                    self.previous = (previous, actual)
            except recipes.RecipeError:
                pass
        self.menu = Path(env["RICEBOWL_DE_SESSION_CONFIG"]) / "menu.xml"
        self.profile = (riceprofile.ProfileSession.from_environment(env)
                        if any(key.env_key in env for key in riceprofile.CLIENTS) else None)
        self.fallback = False

    def status(self) -> dict:
        return {"version": 1, "ok": True, "active": self.active,
                "semantic_sha256": self.active_digest,
                "previous": self.previous[0] if self.previous else None,
                "can_restore": self.previous is not None,
                "next_login_persisted": not self.nested,
                "panel": "waybar-fallback" if self.fallback else self.mode,
                "applied": True,
                "applications": self.profile.status() if self.profile else {
                    "taskotto": "not_managed", "ricefield": "not_managed"}}

    def _reconfigure(self) -> None:
        binary = self.which("labwc")
        if not binary:
            from .live import LiveError
            raise LiveError("labwc reconfiguration is unavailable", code="component_unavailable")
        subprocess.run([binary, "--reconfigure"], env=self.env, check=True,
                       timeout=4, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _start_panel(self, token: str, recipe: object) -> subprocess.Popen[bytes]:
        from . import recipes
        if self.mode == "native" and not self.fallback:
            binary = self.which("riceplate-native")
            if not binary:
                from .live import LiveError
                raise LiveError("Native RicePlate is unavailable", code="component_unavailable")
            command = [binary, "--recipe", recipes.native_token(token)]
        else:
            binary = self.which("waybar")
            if not binary:
                from .live import LiveError
                raise LiveError("Waybar fallback is unavailable", code="component_unavailable")
            directory = Path(self.cleanup.enter_context(tempfile.TemporaryDirectory(
                prefix="ricebowl-live-plate-", dir=self.env["XDG_RUNTIME_DIR"])))
            config, style = _waybar_recipe_config(recipe, self.env, self.which)
            for name, content in (("config.jsonc", config), ("style.css", style)):
                (directory / name).write_text(content, encoding="utf-8")
            command = [binary, "--config", str(directory / "config.jsonc"),
                       "--style", str(directory / "style.css")]
        return self.spawn(command, env={**self.env, "RICEBOWL_DE_RECIPE": recipes.native_token(token)},
                          stdin=subprocess.DEVNULL)

    def rescue_panel(self) -> None:
        """Try one bounded Waybar rescue without changing saved user state.

        Reuse only the reviewed active recipe, never a changed imported file.
        A failed rescue is surfaced to the supervisor rather than looped.
        """
        from . import recipes, staging
        from .live import LiveError
        if self.stopping():
            raise LiveError("Session is shutting down", code="session_stopping")
        recipe = recipes.load(self.active)
        if staging._hash(self.active) != self.active_digest:
            raise LiveError("Active recipe changed; rescue refused", code="recipe_changed")
        self.fallback = True
        candidate = self._start_panel(self.active, recipe)
        time.sleep(0.5)
        if self.stopping():
            _stop_process(candidate)
            raise LiveError("Session is shutting down", code="session_stopping")
        if candidate.poll() is not None:
            _stop_process(candidate)
            raise LiveError("Waybar rescue exited during activation", code="component_failed")
        self.panel = candidate

    def handle(self, request: dict) -> dict:
        from . import recipes, staging
        from .live import LiveError
        import re

        action, token, digest, expected = (request[key] for key in
                                           ("action", "recipe", "sha256", "expected"))
        if action == "status":
            if any(value is not None for value in (token, digest, expected)):
                raise LiveError("Status takes no change options", code="invalid_live_request")
            return self.status()
        if self.stopping():
            raise LiveError("Session is shutting down", code="session_stopping")
        if action == "refresh-outputs":
            if any(value is not None for value in (token, digest, expected)):
                raise LiveError("Output refresh takes no change options", code="invalid_live_request")
            # Native RicePlate follows wl_output changes directly. Only its
            # Waybar rescue/fallback needs an output-specific config refresh.
            if self.mode == "native" and not self.fallback:
                return {**self.status(), "changed": False}
            try:
                recipe = recipes.load(self.active)
                new_panel = self._start_panel(self.active, recipe)
            except (recipes.RecipeError, OSError, LiveError) as exc:
                raise LiveError("Waybar output refresh could not start",
                                code="component_failed") from exc
            time.sleep(0.5)
            if new_panel.poll() is not None:
                _stop_process(new_panel)
                raise LiveError("Waybar output refresh failed; previous bar retained",
                                code="component_failed")
            old_panel, self.panel = self.panel, new_panel
            _stop_process(old_panel)
            return {**self.status(), "changed": True}
        if expected is not None and expected != self.active:
            raise LiveError("Active rice changed; review again", code="selection_conflict")
        if action == "restore":
            if token is not None or digest is not None or self.previous is None:
                raise LiveError("There is no previous live rice", code="rollback_unavailable")
            token, digest = self.previous
        elif (action != "apply" or not isinstance(token, str) or
              not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", token) or
              not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise LiveError("Apply requires a reviewed ID and SHA-256", code="invalid_live_request")
        assert token is not None and digest is not None
        try:
            recipe = recipes.load(token)
            if staging._hash(token) != digest:
                raise LiveError("Recipe changed since review", code="recipe_changed")
            if token == self.active:
                return {**self.status(), "changed": False}
            # Preflight *every* component before mutating the active compositor.
            wallpaper_path = recipes.wallpaper_path(recipe)
            wallpaper_binary = self.which("swaybg")
            if not wallpaper_binary or not wallpaper_path.is_file():
                raise LiveError("Wallpaper component is unavailable", code="component_unavailable")
            new_menu = (recipes.labwc_menu(recipe) if recipe.menu is not None else
                        (resources() / "labwc/menu.xml").read_text(encoding="utf-8"))
            old_menu = self.menu.read_text(encoding="utf-8")
            old_digest = self.active_digest
            prepared_profiles = self.profile.preflight(recipe) if self.profile else {}
            selection_before = recipes._selection_snapshot() if not self.nested else None
            if not self.nested and recipes.current_selection()[0] != self.expected_selection:
                raise LiveError("Next-login selection changed", code="selection_conflict")
        except riceprofile.ProfileError as exc:
            raise LiveError(str(exc), code="profile_unavailable") from exc
        except (recipes.RecipeError, OSError) as exc:
            raise LiveError("Recipe is invalid or an asset is unavailable",
                            code="invalid_recipe") from exc

        new_panel = None
        new_wallpaper = None
        menu_attempted = False
        profile_original = None
        selection_attempted = False
        try:
            new_wallpaper = self.spawn([wallpaper_binary, "--image", str(wallpaper_path),
                                        "--mode", "fill"], env=self.env, stdin=subprocess.DEVNULL)
            new_panel = self._start_panel(token, recipe)
            time.sleep(0.5)
            if new_panel.poll() is not None or new_wallpaper.poll() is not None:
                raise LiveError("New shell component exited during activation", code="component_failed")
            if self.stopping():
                raise LiveError("Session is shutting down", code="session_stopping")
            menu_attempted = True
            _atomic_menu(self.menu, new_menu)
            self._reconfigure()
            if self.profile:
                profile_original = self.profile.commit(prepared_profiles)
            if not self.nested:
                selection_attempted = True
                recipes.change_selection(token, expected_active=self.expected_selection,
                                         expected_semantic_sha256=digest)
            if self.stopping():
                raise LiveError("Session is shutting down", code="session_stopping")
        except (LiveError, OSError, ValueError, subprocess.SubprocessError,
                riceprofile.ProfileError) as exc:
            if new_panel is not None:
                _stop_process(new_panel)
            if new_wallpaper is not None:
                _stop_process(new_wallpaper)
            recovery_errors = []
            if profile_original is not None and self.profile:
                try:
                    self.profile.restore(profile_original)
                except riceprofile.ProfileError as restore_error:
                    recovery_errors.append(f"profile: {restore_error}")
            if menu_attempted:
                try:
                    _atomic_menu(self.menu, old_menu)
                    self._reconfigure()
                except (OSError, subprocess.SubprocessError) as restore_error:
                    recovery_errors.append(f"menu: {restore_error}")
            if selection_attempted:
                try:
                    recipes._restore_failed_live_selection(token, digest, selection_before)
                except (recipes.RecipeError, OSError) as restore_error:
                    recovery_errors.append(f"selection: {restore_error}")
            if recovery_errors:
                print("RiceBowl: incomplete live recovery: " + "; ".join(recovery_errors),
                      file=sys.stderr)
                raise LiveError("Live recovery incomplete; restart the opt-in session",
                                code="rollback_failed") from exc
            if isinstance(exc, LiveError):
                raise
            if isinstance(exc, riceprofile.ProfileError):
                raise LiveError(str(exc), code="profile_unavailable") from exc
            if isinstance(exc, recipes.SelectionConflict):
                raise LiveError("Next-login selection changed during activation",
                                code="selection_conflict") from exc
            if isinstance(exc, recipes.RecipeFingerprintMismatch):
                raise LiveError("Recipe changed during activation",
                                code="recipe_changed") from exc
            raise LiveError("Live activation failed; previous rice retained",
                            code="component_failed") from exc

        old_panel, old_wallpaper, old_active = self.panel, self.wallpaper, self.active
        self.panel, self.wallpaper, self.active = new_panel, new_wallpaper, token
        self.active_digest = digest
        self.expected_selection = token
        self.previous = (old_active, old_digest)
        self.env["RICEBOWL_DE_RECIPE"] = recipes.native_token(token)
        _stop_process(old_panel)
        if old_wallpaper is not None:
            _stop_process(old_wallpaper)
            self.background.remove(old_wallpaper)
        self.background.append(new_wallpaper)
        return {**self.status(), "changed": True}


def _refresh_changed_outputs(controller: _LiveSwitch, previous: tuple[str, str] | None,
                             env: Mapping[str, str], which: Callable[[str], str | None]
                             ) -> tuple[str, str]:
    """Only replace the owned Waybar when a wl_output event changed its layout."""
    from . import recipes

    current = controller.active
    config = _waybar_recipe_config(recipes.load(current), env, which)[0]
    signature = (current, config)
    if signature != previous:
        controller.handle({"action": "refresh-outputs", "recipe": None,
                           "sha256": None, "expected": None})
    return signature


def shell(
    *,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    spawn: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> int:
    """Supervise the temporary native Wayland shell until its panel exits."""
    env = dict(os.environ if environment is None else environment)
    if env.get("RICEBOWL_DE_SHELL_CHILD") != "1" or not env.get("WAYLAND_DISPLAY"):
        raise SessionError("RiceBowl's Wayland shell may only run inside its labwc session.")
    waybar = which("waybar")
    if not waybar:
        raise SessionError("Waybar is required until RicePlate's native panel is ready.")
    panel_mode = env.get("RICEBOWL_DE_PANEL", "waybar")
    if panel_mode not in ("waybar", "native"):
        raise SessionError("Unsupported RiceBowl panel mode.")

    base = resources()
    background: list[subprocess.Popen[bytes]] = []
    panel: subprocess.Popen[bytes] | None = None
    live_controller: _LiveSwitch | None = None
    with ExitStack() as cleanup:
        cleanup.callback(_cleanup_labwc_config, env)
        config = base / "waybar/config.jsonc"
        style = base / "waybar/style.css"
        selected = env.get("RICEBOWL_DE_RECIPE")
        if selected:
            from .recipes import load, waybar_config
            _check_runtime_dir(env)
            recipe = load(selected)
            directory = Path(cleanup.enter_context(tempfile.TemporaryDirectory(
                prefix="ricebowl-plate-", dir=env["XDG_RUNTIME_DIR"])))
            config = directory / "config.jsonc"
            style = directory / "style.css"
            generated_config, generated_style = _waybar_recipe_config(recipe, env, which)
            for path, content in ((config, generated_config), (style, generated_style)):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(content)
        wallpaper_process: subprocess.Popen[bytes] | None = None
        try:
            swaybg = which("swaybg")
            from .recipes import load, wallpaper_path
            wallpaper = wallpaper_path(load(selected or "classic"))
            if swaybg and wallpaper.is_file():
                wallpaper_process = spawn(
                    [swaybg, "--image", str(wallpaper), "--mode", "fill"],
                    env=env, stdin=subprocess.DEVNULL,
                )
                background.append(wallpaper_process)

            # Temporary notification host, not a replacement for RicePop.
            mako = which("mako")
            if mako:
                background.append(spawn([mako], env=env, stdin=subprocess.DEVNULL))

            # Orca is optional, opt-in and only supervised inside a full RiceBowl
            # session. Do not start another reader in a nested XFCE preview.
            if env.get("RICEBOWL_DE_SCREEN_READER") == "1" and env.get("RICEBOWL_DE_NESTED") != "1":
                orca = which("orca")
                if orca:
                    try:
                        background.append(spawn([orca], env=env, stdin=subprocess.DEVNULL))
                    except OSError as error:
                        print(f"RiceBowl: Orca could not start: {error}", file=sys.stderr)
                else:
                    print("RiceBowl: Orca screen reader requested but not installed",
                          file=sys.stderr)

            # Authorization goes to a user polkit agent, never a root shell.
            for name in ("lxpolkit", "mate-polkit", "polkit-gnome-authentication-agent-1"):
                agent = which(name)
                if agent:
                    background.append(spawn([agent], env=env, stdin=subprocess.DEVNULL))
                    break

            idle_process: subprocess.Popen[bytes] | None = None
            if env.get("RICEBOWL_DE_NESTED") != "1":
                idle = which("swayidle")
                locker = which("swaylock")
                if not idle or not locker:
                    raise SessionError(
                        "Full Wayland session requires swayidle and swaylock "
                        "for automatic and pre-suspend screen locking.")
                lock_command = shlex.join([locker, "-f"])
                idle_process = spawn(
                    [idle, "-w", "timeout", "600", lock_command,
                     "before-sleep", lock_command],
                    env=env, stdin=subprocess.DEVNULL,
                )
                background.append(idle_process)

            shutting_down = False
            shutdown_signal = signal.SIGTERM

            def terminate(_signal: int, _frame: object) -> None:
                nonlocal shutting_down, shutdown_signal
                shutting_down = True
                shutdown_signal = _signal
                current = live_controller.panel if live_controller is not None else panel
                if current is not None:
                    _stop_process(current)

            native_live_rescue_attempted = False
            idle_guard_failed = False

            def supervised_wait(process: subprocess.Popen[bytes], mode: str) -> int:
                nonlocal live_controller, native_live_rescue_attempted, idle_guard_failed
                if env.get("RICEBOWL_DE_LIVE") != "1":
                    result, idle_guard_failed = _wait_with_idle_guard(process, idle_process)
                    return result
                from .live import LiveError, listen, serve_once
                from .recipes import RecipeError
                try:
                    live_controller = _LiveSwitch(
                        env=env, mode=mode, which=which, spawn=spawn,
                        cleanup=cleanup, initial_panel=process,
                        initial_wallpaper=wallpaper_process, background=background,
                        stopping=lambda: shutting_down)
                    # The Rust helper observes wl_output events, unlike a
                    # wlr-randr timer. It is optional and only needed for
                    # Waybar, because native RicePlate already reflows itself.
                    output_events = None
                    last_output_config = None
                    resume_gap = (_ResumeGap() if env.get("RICEBOWL_DE_NESTED") != "1"
                                  else None)
                    resume_refresh_at: float | None = None
                    watcher_bin = (which("riceplate-native") if mode == "waybar"
                                   and which("wlr-randr") else None)
                    if watcher_bin:
                        watcher = None
                        try:
                            from . import recipes
                            watcher = spawn([watcher_bin, "--watch-outputs"],
                                            env=env, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                            output_events = _OutputEvents(watcher.stdout)
                            background.append(watcher)
                            active = live_controller.active
                            last_output_config = (active, _waybar_recipe_config(
                                recipes.load(active), env, which)[0])
                        except (OSError, AttributeError, TypeError, RecipeError) as error:
                            if watcher is not None:
                                _stop_process(watcher)
                            output_events = None
                            print(f"RiceBowl: automatic output watch unavailable: {error}",
                                  file=sys.stderr)
                    # The optional Rust output watcher may be absent in a
                    # Waybar-only installation. Still record the initial
                    # output-layout signature, otherwise the first resume
                    # would restart an unchanged bar unnecessarily.
                    if mode == "waybar" and last_output_config is None:
                        try:
                            from . import recipes
                            active = live_controller.active
                            last_output_config = (active, _waybar_recipe_config(
                                recipes.load(active), env, which)[0])
                        except (RecipeError, OSError, ValueError) as error:
                            print(f"RiceBowl: initial output layout unavailable: {error}",
                                  file=sys.stderr)
                    with listen(env) as listener:
                        auto_restore_attempted = False
                        rescue_attempted = False
                        while not shutting_down:
                            # If swayidle dies, the next suspend could resume
                            # onto an unlocked screen. End this opt-in session
                            # rather than silently running without protection.
                            if idle_process is not None and idle_process.poll() is not None:
                                idle_guard_failed = True
                                print("RiceBowl: idle/lock watcher exited; stopping "
                                      "unprotected Wayland session", file=sys.stderr)
                                _stop_process(live_controller.panel)
                                return 1
                            # On wake, allow DRM/output discovery to settle before
                            # one bounded Waybar layout recheck. Native RicePlate
                            # handles wl_output itself. No timer or daemon is
                            # started, and normal CPU wakeups do not trigger it.
                            now = time.monotonic()
                            if resume_gap is not None and resume_gap.resumed():
                                resume_refresh_at = now + 1.5
                            if resume_refresh_at is not None and now >= resume_refresh_at:
                                resume_refresh_at = None
                                if mode == "waybar" or live_controller.fallback:
                                    try:
                                        last_output_config = _refresh_changed_outputs(
                                            live_controller, last_output_config, env, which)
                                    except (LiveError, RecipeError, OSError) as error:
                                        print("RiceBowl: resume output refresh retained "
                                              f"previous panel: {error}", file=sys.stderr)
                            exit_code = live_controller.panel.poll()
                            if exit_code is not None:
                                if exit_code == 0:
                                    break  # Explicit clean panel exit remains a session exit.
                                if not auto_restore_attempted and live_controller.previous is not None:
                                    auto_restore_attempted = True
                                    try:
                                        live_controller.handle({
                                            "action": "restore", "recipe": None, "sha256": None,
                                            "expected": live_controller.active,
                                        })
                                        print("RiceBowl: failed live panel automatically restored",
                                              file=sys.stderr)
                                        continue
                                    except LiveError as error:
                                        print(f"RiceBowl: live auto-restore failed: {error}",
                                              file=sys.stderr)
                                if not rescue_attempted:
                                    rescue_attempted = True
                                    if mode == "native":
                                        native_live_rescue_attempted = True
                                    try:
                                        live_controller.rescue_panel()
                                        print("RiceBowl: failed live panel recovered with Waybar",
                                              file=sys.stderr)
                                        continue
                                    except (LiveError, RecipeError, OSError) as error:
                                        print(f"RiceBowl: Waybar live rescue failed: {error}",
                                              file=sys.stderr)
                                break
                            if output_events is not None and output_events.ready(time.monotonic()):
                                try:
                                    last_output_config = _refresh_changed_outputs(
                                        live_controller, last_output_config, env, which)
                                except (LiveError, RecipeError, OSError) as error:
                                    print(f"RiceBowl: automatic output refresh retained old bar: {error}",
                                          file=sys.stderr)
                            serve_once(listener, live_controller.handle)
                        return live_controller.panel.wait()
                except (LiveError, RecipeError, OSError) as error:
                    print(f"RiceBowl live switching unavailable: {error}", file=sys.stderr)
                    result, guard_failed = _wait_with_idle_guard(process, idle_process)
                    idle_guard_failed = idle_guard_failed or guard_failed
                    return result
                finally:
                    if live_controller is not None:
                        _stop_process(live_controller.panel)
                    live_controller = None

            signal.signal(signal.SIGTERM, terminate)
            signal.signal(signal.SIGINT, terminate)
            if shutting_down:
                return 128 + shutdown_signal
            if panel_mode == "native":
                native = which("riceplate-native")
                if native:
                    try:
                        panel = spawn(
                            [native, "--recipe", selected or "classic"],
                            env=env, stdin=subprocess.DEVNULL,
                        )
                        if shutting_down:
                            _stop_process(panel)
                            return 128 + shutdown_signal
                        status = supervised_wait(panel, "native")
                        if (status == 0 or shutting_down or native_live_rescue_attempted
                                or idle_guard_failed):
                            return status
                        print(f"RicePlate native exited with status {status}; restoring Waybar.",
                              file=sys.stderr)
                    except OSError as exc:
                        if shutting_down:
                            return 1
                        print(f"RicePlate native could not start ({exc}); restoring Waybar.",
                              file=sys.stderr)
                else:
                    print("RicePlate native disappeared from PATH; restoring Waybar.",
                          file=sys.stderr)

            if shutting_down:
                return 128 + shutdown_signal
            # A native panel can fail after a successful live switch. Keep the
            # Waybar rescue on the *current* recipe, not the login-time one.
            current_selected = env.get("RICEBOWL_DE_RECIPE")
            if current_selected != selected:
                from .recipes import load, waybar_config
                current_recipe = load(current_selected or "classic")
                directory = Path(cleanup.enter_context(tempfile.TemporaryDirectory(
                    prefix="ricebowl-plate-rescue-", dir=env["XDG_RUNTIME_DIR"])))
                config, style = directory / "config.jsonc", directory / "style.css"
                generated_config, generated_style = _waybar_recipe_config(current_recipe, env, which)
                config.write_text(generated_config, encoding="utf-8")
                style.write_text(generated_style, encoding="utf-8")
            panel = spawn(
                [waybar, "--config", str(config), "--style", str(style)],
                env=env, stdin=subprocess.DEVNULL,
            )
            if shutting_down:
                _stop_process(panel)
                return 128 + shutdown_signal
            return supervised_wait(panel, "waybar")
        finally:
            if panel is not None:
                _stop_process(panel)
            for process in reversed(background):
                _stop_process(process)

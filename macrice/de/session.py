"""Opt-in labwc session runtime; never modifies the user's XFCE installation."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import NoReturn


REQUIRED_TOOLS = ("labwc", "waybar", "foot", "fuzzel", "swaylock")
DESKTOP_NAME = "RiceBowl:labwc:wlroots"
_CONFIG_PREFIX = "ricebowl-labwc-"


class SessionError(RuntimeError):
    """The preview session cannot start without a safe, usable baseline."""


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
    if ((loaded_recipe is not None and loaded_recipe.menu is not None)
            or (spice_values is not None and spice_values["input_enabled"])):
        config = _custom_labwc_config(
            loaded_recipe if loaded_recipe is not None and loaded_recipe.menu is not None else None,
            env["XDG_RUNTIME_DIR"], spice_values)
        env["RICEBOWL_DE_SESSION_CONFIG"] = str(config)
    else:
        env.pop("RICEBOWL_DE_SESSION_CONFIG", None)
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
            generated_config, generated_style = waybar_config(recipe)
            for path, content in ((config, generated_config), (style, generated_style)):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(content)
        try:
            swaybg = which("swaybg")
            from .recipes import load, wallpaper_path
            wallpaper = wallpaper_path(load(selected or "classic"))
            if swaybg and wallpaper.is_file():
                background.append(spawn(
                    [swaybg, "--image", str(wallpaper), "--mode", "fill"],
                    env=env, stdin=subprocess.DEVNULL,
                ))

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

            idle = which("swayidle")
            locker = which("swaylock")
            if idle and locker and env.get("RICEBOWL_DE_NESTED") != "1":
                lock_command = shlex.join([locker, "-f"])
                background.append(spawn(
                    [idle, "-w", "timeout", "600", lock_command,
                     "before-sleep", lock_command],
                    env=env, stdin=subprocess.DEVNULL,
                ))

            shutting_down = False
            shutdown_signal = signal.SIGTERM

            def terminate(_signal: int, _frame: object) -> None:
                nonlocal shutting_down, shutdown_signal
                shutting_down = True
                shutdown_signal = _signal
                if panel is not None:
                    _stop_process(panel)

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
                        status = panel.wait()
                        if status == 0 or shutting_down:
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
            panel = spawn(
                [waybar, "--config", str(config), "--style", str(style)],
                env=env, stdin=subprocess.DEVNULL,
            )
            if shutting_down:
                _stop_process(panel)
                return 128 + shutdown_signal
            return panel.wait()
        finally:
            if panel is not None:
                _stop_process(panel)
            for process in reversed(background):
                _stop_process(process)

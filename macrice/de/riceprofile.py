"""RiceProfile v1: optional, validated cross-app session appearance handoff.

No desktop defaults, persistent app preferences, or executables are changed.
The supervisor writes only its own disposable, owner-private session files.
The clients remain completely independent outside a RiceBowl session.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from . import taskotto
from .recipes import PanelRecipe


FORMAT_VERSION = 1


class ProfileError(RuntimeError):
    """The optional profile transaction could not be validated or recovered."""


@dataclass(frozen=True)
class _Client:
    binary: str
    env_key: str
    filename: str
    check_flag: str


CLIENTS = (
    _Client("taskotto", "RICEBOWL_TASKOTTO_RICEPACK", "taskotto.ricepack.toml", "--check-ricepack"),
    _Client("ricefield", "RICEBOWL_RICEFIELD_THEME_FILE", "ricefield.riceprofile.toml", "--check-theme-file"),
)


FIELD_THEMES = {
    "windows98": "win98",
    "xp-luna": "xp-luna",
    "windows7": "win7",
    "windows10": "win10",
    "chromeos": "chromeos",
    "frutiger-aero": "frutiger-aero",
    "macos": "macos",
}


def render_ricefield(recipe: PanelRecipe) -> bytes:
    """Strict RiceField RiceProfile v1 TOML, matched to Taskotto's mapping."""
    base = taskotto.WALLPAPER_THEME.get(recipe.wallpaper)
    if base is None and recipe.recipe_id == "chrome":
        base = "chromeos"
    base = FIELD_THEMES.get(base, "win7")
    name = f"RiceBowl: {recipe.name}"
    if len(name) > 64 or any(ord(char) < 32 for char in name):
        raise ProfileError("RicePlate name does not fit the RiceProfile v1 contract")
    surface, text, accent = recipe.colors
    return ("\n".join((
        f"format_version = {FORMAT_VERSION}",
        f"name = {json.dumps(name, ensure_ascii=True)}",
        f"base_theme = {json.dumps(base)}",
        "",
        "[appearance]",
        f"accent = {json.dumps(accent)}",
        f"surface = {json.dumps(surface)}",
        f"text = {json.dumps(text)}",
        "",
    ))).encode("utf-8")


def _render(client: _Client, recipe: PanelRecipe) -> bytes:
    return taskotto.render(recipe) if client.binary == "taskotto" else render_ricefield(recipe)


def _private_file(path: Path) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ProfileError("RiceProfile file is no longer a private regular file")
    if info.st_size > 256 * 1024:
        raise ProfileError("RiceProfile file exceeds its size limit")
    return path.read_bytes()


def _write_new(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _atomic_replace(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".riceprofile-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def _check(binary: str, flag: str, path: Path,
           run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool:
    try:
        result = run([binary, flag, str(path)], timeout=4, check=False,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class ProfileSession:
    """A guarded, reversible set of client-owned hot-reload files."""

    def __init__(self, root: Path, clients: Mapping[_Client, tuple[str, bytes]],
                 *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self.root = root
        self.clients = dict(clients)
        self.run = run

    @classmethod
    def prepare(cls, root: Path, env: dict[str, str], recipe: PanelRecipe, *,
                which: Callable[[str], str | None],
                run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> ProfileSession:
        """Detect support by checking the actual generated file; skip old/missing apps."""
        for client in CLIENTS:
            env.pop(client.env_key, None)  # Never inherit another session's path.
        discovered: dict[_Client, tuple[str, bytes]] = {}
        for client in CLIENTS:
            binary = which(client.binary)
            if not binary:
                continue
            contents = _render(client, recipe)
            target = root / client.filename
            _write_new(target, contents)
            if not _check(binary, client.check_flag, target, run):
                target.unlink()
                continue
            discovered[client] = (binary, contents)
            env[client.env_key] = str(target)
        return cls(root, discovered, run=run)

    @classmethod
    def from_environment(cls, env: Mapping[str, str], *,
                         run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> ProfileSession:
        root = Path(env["RICEBOWL_DE_SESSION_CONFIG"])
        marker = root / ".ricebowl-managed"
        info = root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or marker.is_symlink() or not marker.is_file()):
            raise ProfileError("RiceProfile requires a managed, owner-private session")
        discovered = {}
        for client in CLIENTS:
            path = root / client.filename
            if env.get(client.env_key) == str(path):
                discovered[client] = (client.binary, _private_file(path))
            elif client.env_key in env:
                raise ProfileError("RiceProfile path escapes its managed session")
        return cls(root, discovered, run=run)

    def status(self) -> dict[str, str]:
        return {client.binary: "managed" if client in self.clients else "not_managed"
                for client in CLIENTS}

    def preflight(self, recipe: PanelRecipe) -> dict[_Client, bytes]:
        """Validate all candidate files before any shell component is changed."""
        prepared = {}
        for client, (binary, previous) in self.clients.items():
            path = self.root / client.filename
            if _private_file(path) != previous:
                raise ProfileError("RiceProfile changed outside RiceBowl; refusing to overwrite")
            contents = _render(client, recipe)
            descriptor, temporary = tempfile.mkstemp(prefix=".riceprofile-check-", dir=self.root)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(contents)
                if not _check(binary, client.check_flag, Path(temporary), self.run):
                    raise ProfileError(f"{client.binary} rejected the candidate RiceProfile")
            finally:
                os.unlink(temporary)
            prepared[client] = contents
        return prepared

    def commit(self, prepared: Mapping[_Client, bytes]) -> dict[_Client, bytes]:
        """Swap each private file, with recovery if any swap fails."""
        original = {client: contents for client, (_, contents) in self.clients.items()}
        committed = []
        try:
            for client, contents in prepared.items():
                path = self.root / client.filename
                if _private_file(path) != original[client]:
                    raise ProfileError("RiceProfile changed during activation")
                _atomic_replace(path, contents)
                committed.append(client)
        except (OSError, ProfileError) as error:
            try:
                for client in reversed(committed):
                    _atomic_replace(self.root / client.filename, original[client])
            except OSError as recovery:
                raise ProfileError("RiceProfile rollback failed") from recovery
            raise ProfileError("RiceProfile activation failed; previous files restored") from error
        for client, contents in prepared.items():
            binary, _ = self.clients[client]
            self.clients[client] = (binary, contents)
        return original

    def restore(self, original: Mapping[_Client, bytes]) -> None:
        """Recover the previous appearance after a later compositor failure."""
        for client, previous in original.items():
            path = self.root / client.filename
            if _private_file(path) != self.clients[client][1]:
                raise ProfileError("RiceProfile changed externally; cannot safely restore")
            _atomic_replace(path, previous)
            binary, _ = self.clients[client]
            self.clients[client] = (binary, previous)

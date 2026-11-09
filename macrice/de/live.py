"""Owner-local control socket for explicit active Wayland rice changes.

Only the opt-in RiceBowl shell supervisor listens. No service, shell command,
or user-controlled executable is created by a recipe.
"""

from __future__ import annotations

import json
import os
import re
import select
import socket
import stat
import struct
import sys
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


MAX_MESSAGE = 2048
LIVE_VERSION = 1


class LiveError(RuntimeError):
    def __init__(self, message: str, *, code: str = "live_unavailable") -> None:
        super().__init__(message)
        self.code = code


def socket_path(env: Mapping[str, str]) -> Path:
    runtime = env.get("XDG_RUNTIME_DIR", "")
    display = env.get("WAYLAND_DISPLAY", "")
    if (not os.path.isabs(runtime) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,48}", display)
            or display in (".", "..")):
        raise LiveError("An active RiceBowl Wayland display is required")
    root = Path(runtime)
    try:
        info = root.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise OSError("unsafe runtime directory")
    except OSError as exc:
        raise LiveError("An owner-private XDG_RUNTIME_DIR is required") from exc
    path = root / f"ricebowl-live-{display}.sock"
    if len(os.fsencode(path)) > 103:  # AF_UNIX sun_path is 108 bytes on Linux.
        raise LiveError("Wayland runtime socket path is too long")
    return path


@contextmanager
def listen(env: Mapping[str, str]) -> Iterator[socket.socket]:
    path = socket_path(env)
    if os.path.lexists(path):
        info = path.lstat()
        if info.st_uid != os.geteuid() or not stat.S_ISSOCK(info.st_mode):
            raise LiveError("An unsafe RiceBowl control socket already exists")
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(0.3)
            try:
                probe.connect(str(path))
            except (ConnectionRefusedError, FileNotFoundError):
                path.unlink()  # Own stale socket in an already owner-private directory.
            else:
                raise LiveError("This Wayland display already has a RiceBowl supervisor")
    with socket.socket(socket.AF_UNIX) as listener:
        old_umask = os.umask(0o177)
        try:
            listener.bind(str(path))
        finally:
            os.umask(old_umask)
        listener.listen(2)
        identity = path.lstat().st_ino
        try:
            yield listener
        finally:
            try:
                if path.lstat().st_ino == identity:
                    path.unlink()
            except FileNotFoundError:
                pass


def _read_message(stream: socket.socket) -> dict:
    stream.settimeout(3)
    chunks = bytearray()
    while len(chunks) <= MAX_MESSAGE:
        block = stream.recv(MAX_MESSAGE + 1 - len(chunks))
        if not block:
            break
        chunks.extend(block)
        if b"\n" in block:
            break
    if len(chunks) > MAX_MESSAGE or not chunks.endswith(b"\n"):
        raise LiveError("Malformed or oversized live request", code="invalid_live_request")
    try:
        data = json.loads(chunks)
    except (ValueError, UnicodeError) as exc:
        raise LiveError("Malformed live request", code="invalid_live_request") from exc
    if not isinstance(data, dict) or set(data) != {"action", "recipe", "sha256", "expected"}:
        raise LiveError("Invalid live request fields", code="invalid_live_request")
    if (data["action"] not in ("status", "apply", "restore", "refresh-outputs")
            or any(value is not None and type(value) is not str for value in data.values())):
        raise LiveError("Unsupported live request", code="invalid_live_request")
    return data


def serve_once(listener: socket.socket, handler: Callable[[dict], dict], timeout: float = 0.2) -> None:
    if not select.select([listener], [], [], timeout)[0]:
        return
    connection, _ = listener.accept()
    with connection:
        try:
            # Linux SO_PEERCRED keeps other local users from selecting our rice.
            uid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
            if uid != os.geteuid():
                raise LiveError("RiceBowl control is owner-only", code="permission_denied")
            response = handler(_read_message(connection))
        except LiveError as exc:
            response = {"version": LIVE_VERSION, "ok": False,
                        "error": {"code": exc.code, "message": str(exc)}}
        except (OSError, ValueError, TimeoutError):
            response = {"version": LIVE_VERSION, "ok": False,
                        "error": {"code": "invalid_live_request", "message": "Invalid live request"}}
        except Exception as exc:
            # A client-triggered failure must never bring down the compositor.
            print(f"RiceBowl live request failed: {type(exc).__name__}", file=sys.stderr)
            response = {"version": LIVE_VERSION, "ok": False,
                        "error": {"code": "component_failed", "message": "Live switch failed safely"}}
        try:
            connection.sendall((json.dumps(response, separators=(",", ":")) + "\n").encode())
        except OSError:
            pass


def request(action: str, *, recipe: str | None = None, sha256: str | None = None,
            expected: str | None = None, environment: Mapping[str, str] | None = None) -> dict:
    env = os.environ if environment is None else environment
    path = socket_path(env)
    message = json.dumps({"action": action, "recipe": recipe, "sha256": sha256,
                          "expected": expected}, separators=(",", ":")) + "\n"
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(20)
            client.connect(str(path))
            client.sendall(message.encode())
            result = _read_response(client)
    except (OSError, ValueError, TimeoutError) as exc:
        raise LiveError("No responsive RiceBowl live Wayland supervisor") from exc
    return result


def _read_response(client: socket.socket) -> dict:
    data = bytearray()
    while len(data) <= MAX_MESSAGE:
        part = client.recv(MAX_MESSAGE + 1 - len(data))
        if not part:
            break
        data.extend(part)
        if b"\n" in part:
            break
    if len(data) > MAX_MESSAGE or not data.endswith(b"\n"):
        raise LiveError("Invalid supervisor response")
    result = json.loads(data)
    if not isinstance(result, dict) or result.get("version") != LIVE_VERSION:
        raise LiveError("Incompatible supervisor response")
    return result

"""RiceClip: opt-in, event-driven Wayland clipboard history held only in RAM."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

MAX_TEXT = 512 * 1024
MAX_IMAGE = 4 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_ITEMS = 50
MAX_MESSAGE = 6 * 1024 * 1024
MIMES = ("text/plain;charset=utf-8", "text/uri-list", "image/png")


class ClipError(RuntimeError):
    pass


def _socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime or not Path(runtime).is_dir():
        raise ClipError("No private XDG_RUNTIME_DIR available")
    directory = Path(runtime) / "ricebowl"
    if not directory.exists():
        directory.mkdir(mode=0o700)
    if (directory.is_symlink() or directory.stat().st_uid != os.getuid()
            or directory.stat().st_mode & 0o077):
        raise ClipError("RiceBowl runtime directory is not owner-private")
    return directory / "riceclip.sock"


@dataclass
class Item:
    id: str
    mime: str
    data: bytes
    preview: str
    pinned: bool = False


class History:
    def __init__(self) -> None:
        self.items: deque[Item] = deque()
        self.paused = False

    def add(self, mime: str, data: bytes) -> bool:
        if self.paused or mime not in MIMES or not data:
            return False
        if len(data) > (MAX_IMAGE if mime == "image/png" else MAX_TEXT):
            return False
        if mime == "image/png":
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                return False
            preview = f"Image · {len(data) / 1024:.0f} KiB"
        else:
            try:
                decoded = data.decode("utf-8")
            except UnicodeDecodeError:
                return False
            if "\x00" in decoded:
                return False
            preview = " ".join(decoded.split())[:180]
            if not preview:
                return False
        digest = hashlib.sha256(mime.encode("ascii") + b"\0" + data).hexdigest()
        prior = next((item for item in self.items if item.id == digest), None)
        if prior:
            self.items.remove(prior)
            self.items.appendleft(prior)
            return True
        while self.items and (len(self.items) >= MAX_ITEMS or
                              sum(len(item.data) for item in self.items) + len(data) > MAX_TOTAL):
            victim = next((item for item in reversed(self.items) if not item.pinned), None)
            if victim is None:
                return False
            self.items.remove(victim)
        self.items.appendleft(Item(digest, mime, data, preview))
        return True

    def list(self) -> list[dict[str, object]]:
        return [{"id": item.id, "mime": item.mime, "preview": item.preview,
                 "pinned": item.pinned} for item in self.items]

    def get(self, identifier: str) -> Item:
        for item in self.items:
            if item.id == identifier:
                return item
        raise ClipError("Clipboard item is no longer available")


def _request(operation: str, **arguments: object) -> dict[str, object]:
    request = json.dumps({"op": operation, **arguments}, separators=(",", ":")).encode() + b"\n"
    if len(request) > MAX_MESSAGE:
        raise ClipError("Clipboard item exceeds the transfer limit")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.settimeout(4)
        try:
            channel.connect(str(_socket_path()))
            channel.sendall(request)
            response = bytearray()
            while b"\n" not in response:
                chunk = channel.recv(65536)
                if not chunk or len(response) + len(chunk) > MAX_MESSAGE:
                    raise ClipError("RiceClip service returned an invalid reply")
                response.extend(chunk)
        except (OSError, socket.timeout) as exc:
            raise ClipError("RiceClip is not running; use 'ricebowl riceclip open'") from exc
    result = json.loads(response.split(b"\n", 1)[0])
    if not result.get("ok"):
        raise ClipError(str(result.get("error", "RiceClip request failed")))
    return result


def _handle(history: History, request: dict[str, object]) -> dict[str, object]:
    op = request.get("op")
    if op == "ingest":
        mime = request.get("mime")
        encoded = request.get("data")
        if not isinstance(mime, str) or not isinstance(encoded, str):
            raise ClipError("Invalid clipboard sample")
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ClipError("Invalid clipboard encoding") from exc
        return {"ok": True, "added": history.add(mime, data)}
    if op == "list":
        return {"ok": True, "items": history.list(), "paused": history.paused}
    if op == "clear":
        history.items.clear()
    elif op == "pause":
        history.paused = True
    elif op == "resume":
        history.paused = False
    elif op in ("pin", "unpin", "paste"):
        identifier = request.get("id")
        if not isinstance(identifier, str):
            raise ClipError("Choose a clipboard item")
        item = history.get(identifier)
        if op == "paste":
            copier = shutil.which("wl-copy")
            if not copier:
                raise ClipError("wl-copy is unavailable")
            try:
                subprocess.run([copier, "--type", item.mime], input=item.data,
                               timeout=10, check=True, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError) as exc:
                raise ClipError("Could not restore clipboard item") from exc
        else:
            item.pinned = op == "pin"
    elif op != "stop":
        raise ClipError("Unknown RiceClip operation")
    return {"ok": True}


def _serve() -> int:
    if not os.environ.get("WAYLAND_DISPLAY") or not shutil.which("wl-paste"):
        raise ClipError("RiceClip needs Wayland and wl-clipboard (wl-paste/wl-copy)")
    address = _socket_path()
    if os.path.lexists(address):
        raise ClipError("RiceClip socket already exists; inspect the running session")
    watcher: list[subprocess.Popen[bytes]] = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        old_umask = os.umask(0o077)
        try:
            server.bind(str(address))
        finally:
            os.umask(old_umask)
        os.chmod(address, stat.S_IRUSR | stat.S_IWUSR)
        server.listen(8)
        server.settimeout(3)
        history = History()
        try:
            launcher = str(Path(__file__).resolve().parents[2] / "launcher.py")
            for mime in MIMES:
                watcher.append(subprocess.Popen(
                    [shutil.which("wl-paste"), "--type", mime, "--watch",
                     sys.executable, launcher, "riceclip", "ingest", "--mime", mime],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True))
            while True:
                if all(proc.poll() is not None for proc in watcher):
                    raise ClipError("Wayland clipboard watch is unsupported or has disconnected")
                try:
                    client, _ = server.accept()
                except socket.timeout:
                    continue
                with client:
                    client.settimeout(5)
                    incoming = bytearray()
                    try:
                        while b"\n" not in incoming:
                            chunk = client.recv(65536)
                            if not chunk or len(incoming) + len(chunk) > MAX_MESSAGE:
                                raise ClipError("Invalid bounded RiceClip request")
                            incoming.extend(chunk)
                        payload = json.loads(incoming.split(b"\n", 1)[0])
                        if not isinstance(payload, dict):
                            raise ClipError("Invalid RiceClip request")
                        reply = _handle(history, payload)
                    except (ClipError, ValueError, OSError, socket.timeout) as exc:
                        reply = {"ok": False, "error": str(exc)}
                    client.sendall(json.dumps(reply).encode() + b"\n")
                    if reply.get("ok") and payload.get("op") == "stop":
                        break
        finally:
            for proc in watcher:
                proc.terminate() if proc.poll() is None else None
            for proc in watcher:
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            address.unlink(missing_ok=True)
    return 0


def _ingest(mime: str) -> int:
    limit = MAX_IMAGE if mime == "image/png" else MAX_TEXT
    data = sys.stdin.buffer.read(limit + 1)
    if 0 < len(data) <= limit:
        try:
            _request("ingest", mime=mime, data=base64.b64encode(data).decode("ascii"))
        except ClipError:
            pass  # Clipboard contents and failures are never logged by the watcher.
    return 0


def _ensure_started() -> None:
    try:
        _request("list")
        return
    except ClipError:
        address = _socket_path()
        if os.path.lexists(address):
            raise ClipError("RiceClip has a stale or inaccessible socket; no unsafe replacement")
    subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[2] / "launcher.py"),
                      "riceclip", "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    for _ in range(15):
        time.sleep(0.1)
        try:
            _request("list")
            return
        except ClipError:
            pass
    raise ClipError("RiceClip could not start; check Wayland data-control support")


def run(action: str, *, identifier: str | None = None, mime: str | None = None) -> int:
    if action == "serve":
        return _serve()
    if action == "ingest":
        return _ingest(mime or "")
    if action == "open":
        _ensure_started()
        from .riceclip_ui import show
        show(_request)
        return 0
    if action == "start":
        _ensure_started()
        print("RiceClip enabled for this session (RAM only)")
        return 0
    operation = {"copy": "paste", "status": "list"}.get(action, action)
    result = _request(operation, **({"id": identifier} if identifier else {}))
    if action in ("list", "status"):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0

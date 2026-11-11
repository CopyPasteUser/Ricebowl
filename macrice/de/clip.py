"""Opt-in, session-memory Wayland clipboard history.

The watcher owns no clipboard selection: wl-paste --watch delivers changes
through a short-lived receiver. Nothing starts with the desktop by default.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
from pathlib import Path

MAX_TEXT_BYTES = 64 * 1024
MAX_ITEMS = 20
MAX_REQUEST_BYTES = 512 * 1024
ERROR_MESSAGES = {
    "unavailable": "RiceClip requires a private XDG runtime directory and Wayland session",
    "not_running": "RiceClip is not running; explicitly start 'ricebowl de clip --clip-op watch'",
    "already_running": "RiceClip already has a watcher for this Wayland display",
    "watch_unavailable": "RiceClip needs wl-paste --watch and compositor data-control support",
    "invalid_request": "Invalid RiceClip operation or history index",
    "copy_unavailable": "Wayland clipboard copy requires wl-copy",
    "copy_failed": "Could not restore this RiceClip item to the clipboard",
}


class ClipError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(ERROR_MESSAGES[code])


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    display = os.environ.get("WAYLAND_DISPLAY")
    if not runtime or not display:
        raise ClipError("unavailable")
    root = Path(runtime)
    try:
        info = root.lstat()
    except OSError as exc:
        raise ClipError("unavailable") from exc
    if not (root.is_absolute() and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid() and not info.st_mode & 0o077):
        raise ClipError("unavailable")
    digest = hashlib.sha256(display.encode("utf-8")).hexdigest()[:16]
    return root / f"ricebowl-clip-{digest}.sock"


class History:
    def __init__(self):
        self.items: list[str] = []
        self.paused = False

    def handle(self, request: dict[str, object]) -> dict[str, object]:
        op = request.get("op")
        if op == "ingest":
            data = request.get("text")
            if (request.get("state") != "data" or not isinstance(data, str)
                    or len(data.encode("utf-8")) > MAX_TEXT_BYTES or "\x00" in data):
                return {"ok": True, "recorded": False}
            if self.paused or not data:
                return {"ok": True, "recorded": False}
            if data in self.items:
                self.items.remove(data)
            self.items.insert(0, data)
            del self.items[MAX_ITEMS:]
            return {"ok": True, "recorded": True}
        if op == "status":
            return {"ok": True, "paused": self.paused, "count": len(self.items),
                    "max_items": MAX_ITEMS, "max_text_bytes": MAX_TEXT_BYTES,
                    "persistent": False}
        if op == "list":
            return {"ok": True, "items": [
                {"index": index, "preview": item[:80], "characters": len(item)}
                for index, item in enumerate(self.items)]}
        if op == "clear":
            self.items.clear()
            return {"ok": True, "count": 0}
        if op in ("pause", "resume"):
            self.paused = op == "pause"
            return {"ok": True, "paused": self.paused}
        if op == "copy":
            index = request.get("index")
            if type(index) is not int or not 0 <= index < len(self.items):
                raise ClipError("invalid_request")
            copier = shutil.which("wl-copy")
            if not copier:
                raise ClipError("copy_unavailable")
            try:
                subprocess.run([copier, "--type", "text/plain;charset=utf-8"],
                               input=self.items[index].encode("utf-8"),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=10, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                raise ClipError("copy_failed") from exc
            return {"ok": True, "copied_index": index}
        raise ClipError("invalid_request")


def _transact(connection: socket.socket, history: History) -> None:
    connection.settimeout(2)
    data = bytearray()
    while b"\n" not in data and len(data) <= MAX_REQUEST_BYTES:
        part = connection.recv(min(8192, MAX_REQUEST_BYTES + 1 - len(data)))
        if not part:
            break
        data.extend(part)
    try:
        if len(data) > MAX_REQUEST_BYTES or not data.endswith(b"\n"):
            raise ClipError("invalid_request")
        request = json.loads(data.decode("utf-8"))
        if not isinstance(request, dict):
            raise ClipError("invalid_request")
        response = history.handle(request)
    except (ValueError, UnicodeError) as exc:
        code = exc.code if isinstance(exc, ClipError) else "invalid_request"
        response = {"ok": False, "error": code}
    connection.sendall(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")


def request(op: str, *, index: int | None = None, text: str | None = None,
            state: str | None = None) -> dict[str, object]:
    path = socket_path()
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(3)
            connection.connect(str(path))
            payload = {"op": op}
            if index is not None:
                payload["index"] = index
            if text is not None:
                payload.update(text=text, state=state)
            connection.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
            answer = bytearray()
            while b"\n" not in answer and len(answer) < MAX_REQUEST_BYTES:
                part = connection.recv(8192)
                if not part:
                    break
                answer.extend(part)
            result = json.loads(answer.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ClipError("not_running") from exc
    if not isinstance(result, dict):
        raise ClipError("invalid_request")
    if not result.get("ok"):
        code = result.get("error")
        raise ClipError(code if isinstance(code, str) and code in ERROR_MESSAGES
                        else "invalid_request")
    return result


def ingest() -> dict[str, object]:
    if os.environ.get("CLIPBOARD_STATE") != "data":
        return {"ok": True, "recorded": False}
    data = sys.stdin.buffer.read(MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES:
        return {"ok": True, "recorded": False}
    try:
        return request("ingest", text=data.decode("utf-8"), state="data")
    except UnicodeError:
        return {"ok": True, "recorded": False}


def watch(*, on_ready=None) -> None:
    path = socket_path()
    command = shutil.which("wl-paste")
    if not command:
        raise ClipError("watch_unavailable")
    server = socket.socket(socket.AF_UNIX)
    watcher = None
    original_termination = signal.getsignal(signal.SIGTERM)
    original_interrupt = signal.getsignal(signal.SIGINT)

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    try:
        try:
            server.bind(str(path))
        except OSError as exc:
            raise ClipError("already_running") from exc
        os.chmod(path, 0o600)
        inode = path.lstat().st_ino
        server.listen(4)
        server.settimeout(0.5)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            # The standalone .deb executes launcher.py from /usr/lib/ricebowl-wayland;
            # `python -m macrice` would not find that module from other CWDs.
            launcher = Path(__file__).resolve().parents[2] / "launcher.py"
            watcher = subprocess.Popen(
                [command, "--type", "text", "--watch", sys.executable, "-B",
                 str(launcher), "de", "clip", "--clip-op", "ingest"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise ClipError("watch_unavailable") from exc
        if on_ready:
            on_ready()
        history = History()
        while watcher.poll() is None:
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            with connection:
                try:
                    if hasattr(socket, "SO_PEERCRED"):
                        import struct
                        _pid, uid, _gid = struct.unpack("3i", connection.getsockopt(
                            socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        if uid != os.getuid():
                            continue
                    _transact(connection, history)
                except (OSError, TimeoutError):
                    continue
        raise ClipError("watch_unavailable")
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, original_termination)
        signal.signal(signal.SIGINT, original_interrupt)
        if watcher is not None and watcher.poll() is None:
            watcher.terminate()
            try:
                watcher.wait(timeout=3)
            except subprocess.TimeoutExpired:
                watcher.kill()
                watcher.wait()
        server.close()
        try:
            if path.lstat().st_ino == locals().get("inode"):
                path.unlink()
        except FileNotFoundError:
            pass

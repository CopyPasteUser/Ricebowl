"""On-demand, isolated interactive Creator preview in a nested labwc window.

This is deliberately separate from the confirmed live apply/restore protocol.
It runs only a reviewed immutable private draft and never changes selection.
"""

from __future__ import annotations

import os
import select
import shutil
import signal
import subprocess
import sys
import time
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from . import creator_activation, creator_workspace, session

_STOP_GRACE_SECONDS = 4


class InteractivePreviewError(ValueError):
    """An isolated Creator session could not safely start."""


@dataclass(frozen=True)
class PreviewResult:
    exit_code: int
    stopped_by_user: bool
    diagnostic: str


class InteractivePreview:
    """Own exactly one compositor process and its bounded exit diagnostics."""

    def __init__(self, process: subprocess.Popen[bytes], draft: creator_workspace.DraftInfo,
                 on_exit: Callable[[InteractivePreview, PreviewResult], None]):
        self.process = process
        self.draft = draft
        self._on_exit = on_exit
        self._stopping = False
        self._lock = threading.Lock()
        self._finished = threading.Event()
        threading.Thread(target=self._watch, name="ricebowl-creator-interactive-watch",
                         daemon=True).start()

    def _watch(self) -> None:
        tail = bytearray()
        stream = self.process.stderr
        exited_at: float | None = None
        try:
            if stream is not None:
                descriptor = stream.fileno()
                while True:
                    readable, _, _ = select.select([descriptor], [], [], 0.2)
                    if readable:
                        chunk = os.read(descriptor, 4096)
                        if not chunk:
                            break
                        tail.extend(chunk)
                        if len(tail) > 8192:
                            del tail[:-8192]
                    elif self.process.poll() is not None:
                        if exited_at is None:
                            exited_at = time.monotonic()
                        if time.monotonic() - exited_at >= 2:
                            break  # Do not wait indefinitely for a leaked child's stderr.
            code = self.process.wait()
        except (OSError, ValueError) as exc:
            code = self.process.poll()
            tail.extend(str(exc).encode("utf-8", errors="replace"))
        finally:
            if stream is not None:
                stream.close()
            self._finished.set()
        lines = tail.decode("utf-8", errors="replace").splitlines()
        # No terminal control sequences or unbounded compositor logs in GTK UI.
        detail = " ".join("".join(c for c in line if c.isprintable()) for line in lines[-3:])[-350:]
        self._on_exit(self, PreviewResult(code if code is not None else -1,
                                          self._stopping, detail))

    def stop(self) -> None:
        """Request graceful compositor exit, then enforce bounded teardown."""
        with self._lock:
            if self._stopping or self._finished.is_set():
                return
            self._stopping = True
        try:
            # Each preview has its own process group. Include dbus-run-session
            # and compositor children, so a wrapper's early exit cannot leave
            # an orphaned test shell. The shell handles TERM for owned cleanup.
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            if self.process.poll() is None:
                self.process.terminate()

        def enforce():
            if self._finished.wait(_STOP_GRACE_SECONDS):
                return
            if self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        threading.Thread(target=enforce, name="ricebowl-creator-interactive-stop",
                         daemon=True).start()


def launch(draft: creator_workspace.DraftInfo,
           on_exit: Callable[[InteractivePreview, PreviewResult], None], *,
           environment: Mapping[str, str] | None = None,
           which: Callable[[str], str | None] = shutil.which,
           spawn: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen) -> InteractivePreview:
    """Start a separately isolated, interactive native RicePlate test window.

    This path deliberately does not use the live supervisor, install a recipe,
    select a rice, or change next-login persistence.
    """
    try:
        checked = creator_activation._checked_draft(draft)
    except creator_activation.ActivationError as exc:
        raise InteractivePreviewError(str(exc)) from exc
    if os.geteuid() == 0:
        raise InteractivePreviewError("Interactive Wayland previews cannot run as root")
    env = dict(os.environ if environment is None else environment)
    if not (env.get("WAYLAND_DISPLAY") or env.get("DISPLAY")):
        raise InteractivePreviewError("Open Creator in a graphical X11 or Wayland desktop")
    try:
        session._check_runtime_dir(env)
    except session.SessionError as exc:
        raise InteractivePreviewError(str(exc)) from exc
    required = (*session.REQUIRED_TOOLS, "riceplate-native")
    missing = [name for name in required if not which(name)]
    if not env.get("DBUS_SESSION_BUS_ADDRESS") and not which("dbus-run-session"):
        missing.append("dbus-run-session")
    if missing:
        raise InteractivePreviewError("Install the nested Wayland dependencies: " +
                                      ", ".join(missing))
    launcher = session.project_root() / "launcher.py"
    if not launcher.is_file():
        raise InteractivePreviewError("RiceBowl launcher is missing from this installation")
    for name in ("RICEBOWL_DE_SHELL_CHILD", "RICEBOWL_DE_SESSION_CONFIG",
                 "RICEBOWL_RENDER_SESSION", "WLR_HEADLESS_OUTPUTS", "WLR_BACKENDS"):
        env.pop(name, None)
    argv = [sys.executable, str(launcher), "de", "start", "--nested", "--panel", "native",
            "--recipe", str(checked.path)]
    try:
        process = spawn(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
    except OSError as exc:
        raise InteractivePreviewError(f"Could not start the nested compositor: {exc}") from exc
    return InteractivePreview(process, checked, on_exit)

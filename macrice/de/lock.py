"""Full-session Wayland screen lock with best-effort RiceClip memory cleanup.

Only an already-running opt-in watcher is contacted. No history is copied,
read, persisted, logged, or exposed to the locker.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping

from . import clip


class ScreenLockError(RuntimeError):
    """The compositor was not successfully locked."""


def lock_screen(
    *,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    clear: Callable[[str], dict[str, object]] = clip.request,
) -> dict[str, object]:
    """Lock the active full RiceBowl session before clearing volatile history.

    swaylock -f returns once the compositor reports the screen locked, and
    swayidle -w waits for our command before allowing suspend. Failed
    cleanup NEVER prevents the user from getting a locked screen.
    """
    env = dict(os.environ if environment is None else environment)
    if (env.get("RICEBOWL_DE_NESTED") != "0"
            or env.get("RICEBOWL_DE_SHELL_CHILD") != "1"
            or not env.get("WAYLAND_DISPLAY")):
        raise ScreenLockError("Screen locking is available only in a full RiceBowl Wayland session")
    locker = which("swaylock")
    if not locker:
        raise ScreenLockError("swaylock is unavailable; screen not locked")
    try:
        run([locker, "-f"], check=True, timeout=20, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScreenLockError("swaylock failed; screen lock not confirmed") from exc

    # Never block/unlock the actual screen on a missing, terminated or busy
    # clipboard watcher; report the distinction rather than pretending clean.
    try:
        # Pause first so asynchronous clipboard events cannot re-fill history
        # immediately after the clear. User must explicitly resume recording
        # after unlock; this is intentional privacy-first behavior.
        pause = clear("pause")
        cleared = clear("clear") if pause.get("ok") and pause.get("paused") else {"ok": False}
    except clip.ClipError as exc:
        # RiceClip is disabled by default. A verified absent socket is not a
        # failure; a socket that exists but cannot be reached is a warning.
        inactive = False
        if exc.code == "not_running":
            try:
                inactive = not clip.socket_path().exists()
            except clip.ClipError:
                pass
        return {"locked": True, "riceclip_cleared": False,
                "riceclip_inactive": inactive}
    except OSError:
        return {"locked": True, "riceclip_cleared": False,
                "riceclip_inactive": False}
    return {"locked": True, "riceclip_cleared": bool(cleared.get("ok")),
            "riceclip_inactive": False}

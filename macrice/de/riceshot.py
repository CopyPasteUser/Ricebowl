"""RiceShot: explicit, bounded Wayland capture with optional native annotation."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .capture import CaptureError, capture


class ShotError(ValueError):
    pass


def _select(mode: str) -> str | None:
    if mode == "full":
        return None
    slurp = shutil.which("slurp")
    if not slurp:
        raise ShotError("Install slurp for interactive region/monitor selection")
    try:
        result = subprocess.run([slurp, "-o"] if mode == "monitor" else [slurp],
                                capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ShotError("Region selection unavailable or timed out") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise ShotError("Screenshot selection cancelled")
    return result.stdout.strip()


def _safe_save(source: Path, destination: Path) -> Path:
    if not destination.is_absolute() or destination.suffix.lower() != ".png":
        raise ShotError("Choose an absolute new .png filename")
    if not destination.parent.is_dir():
        raise ShotError("The destination directory does not exist")
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise ShotError("Destination exists or cannot be created; nothing overwritten") from exc
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise ShotError("Failed to save screenshot") from exc
    return destination


def shoot(*, mode: str = "region", destination: Path | None = None,
          clipboard: bool = False, annotate: bool = False) -> Path | None:
    """Capture on demand. Never overwrite a destination or persist a temp capture."""
    if mode not in ("full", "monitor", "region"):
        raise ShotError("Choose full, monitor or region")
    if destination is not None and (not destination.is_absolute()
                                    or destination.suffix.lower() != ".png"
                                    or os.path.lexists(destination)):
        raise ShotError("Choose a new absolute .png filename (no overwrite)")
    if not os.environ.get("WAYLAND_DISPLAY"):
        raise ShotError("RiceShot requires a running Wayland desktop")
    if annotate and not shutil.which("swappy"):
        raise ShotError("Install swappy to crop, draw, add text/arrows or blur")
    if clipboard and not shutil.which("wl-copy"):
        raise ShotError("Install wl-clipboard to copy screenshots")
    if destination is None and not clipboard:
        folder = Path.home() / "Pictures" / "Screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"RiceShot-{datetime.now():%Y%m%d-%H%M%S-%f}.png"
    # Selecting may be cancelled without ever taking a screenshot.
    geometry = _select(mode)
    with tempfile.TemporaryDirectory(prefix="riceshot-") as directory:
        os.chmod(directory, 0o700)
        raw = Path(directory) / "original.png"
        try:
            capture(raw, geometry=geometry)
        except CaptureError as exc:
            raise ShotError(str(exc)) from exc
        source = raw
        if annotate:
            annotated = Path(directory) / "annotated.png"
            try:
                result = subprocess.run([shutil.which("swappy"), "-f", str(raw),
                                         "-o", str(annotated)],
                                        stderr=subprocess.DEVNULL, timeout=900, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ShotError("Annotation editor failed") from exc
            if result.returncode != 0 or not annotated.is_file():
                raise ShotError("Annotation cancelled; no screenshot was saved")
            # Check the edited PNG against the same size limits as unedited captures.
            with annotated.open("rb") as edited:
                png_signature = edited.read(8)
            if (not 57 <= annotated.stat().st_size <= 64 * 1024 * 1024
                    or png_signature != b"\x89PNG\r\n\x1a\n"):
                raise ShotError("Annotation output is not a valid bounded PNG")
            source = annotated
        if clipboard:
            try:
                subprocess.run([shutil.which("wl-copy"), "--type", "image/png"],
                               input=source.read_bytes(), timeout=15, check=True,
                               stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError) as exc:
                raise ShotError("Copy to clipboard failed") from exc
        return _safe_save(source, destination) if destination is not None else None

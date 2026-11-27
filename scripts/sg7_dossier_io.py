"""Publish SG7 evidence exactly once without exposing partially written JSON.

This is a software-evidence artifact writer, not a cryptographic attestation.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class DossierWriteError(ValueError):
    """An SG7 dossier could not be published atomically and exclusively."""


def publish_dossier(path: Path, report: object) -> None:
    """Write and fsync private JSON, then link it without replacing a target.

    The temporary file is on the destination filesystem; hard-linking it is
    atomic and fails with EEXIST for any existing target, including symlinks.
    Never rename over a report from another run.
    """
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         prefix=f".{path.name}.", suffix=".tmp",
                                         dir=path.parent, delete=False) as stream:
            temp_path = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_path, path)
    except (OSError, TypeError, ValueError) as exc:
        raise DossierWriteError("SG7 dossier could not be safely published") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                # The temporary file contains no credentials; a failed cleanup
                # must never turn a failed publication into a success claim.
                pass

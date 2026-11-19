#!/usr/bin/python3
"""Use Ubuntu's signed public archive instead of a stuck EC2 regional mirror.

GitHub's ephemeral Ubuntu 24.04 runner sometimes spends the full 28-minute
Wayland install budget downloading dozens of packages from its region-local
EC2 mirror. This edits *only* that runner's archive URI, not apt trust,
distribution/suites, security.ubuntu.com, packages, or the user's machine.
"""
from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path


SOURCES = Path("/etc/apt/sources.list.d/ubuntu.sources")
_EC2_ARCHIVE = re.compile(
    r"http://[a-z0-9-]+\.ec2\.archive\.ubuntu\.com/ubuntu(?=/|\s|$)"
)
_PUBLIC_ARCHIVE = "https://archive.ubuntu.com/ubuntu"


def rewrite_sources(text: str) -> str:
    """Replace only Ubuntu's EC2 archive endpoint; leave trust/other repos alone."""
    return _EC2_ARCHIVE.sub(_PUBLIC_ARCHIVE, text)


def update_runner_sources(path: Path = SOURCES) -> bool:
    """Atomic one-file update; fail closed if the expected .sources is unsafe."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.geteuid() != 0:
        raise RuntimeError("Ubuntu mirror selection is restricted to root in GitHub Actions")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise RuntimeError("Unexpected runner Ubuntu archive source file")
    current = path.read_text(encoding="utf-8")
    changed = rewrite_sources(current)
    if changed == current:
        return False
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".ubuntu-sources-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as dest:
            os.fchmod(dest.fileno(), stat.S_IMODE(info.st_mode))
            dest.write(changed)
            dest.flush()
            os.fsync(dest.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    print("Public Ubuntu archive selected" if update_runner_sources()
          else "Runner Ubuntu archive already configured")

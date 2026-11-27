#!/usr/bin/python3
"""Explicitly link one real video source to one real receiver in private CI.

This does not create frames or fabricate a receipt. It replaces the automatic
PipeWire session-policy link only in a disposable no-DRM software acceptance
environment. The actual portal FD and Gst.Sample are checked separately.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import time


def verified_video_ports(objects: object) -> tuple[int, int] | None:
    if not isinstance(objects, list):
        raise ValueError("PipeWire registry must be an array")
    nodes: dict[int, dict] = {}
    ports: list[tuple[int, int, str]] = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        info = obj.get("info")
        if not isinstance(info, dict):
            continue
        props = info.get("props")
        ident = obj.get("id")
        if type(ident) is not int or not isinstance(props, dict) or ident < 1:
            continue
        if obj.get("type") == "PipeWire:Interface:Node":
            nodes[ident] = props
        elif obj.get("type") == "PipeWire:Interface:Port":
            raw_node = props.get("node.id")
            if type(raw_node) in (str, int) and str(raw_node).isdecimal():
                ports.append((ident, int(raw_node), props.get("port.direction", "")))
    sources = [n for n, p in nodes.items()
               if p.get("media.class") == "Video/Source"
               and str(p.get("node.name", "")).startswith("xdp-capture-")]
    consumers = [n for n, p in nodes.items()
                 if p.get("node.name") == "ricebowl-ci-consumer"]
    if len(sources) != 1 or len(consumers) != 1:
        return None
    out = [i for i, n, direction in ports if n == sources[0] and direction == "out"]
    inp = [i for i, n, direction in ports if n == consumers[0] and direction == "in"]
    if len(out) != 1 or len(inp) != 1 or out[0] == inp[0]:
        return None
    return out[0], inp[0]


def checked_runtime() -> None:
    env = os.environ
    # Disposable runner: hosted Actions, or a local-CI step in a container
    # provisioned for it (same rule as scripts/ci_portal_generic_remote.py).
    if (env.get("GITHUB_ACTIONS") != "true"
            and env.get("RICEBOWL_LOCAL_CI_DISPOSABLE") != "1"):
        raise RuntimeError("Refusing to link outside strict disposable CI")
    if any(env.get(k) != v for k, v in {
        "RICEBOWL_PORTAL_CAPTURE_CI": "1",
        "RICEBOWL_PORTAL_STRICT_CI": "1",
        "RICEBOWL_PORTAL_BACKEND": "generic",
        "WLR_BACKENDS": "headless",
        "WLR_RENDERER": "pixman",
    }.items()):
        raise RuntimeError("Refusing to link outside strict disposable CI")
    runtime = Path(env.get("XDG_RUNTIME_DIR", ""))
    if not runtime.is_absolute() or runtime.is_symlink():
        raise RuntimeError("Invalid private PipeWire runtime")
    mode = runtime.stat()
    if not stat.S_ISDIR(mode.st_mode) or mode.st_uid != os.geteuid() or stat.S_IMODE(mode.st_mode) != 0o700:
        raise RuntimeError("PipeWire runtime is not owner-private")
    marker = runtime / ".ricebowl-portal-ci"
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("Missing private portal CI marker")
    sock = runtime / "pipewire-0"
    if sock.is_symlink() or not stat.S_ISSOCK(sock.stat().st_mode):
        raise RuntimeError("Missing private PipeWire server socket")


def main() -> int:
    checked_runtime()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            proc = subprocess.run(["pw-dump"], capture_output=True, text=True,
                                  check=False, timeout=3)
            if proc.returncode == 0 and len(proc.stdout) < 2_000_000:
                pair = verified_video_ports(json.loads(proc.stdout))
                if pair is not None:
                    out_port, in_port = pair
                    linked = subprocess.run(["pw-link", str(out_port), str(in_port)],
                                            capture_output=True, text=True,
                                            check=False, timeout=4)
                    if linked.returncode != 0:
                        raise RuntimeError("Explicit private video link failed: " +
                                           linked.stderr.strip()[:300])
                    print(f"PORTAL_CI_LINK_OK: private source port={out_port} "
                          f"consumer port={in_port}", flush=True)
                    return 0
        except (ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
            pass  # An initial partial registry must not pass as a real link.
        time.sleep(0.15)
    raise RuntimeError("PORTAL_CI_LINK_FAIL: no unique private video receiver/source ports")


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify exact-source main-branch CI evidence before assembling 1.0 artifacts.

This is a release-time network check, not a physical-device certificate.
The stable sign-off commit may differ from the tested commit ONLY in the
sign-off JSON; check_release_contract.py verifies that before this script.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REQUIRED = {
    ".github/workflows/ci.yml": "Tests",
    ".github/workflows/riceplate-native.yml": "Native RicePlate prototype",
    ".github/workflows/wayland-session.yml": "Wayland session preview",
    # Real, strict PipeWire screen frames are separate from generic portal
    # endpoint smoke. This gate is dispatch-only on the exact release source.
    ".github/workflows/wayland-portal-strict.yml": "Strict Wayland portals and PipeWire frames",
}
ROOT = Path(__file__).resolve().parents[1]


class WorkflowGateError(ValueError):
    """A release candidate lacks current, successful workflow evidence."""


def validate_runs(payload: object, source_sha: str) -> dict[str, int]:
    """Require all four exact-source software workflows before any 1.0 tag."""
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        raise WorkflowGateError("Malformed GitHub Actions evidence")
    selected: dict[str, dict] = {}
    for run in payload["workflow_runs"]:
        if not isinstance(run, dict):
            continue
        path = run.get("path")
        if (not isinstance(path, str) or path not in REQUIRED
                or run.get("name") != REQUIRED[path]
                or run.get("head_sha") != source_sha
                or run.get("head_branch") != "main"):
            continue
        # Tests runs on main pushes. Native + session lanes may be dispatched
        # at the exact main SHA when a path-filtered change does not trigger
        # them. The strict portal workflow has NO push trigger; require an
        # explicit exact-source dispatch, never an unrelated PR run.
        if path == ".github/workflows/ci.yml":
            allowed_events = ("push",)
        elif path == ".github/workflows/wayland-portal-strict.yml":
            allowed_events = ("workflow_dispatch",)
        else:
            allowed_events = ("push", "workflow_dispatch")
        if run.get("event") not in allowed_events:
            continue
        run_id = run.get("id")
        if not isinstance(run_id, int) or isinstance(run_id, bool):
            continue
        if path not in selected or run_id > selected[path]["id"]:
            selected[path] = run
    for path, name in REQUIRED.items():
        run = selected.get(path)
        if run is None:
            raise WorkflowGateError(f"Missing exact-source main push CI: {name}")
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            raise WorkflowGateError(f"Latest exact-source CI is not green: {name}")
    return {path: selected[path]["id"] for path in REQUIRED}


def source_for_tag(tag: str, tag_sha: str, root: Path = ROOT) -> str:
    if tag == "v1.0.0":
        try:
            data = json.loads((root / ".github/release-signoff-1.0.json")
                              .read_text(encoding="utf-8"))
            sha = data["tested_source_commit"]
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise WorkflowGateError("Missing stable release source sign-off") from exc
    else:
        sha = tag_sha
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise WorkflowGateError("Invalid exact-source SHA for release verification")
    return sha


def fetch_evidence(repository: str, sha: str, token: str) -> object:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
        raise WorkflowGateError("Missing trusted GitHub repository/token context")

    # Exact-source Actions runs are paginated. A truncated first page can
    # hide a required workflow (or its latest attempt), so incomplete or
    # inconsistent API results must block release rather than certify it.
    runs: list[dict] = []
    total_count: int | None = None
    page_size = 100
    max_pages = 10
    for page in range(1, max_pages + 1):
        url = (f"https://api.github.com/repos/{repository}/actions/runs?"
               + urllib.parse.urlencode({
                   "head_sha": sha, "per_page": page_size, "page": page,
               }))
        request = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "RiceBowl-Release-CI-Gate",
        })
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            raise WorkflowGateError("Cannot obtain trusted GitHub workflow evidence") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
            raise WorkflowGateError("Malformed paginated GitHub workflow evidence")
        batch = payload["workflow_runs"]
        count = payload.get("total_count")
        if (not isinstance(count, int) or isinstance(count, bool)
                or count < 0 or len(batch) > page_size):
            raise WorkflowGateError("Invalid GitHub workflow evidence count")
        if total_count is None:
            total_count = count
        if count != total_count:
            raise WorkflowGateError("GitHub workflow evidence changed during pagination")
        runs.extend(batch)
        if len(runs) == total_count:
            return {"workflow_runs": runs}
        if len(batch) < page_size or len(runs) > total_count:
            raise WorkflowGateError("Incomplete paginated GitHub workflow evidence")

    raise WorkflowGateError("Too many exact-source workflow runs to verify safely")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    try:
        sha = source_for_tag(args.tag, os.environ.get("GITHUB_SHA", ""))
        evidence = fetch_evidence(os.environ.get("GITHUB_REPOSITORY", ""),
                                  sha, os.environ.get("GH_TOKEN", ""))
        runs = validate_runs(evidence, sha)
    except WorkflowGateError as exc:
        print(f"RiceBowl release CI gate: BLOCKED — {exc}", file=sys.stderr)
        return 1
    for path, run_id in runs.items():
        print(f"Verified {path} at {sha[:12]}: run {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

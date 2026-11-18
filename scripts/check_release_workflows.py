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
    # endpoint smoke. Accept only exact-main path-filtered push or dispatch.
    ".github/workflows/wayland-portal-strict.yml": "Strict Wayland portals and PipeWire frames",
}
ROOT = Path(__file__).resolve().parents[1]

# A green workflow may contain skipped or conditionally omitted jobs. A
# software release cannot infer that the native/portal acceptance actually
# ran merely from the workflow run's top-level success conclusion.
REQUIRED_JOBS = {
    ".github/workflows/ci.yml": ("test",),
    ".github/workflows/riceplate-native.yml": ("native-layer-shell",),
    ".github/workflows/wayland-session.yml": ("session-smoke",),
    ".github/workflows/wayland-portal-strict.yml":
        ("portal-unit", "portal-pixman-repeat", "portal-strict-software-frame"),
}


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
        # Tests runs only on main pushes. Path-filtered Native/Wayland/
        # Strict-Portal workflows can also be explicitly dispatched at the
        # exact main SHA. PR runs never satisfy release provenance.
        if path == ".github/workflows/ci.yml":
            allowed_events = ("push",)
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
            raise WorkflowGateError(f"Missing exact-source trusted-main CI: {name}")
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            raise WorkflowGateError(f"Latest exact-source CI is not green: {name}")
    return {path: selected[path]["id"] for path in REQUIRED}


def validate_jobs(evidence: object, selected: dict[str, int]) -> None:
    """Reject missing, skipped, failed or borrowed required CI job evidence."""
    if (not isinstance(evidence, dict) or set(evidence) != set(REQUIRED_JOBS)
            or set(selected) != set(REQUIRED_JOBS)):
        raise WorkflowGateError("Incomplete exact-source CI job evidence")
    for path, required in REQUIRED_JOBS.items():
        jobs = evidence.get(path)
        if not isinstance(jobs, list) or len(jobs) > 1000:
            raise WorkflowGateError("Malformed exact-source CI job evidence")
        for name in required:
            matches = [job for job in jobs
                       if isinstance(job, dict) and job.get("name") == name]
            if len(matches) != 1:
                raise WorkflowGateError(f"Required workflow job missing or ambiguous: {name}")
            job = matches[0]
            if (type(job.get("run_id")) is not int or job["run_id"] != selected[path]
                    or job.get("status") != "completed"
                    or job.get("conclusion") != "success"):
                raise WorkflowGateError(f"Required workflow job not green: {name}")


def fetch_job_evidence(repository: str, selected: dict[str, int],
                       token: str) -> dict[str, list[dict]]:
    """Read every required workflow's latest-attempt jobs, never a first-page subset."""
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not token or set(selected) != set(REQUIRED_JOBS)
            or any(type(value) is not int or value <= 0 for value in selected.values())):
        raise WorkflowGateError("Missing trusted job verification context")
    results: dict[str, list[dict]] = {}
    for path, run_id in selected.items():
        jobs: list[dict] = []
        total: int | None = None
        for page in range(1, 11):
            url = (f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs?"
                   + urllib.parse.urlencode({"per_page": 100, "page": page}))
            request = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "RiceBowl-Release-Job-Gate",
            })
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    payload = json.load(response)
            except (OSError, ValueError, urllib.error.HTTPError) as exc:
                raise WorkflowGateError("Cannot obtain trusted CI job evidence") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
                raise WorkflowGateError("Malformed GitHub CI jobs response")
            batch = payload["jobs"]
            count = payload.get("total_count")
            if (type(count) is not int or count < 0 or len(batch) > 100
                    or (total is not None and count != total)):
                raise WorkflowGateError("Inconsistent GitHub CI job pagination")
            total = count
            jobs.extend(batch)
            if len(jobs) == total:
                break
            if len(batch) < 100 or len(jobs) > total:
                raise WorkflowGateError("Incomplete GitHub CI job pagination")
        else:
            raise WorkflowGateError("Too many GitHub CI jobs to verify safely")
        results[path] = jobs
    return results


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
        jobs = fetch_job_evidence(os.environ.get("GITHUB_REPOSITORY", ""),
                                  runs, os.environ.get("GH_TOKEN", ""))
        validate_jobs(jobs, runs)
    except WorkflowGateError as exc:
        print(f"RiceBowl release CI gate: BLOCKED — {exc}", file=sys.stderr)
        return 1
    for path, run_id in runs.items():
        print(f"Verified {path} at {sha[:12]}: run {run_id}; required jobs green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

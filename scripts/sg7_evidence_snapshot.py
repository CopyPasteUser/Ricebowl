"""Stable, read-only trusted-run identity for SG7's exact-main dossier.

Only run identities and gate-relevant mutable states are compared. Unrelated
PR/untrusted workflow events cannot turn a missing exact-main proof green.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_TESTS_WORKFLOW = ".github/workflows/ci.yml"


def trusted_run_snapshot(evidence: object, source_sha: str,
                         required: Mapping[str, str]) -> tuple[tuple[str, int, int, str, str], ...]:
    """Return a deterministic accepted-workflow snapshot, or reject malformed proof.

    A newer pending/failed run, run rerun, changed conclusion or disappearing
    run must be noticed before the publisher claims one stable source state.
    """
    if (not isinstance(source_sha, str) or not _SHA.fullmatch(source_sha)
            or not isinstance(required, Mapping)
            or not required or any(not isinstance(path, str) or not isinstance(name, str)
                                    for path, name in required.items())
            or type(evidence) is not dict
            or type(evidence.get("workflow_runs")) is not list):
        raise ValueError("Malformed exact-source workflow snapshot")
    observed = set()
    rows = []
    for run in evidence["workflow_runs"]:
        if not isinstance(run, dict):
            continue
        path = run.get("path")
        if (type(path) is not str or path not in required
                or run.get("name") != required[path]
                or run.get("head_branch") != "main"
                or run.get("head_sha") != source_sha
                or run.get("event") not in (("push",) if path == _TESTS_WORKFLOW
                                            else ("push", "workflow_dispatch"))):
            continue
        identity = run.get("id")
        # The GitHub workflow-runs REST response includes run_attempt. If it
        # disappears, silently assuming attempt 1 could launder a rerun.
        attempt = run.get("run_attempt")
        status = run.get("status")
        conclusion = run.get("conclusion")
        if (type(identity) is not int or identity <= 0
                or type(attempt) is not int or attempt <= 0
                or type(status) is not str or not status
                or conclusion is not None and (type(conclusion) is not str
                                               or not conclusion)):
            raise ValueError("Invalid trusted workflow run identity or state")
        key = (path, identity)
        if key in observed:
            raise ValueError("Duplicate trusted workflow run")
        observed.add(key)
        rows.append((path, identity, attempt, status, conclusion or ""))
    return tuple(sorted(rows))

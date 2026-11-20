# SG6 two-runner build evidence — PR preflight vs trusted main

**Purpose:** build the *real* Core, Native, Session, and Desktop Debian
packages independently on two Ubuntu 24.04 GitHub-hosted runners and compare
all four archive byte streams in a third job.

The `sg6-cross-runner.yml` workflow runs in two distinct trust modes:

| Trigger | Source | Build+compare | OIDC/attestation | SG6 sign-off |
| --- | --- | --- | --- | --- |
| Relevant `pull_request` | GitHub test merge commit (`GITHUB_SHA`) | Yes, two VMs and third comparison job | **Never** | No |
| Deliberate `workflow_dispatch` on `main` | Exact checked-out main SHA, checked against live ref | Yes | Separate `attest` job after comparison | Requires independent review; not automatic |

A passing PR comparison is useful to catch real compilation/packaging and
cross-runner differences **before** integration. It is not an exact-main
provenance receipt, physical Mint acceptance or authorization for release.

## What the verifier actually checks

- Receipts from each hosted runner contain matching exact source SHA,
  non-colliding runner identities, matching build-tool versions, timestamp
  and lockfile SHA-256.
- The third runner independently computes the lockfile digest and source
  commit timestamp *from its checkout*, rejecting two mutually consistent
  receipts that disagree with the actual committed inputs.
- Every package file must exist as an ordinary file, match its individual
  receipt SHA-256 and be byte-identical on both runners.
- Duplicate JSON keys, extra fields, malformed identities, symlinked
  evidence inputs and inconsistent source toolchains fail closed.

The compare report explicitly sets
`independent_external_provenance_certified=false`. This workflow proves
**independent hosted-runner repeatability**, not third-party supply-chain
provenance. Attesting the *comparison report* binds that report to a trusted
main Actions run, not the original ELF to an external auditor's toolchain.

## Reproduce

- Run `python3 -m unittest tests.test_sg6_cross_runner tests.test_sg6_workflow_policy -v`.
- Open a PR touching SG6 verifier or workflow sources; require both
  `Build four debs` jobs and `Compare actual packages` to succeed.
- After integration, deliberately dispatch `SG6 independent-runner
  four-deb reproducibility` on the **new** `main`. Verify the `attest`
  job, downloaded report, run event, source SHA and all four digests.
- After further merges, previous main receipts are historical and do not
  satisfy an exact-final-main release dossier.

## Remaining SG6 blockers

- Full Core/Native/Session/Meta multi-version transition and interrupted
  `dpkg` recovery from actual immutable builds, not stamped relabels.
- Disposable Mint-compatible install/rollback test environment.
- Further external, reproducible toolchain provenance and independently
  reviewed supply-chain claims.
- Final exact-main CI, XFCE preservation review and physical Mint/ThinkPad
  sign-off (physical checks remain a separate, later release gate).

This preflight does not change a login session or XFCE/X11 state, and must
never update the formal SG checklist on its own.

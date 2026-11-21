# SG6 two-runner build evidence — PR preflight vs trusted main

**Purpose:** build the *real* Core, Native, Session, and Desktop Debian
packages independently on two Ubuntu 24.04 GitHub-hosted runners and compare
all four archive byte streams in a third job.

The `sg6-cross-runner.yml` workflow runs in two distinct trust modes:

| Trigger | Source | Build+compare | OIDC/attestation | SG6 sign-off |
| --- | --- | --- | --- | --- |
| Relevant `pull_request` | GitHub test merge commit (`GITHUB_SHA`) | Yes, two VMs and third comparison job | **Never** | No |
| Relevant `push` on `main` | Exact checked-out main SHA, checked against the live main ref | Yes | Separate `attest` job after comparison | Candidate; still requires review of the *actual run* |
| Deliberate `workflow_dispatch` on `main` | Exact checked-out main SHA, checked against live ref | Yes | Separate `attest` job after comparison | Candidate; still requires review of the *actual run* |

A passing PR comparison is useful to catch real compilation/packaging and
cross-runner differences **before** integration. It is not an exact-main
provenance receipt, physical Mint acceptance or authorization for release.

## What the verifier actually checks

- Receipts from each hosted runner contain matching exact source SHA,
  **distinct hosted-runner job names**, matching build-tool versions, timestamp
  and lockfile SHA-256. Hostname hashes are recorded as diagnostic metadata
  only: GitHub's guest hostname template can match across distinct runners,
  and neither name nor hostname is a cryptographic VM identity proof.
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
- After integration, require the automatically triggered **trusted main push**
  run when the commit changes any SG6 package input. For a different exact
  `main` SHA where the workflow path filters did not trigger, deliberately
  dispatch `SG6 independent-runner four-deb reproducibility` on `main`.
  Verify the non-skipped `attest` job, downloaded report, event (`push` or
  `workflow_dispatch`), current main SHA and all four digests. A passing
  PR run, a queued signing job or an obsolete main receipt is insufficient.
- After further merges, previous main receipts are historical and do not
  satisfy an exact-final-main release dossier.

## Trusted-main signed package receipt (20 November 2026)

On [`main@6df41f60818cb1a41bd80d198932edf0ef266a63`](https://github.com/CopyPasteUser/Ricebowl/commit/6df41f60818cb1a41bd80d198932edf0ef266a63),
the [SG6 independent-runner run #44779349464](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44779349464)
completed successfully on a trusted `push`. Both independent builders and
the third comparison job passed. The **executed** main-only `actions/attest@v4`
step signed the downloaded report:

- [GitHub Attestation #70241030](https://github.com/CopyPasteUser/Ricebowl/attestations/70241030)
- Subject: `report.json`, SHA-256 `8a22caa97ed181fb620c9bad1552a7176aa4bca012755228324caf6e16b38473`
- Public Sigstore Rekor index: `4027375948`
- Recorded source SHA: `6df41f60818cb1a41bd80d198932edf0ef266a63`
- Four byte-identical packages from independently identified hosted runners;
  the comparison report and subject digest were independently rechecked
  against the downloaded artifact.

This verifies **report identity and digest**, not a cryptographic external
attestation of the build machines themselves. Final SG6 acceptance also
requires Tests plus the exact-main installed native/Ubuntu/Mint recovery jobs
to finish successfully; their outcomes must not be inferred from this
comparison alone.

## Hostname template collision observed on main (21 November 2026)

The trusted main [run #44879890124](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44879890124)
on `e81e092eb6fc366b14ed977863455cf4611b622e`
successfully built four identical packages on each of two hosted runner jobs,
but the separate comparison job **correctly reported failure under the then
current verification policy**. Analysis of both downloaded build receipts
found distinct GitHub job runner names (`GitHub Actions 1000013479` and
`GitHub Actions 1000013478`) with the *same* guest hostname hash. The
independent four-file SHA-256 comparisons succeeded. A hostname is not a
documented unique GitHub-hosted VM identifier, and requiring its hash to
differ falsely rejected the independent job comparison.

The follow-up verifier fix keeps the distinct runner-name requirement,
records `distinct_hostname_hashes_observed` transparently, and retains the
explicit no-external-machine-attestation limitation. This **does not** mean
the failed run is an SG6 acceptance receipt: only a new successful trusted
main comparison **and executed signing jobs** can satisfy that requirement.

## SG6 implementation and evidence requirements

The installed-package regression matrix now includes source-built, versioned
Native and Session transitions (PRs [#559](https://github.com/CopyPasteUser/Ricebowl/pull/559)
and [#563](https://github.com/CopyPasteUser/Ricebowl/pull/563)),
rather than only Core/Meta relabeling. It exercises dependency-safe
downgrade/upgrade, archive corruption, an actual injected `dpkg`
configuration `SIGKILL`, recovery, re-login, purge and preservation of
unmodified owner-private recipes and XFCE settings in disposable Ubuntu.

A separate Mint 22.1 Xia package root runs real four-package installation,
reinstallation, corrupt-archive rejection, interrupted configuration
recovery and purge against the exact tested source
([#562](https://github.com/CopyPasteUser/Ricebowl/pull/562)). A green
Ubuntu job cannot substitute for its separate Mint result.

The following successful **trusted `main` push** runs share exactly
`6df41f60818cb1a41bd80d198932edf0ef266a63`:

- [Tests #44779349293](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44779349293):
  completed successfully (unfiltered Python/X11/contract workflow).
- [Native #44779349236](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44779349236):
  completed successfully, including the executed native-layer-shell,
  installed Ubuntu upgrade/downgrade and repair checks, the independent
  **SG6 disposable Mint Xia package install and recovery** job, and the
  trusted-main native-preview attestation.
- [Cross-runner #44779349464](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44779349464):
  two distinct builder jobs, separate byte comparison and main-only
  signing all completed successfully.

[#567](https://github.com/CopyPasteUser/Ricebowl/pull/567) is already integrated
at that exact SHA. These are **historical pinned evidence**, not proof
that a later `main` SHA passed. A separate review of the downloaded receipt,
package digests and attestation subject remains required before asserting
full SG6 gate acceptance. The exact final SG7 matrix has other workflows and
requirements which these SG6 runs do not establish.

The report continues to say
`independent_external_provenance_certified=false`: two GitHub-hosted runner
VMs and a GitHub-signed report are traceable hosted CI evidence, **not**
independent third-party toolchain auditing or physical-device certification.
Mint/ThinkPad login, GPU, Flatpak and real-hardware recovery remain separate
later release gates. Neither this document nor a green PR changes the
formal checklist in issue #417.

## SG6 software-only acceptance — 21 November 2026

The [SG6 item in issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417)
was checked after trusted exact-main evidence for
[`344d5557a749213dfdd83be2db4a5ba21e8b2624`](https://github.com/CopyPasteUser/Ricebowl/commit/344d5557a749213dfdd83be2db4a5ba21e8b2624):

- [Tests #44881618535](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44881618535):
  test job completed successfully, including the executed suite step.
- [Native #44881618473](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44881618473):
  native build, clean four-package rebuild, historical upgrades/downgrades,
  corrupted archive rejection and interrupted dpkg recovery passed.
  The separate disposable Mint 22.1 Xia install/recovery job also succeeded.
- [Cross-runner #44881618480](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44881618480):
  two hosted builders, the third independent byte comparison and the trusted
  signing job all completed successfully. The signer attested both the
  [comparison report (#70471969)](https://github.com/CopyPasteUser/Ricebowl/attestations/70471969)
  and [all four package subjects (#70471973)](https://github.com/CopyPasteUser/Ricebowl/attestations/70471973).

This closes SG6 **for the software-only gate**. These receipts do not
certify third-party toolchains, physical power-loss behavior, Mint/ThinkPad
login, GPU/DRM, Flatpak consent or stable 1.0 readiness. SG1–SG5 and SG7
remain open. A future exact-final-main review must use current-source CI
rather than reusing these historical receipts.

# RiceBowl DE 1.0 – integration contract

> Scope: experimental native labwc/Wayland DE only. XFCE/X11 stays the supported
> default. This document governs **parallel changes**; it is not a release
> certificate. Always inspect current GitHub state before acting on the snapshot.

## Integration authority and sources of truth

- `main` is the sole stable integration base; never merge directly from a
  stale checkout or override concurrent commits.
- [AGENTS.md](../AGENTS.md) defines architectural/safety constraints;
  [RICEBOWL_DE_ROADMAP.md](../RICEBOWL_DE_ROADMAP.md) defines functional targets;
  [RELEASE_1_0_GATES.md](../RELEASE_1_0_GATES.md) defines release sign-off.
- Each lane works on its own branch and submits a **draft PR**. GitHub PR
  descriptions/comments are asynchronous hand-offs, not proof of behavior.
- Only the integration lane makes reviewed merges into `main`; no agent
  should automatically merge another lane's PR.
- This applies equally to unattended RiceBowl development automations.
  Their existing schedules are not controlled by this document. Operators must
  coordinate those automations before enabling concurrent write access.

## Temporary offline lane-owned integration (owner decision, 22 November 2026)

The repository owner explicitly authorized **each scoped development lane to review
and merge its own pull request** in the current November 2026 offline-development
period. This replaces the earlier *integration-only merge authority* for
owner-approved, isolated SG1–SG5 work **only**. All other architecture, safety
and release requirements in this document remain in effect. The integration
lane remains responsible for shared hotpots, cross-lane interfaces and final
release acceptance, but is not a mandatory hand-off for independent lane PRs.

- **No GitHub Actions until December 2026.** Do not dispatch, rerun or use
  hosted Actions as a substitute for local testing. Every new branch commit
  and every merge commit must contain `[skip ci]` in its commit message.
- Self-merge is permitted only for **the lane's own strictly owned files**,
  after a real full-checkout local test run appropriate to the change. Tests
  must be executed on the exact PR head; source excerpts, mocked snippets and
  `sh -n` alone do not certify a runtime change. Where genuine labwc/Rust/
  Mako integration is required, it must run in an isolated development
  environment. If tools or a full checkout are missing, the PR **cannot**
  be declared ready or merged just to remove a draft from the queue.
- Before editing, inspect the current main and all open PRs. No other lane may
  modify an assigned file or a shared hotspot. A shared dependency requires
  an explicit integration handoff; do not widen scope silently.
- Merges are **serialized**. Just before each merge, reread main and the PR's
  exact head SHA and all changed paths. Verify mergeability, unresolved
  reviews, branch-protection requirements and that all relevant tests were
  performed against the up-to-date integrated tree. If main advanced since
  local validation, update the local checkout and rerun the affected tests.
  Merge with an expected-head-SHA guard and `[skip ci]`. Never force push or
  bypass branch protection.
- Immediately after merging, retrieve the new main SHA and rerun the relevant
  local regression tests against that exact integrated tree. Repair or revert
  any regression rather than calling the lane complete.
- A lane can report **DONE** only after implementation, its exact-head tests,
  its own guarded merge, and post-merge validation, with commit IDs and actual
  test outputs. If any prerequisite remains unavailable, report
  **BLOCKED / NOT MERGED**. Avoid speculative "five-minute fixes" passed off
  as closure of an entire shared software gate.
- This temporary integration exception does **not** replace exact-main
  hosted-CI evidence required for formal SG acceptance or 1.0 release
  certification. Those signoffs remain open until their own contractual
  requirements can actually be met after December.

## Four development lanes and integration lane

| Lane | Owns | Boundary |
| --- | --- | --- |
| **core** | `input_core.rs`, desktop keyboard focus/seat policy, foreign-toplevel window registry/actions, shared surface/event lifecycle | Does not implement file operations or rice-specific menu UI |
| **desktop** | Native XDG Desktop inventory, selection/layout/positions, file operations and RiceField hand-off | Uses core input/focus API; does not independently own compositor grabs |
| **system** | `macrice/de/session.py`, `settings_backend.py`, `wayland_displays.py`, `display_restore.py`, OS services and portals | Backends may expose capabilities but may not redesign the GTK settings UI |
| **shell** | `native_menu.rs`, `menu_chrome.rs`, `recipe.rs`, `macrice/de/settings.py`, Creator and RicePack/UI contracts | No duplicate NetworkManager/BlueZ/PipeWire/window-management backends |
| **integration** | Shared interface contracts, PR review, head-SHA CI, merge order, performance/release QA and this governance file | No opportunistic concurrent feature rewrite |

**Collision-prone paths:** `components/riceplate-wayland/src/main.rs`,
`macrice/de/session.py`, `macrice/de/settings.py`,
`components/riceplate-wayland/src/recipe.rs`,
`.github/workflows/riceplate-native.yml`, and
`scripts/smoke_riceplate_native.sh`. An owner may use their assigned path,
but every concurrent change to these paths requires coordination in the PR
description with the other affected lane(s). `main.rs` glue should be
small and reviewed by integration, while behavior lives in owned modules.

**Cross-lane feature request protocol:**

1. Open a GitHub issue/PR comment defining the **type signature, state machine,
   error states, security boundary and intended call sites**.
2. Wait for the owning lane to supply the API (or explicitly transfer the
   single-file ownership for a limited change).
3. Base stacked work on the owning PR only when necessary; clearly state the
   parent branch and dependency in the PR body.
4. Never silently cherry-pick/duplicate unmerged private branch behavior.
5. Rebase/retarget only after the parent lands and rerun CI for the new head.

## Integration dependency snapshot (15 November 2026; verified main)

This snapshot supersedes the obsolete 14 November unmerged-PR graph; earlier
states remain available in Git history. Refresh live GitHub refs before every
new merge. Coordination: [issue #360](https://github.com/CopyPasteUser/Ricebowl/issues/360).

```text
main @ fca6910d5a885d0bfd0f37d757f199775f821983
├── #376 native XDG context/rename/Trash — MERGED 1eb682a
├── #377 bounded shortcut keyboard focus — MERGED 5dcf4f6
├── #378 durable XDG file positions — MERGED fb47082
├── #379 native New Folder surface — MERGED b017b4b
├── #380 icon drag/output handoff — MERGED 576416b
├── #381 compositor-ready shared Rice live transaction — MERGED 134851e
├── #382 CI-only generic/pixman real PipeWire video frame — MERGED 16daf0a
├── #384 optional production wlr/GLES2 GPU test preparation — MERGED b3431ad
└── #383 native desktop → external GTK keyboard handoff — MERGED fca6910
```

**At this snapshot:** no open GitHub pull requests. No other agent's active
branch is implicitly approved for merging.

### Verified post-merge acceptance

On the exact merged `main@fca6910` (not only on `#383` head):

- [Tests #43678051131](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051131)
  — **success**, push event, including the legacy XFCE/X11 and Python suite.
- [Native RicePlate #43678051154](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43678051154)
  — **success**, push event. Actual headless labwc smoke verifies native
  keyboard Enter and return to a real GTK Wayland text-entry client,
  shortcut typing/Escape, file rename/Trash/New Folder/icon drag,
  two-output icon move and hotplug, XWayland taskbar/clipboard,
  compositor-confirmed Rice switching (Classic → Chrome → XP Luna → Chrome),
  private Creator recovery and failure rollback, installed-session
  lock guard, package downgrade/upgrade, and XFCE/test-user data preservation.
- The strict **generic/pixman software frame** test (PR #382) proved an
  actual PipeWire/GStreamer sample without a DRM node. That is a CI-private
  backend with CI-only patches; the production selection remains wlr.
  PR #384 prepared a GPU runner lane but did **not** certify real
  GPU/GLES2 production capture. Keep [#304](https://github.com/CopyPasteUser/Ricebowl/issues/304)
  open. Likewise keep [#328](https://github.com/CopyPasteUser/Ricebowl/issues/328)
  open for physical Mint/IME/Orca/client-matrix signoff.
- The separate Wayland session preview / strict portal GPU workflows were
  not both shown as fresh post-merge push runs for this exact `main` SHA:
  do not infer they passed on it. Relevant installed-session recovery and
  portal software smoke run inside the successful Native CI; physical
  login, hardware/Flatpak and final release evidence remain **unverified**.

### Safe next integration sequence

1. Continue feature implementation on isolated, owner-scoped branches only;
   inspect the latest main/PR state before opening or merging anything.
2. Use verified typed Core/desktop/system/shell APIs; do not reintroduce
   duplicate focus managers, independent Linux settings adapters or multiple
   per-rice execution engines.
3. Require exact-head CI and real compositor regressions for input/desktop
   changes; check upgrade/rollback, owner-private state and XFCE invariants.
4. After every future merge, validate new `main` via GitHub push runs and
   record actual SHA/run links in #360. If failed, investigate and revert;
   never substitute PR-green evidence for post-merge checks.
5. Reserve physical Mint/ThinkPad, IME/Orca, DRM/GLES2, Flatpak consent,
   multi-monitor and final reproducibility/performance certification for
   their explicit hardware/release gates, not a fictitious CI pass.

## Mandatory PR pre-merge checklist

For a candidate `head_sha` and the contemporaneous `main_sha`:

- [ ] Fetch exact head/base SHAs, full diff, changed paths, stack parents and
  status of the PR; inspect outdated docs and competing changes.
- [ ] Check owner boundaries, shared hotspots, all upstream dependencies,
  branch ancestry, reviews and unresolved discussions.
- [ ] Review Wayland protocol and D-Bus/IPC/resource lifecycle; reject
  stale window proxies, unbounded waits, shell interpolation and untrusted
  filesystem traversal. Confirm no global XFCE settings are changed.
- [ ] **Exact-head** Tests, native Rust tests, Clippy, release build and genuine
  labwc smoke all pass when affected. Wayland session/packaging/recovery tests
  must pass for session/package changes. A check from an intermediate commit,
  another PR, or just a green merge button does not count.
- [ ] For UI/input changes, inspect genuine `grim` outputs and verify
  interactions (pointer *and* keyboard), geometry, output/mixed-DPI and
  accessibility boundaries. Screenshots alone do not establish function.
- [ ] Corrupted config, missing provider, cancellation, crashed child,
  rollback and X11/XFCE non-regression covered by relevant tests.
- [ ] **Re-read the head SHA immediately before merge**, use GitHub's
  expected-head-SHA guard, and reject if it moved.
- [ ] After merge, fetch the **new main SHA** and verify full appropriate
  workflows on that exact SHA. If regression occurs, investigate and revert
  the offending change, not the tests.
- [ ] Keep physical Mint hardware/IME/Orca/real GPU/portal acceptance
  outstanding until traceable on-device evidence exists.

If a change is doc-only and has no runtime or CI effect, explicitly record
that limited scope and still require valid merge ancestry, review and exact-head
tests appropriate to the change. Never bypass a failing **relevant** gate.

## Performance and release evidence

Track actual `labwc`, native RicePlate, Mako, swayidle, optional Waybar and
on-demand RiceSpice PSS/RSS, CPU time/wakeups, startup and session shutdown.
Measure whole-session and per-process cost on the same physical machine,
including cold start, repeated rice switching, two outputs and long-running
idle. Report hardware/kernel, display configuration and exact commit SHA.
Headless CI timings and screenshot-script wall time are **not** hardware
performance benchmarks. Extra resident helpers require measured benefit
and verified cleanup.

Release status is binary by gate, never a made-up percentage. The mandatory
real-device list in `RELEASE_1_0_GATES.md` stays open until independently
performed and recorded. The 1.0 sign-off JSON must not be marked approved
on CI evidence alone.

## Concurrent writers and scheduled automation

At the 14 November preflight, task automation **RiceBowl Wayland
weiterentwickeln** (`Automation_ef9aa6256c388191b92abae017fad985`) was
verified **disabled**. The older XP Luna and RiceBowl Roadmap automation tasks
were also disabled. This resolves the previously documented *scheduled*
merge-writer overlap; it does not prevent other live development chats
from pushing to their own branches. A file lease requires fresh head/base
checks before every write, and only Integration merges to `main`.
Other active automations target separate repositories and are not treated
as RiceBowl merge approval.

## Reporting format

Report **merged into main**, **implemented on branch**, **CI pass**,
**CI fail**, **pending**, and **on-device unverified** as separate states.
Include stable PR URLs, exact head/main SHAs and GitHub Actions run links.
After each integration, update the dependency graph from *live* GitHub data
instead of copying this snapshot.

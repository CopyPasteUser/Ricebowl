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

## Integration dependency snapshot (2026-11-14; refresh before each merge)

This is an **evidence snapshot**, not a branch lock or release certificate.
Live coordination: [issue #360](https://github.com/CopyPasteUser/Ricebowl/issues/360).
Current refs and exact-head checks must always override this snapshot.

```text
main @ 7fd55f44832d3e15be4bcd00daf719fa56d687af (verified at snapshot)
├── #367 Core focus lease/seat fallback — MERGED 23f524e7
├── #370 XDG inventory/inotify/file state — MERGED 7fd55f4
├── #366 XP Run pointer/focus — Draft; native CI failed
├── #368 strict portal ScreenCast — Draft; strict DRM frame gate outstanding
├── #369 governance refresh — this documentation PR
├── #371 native file-desktop assembly — Draft; native E2E outstanding
├── #372 file actions/RiceField — Draft; reconciled with main, CI pending
└── #373 compositor focus timeout/probe — Draft; reconciled, CI pending
```

**Main includes foundations, not a completed interactive file desktop.**
#367 owns the seat-safe focus state machine; it does not prove real
compositor keyboard focus on Bottom-layer icons. #370 supplies bounded
XDG inventory/inotify/file state without completed native UI surfaces.

**Pending runtime:** #371 must deliver live file layers, calloop watcher
wiring, real keyboard handling and return-to-client E2E under labwc.
#372 exposes verified file actions, no-overwrite rename and RiceField
intents, but does not prove UI integration. #373 provides bounded focus
acquisition and a diagnostic probe, not standalone production focus.
#366 must satisfy its full exact-head Run/Help native capture gate.

**Portals (#368):** D-Bus negotiation and a socket FD are not delivered
video. The strict gate requires a nonempty GStreamer frame on a compatible
DRM/GLES2 runner. Pixman response=2 remains a documented limitation.
A missing render node is an infrastructure blocker; never weaken the
frame assertion to force green CI.

### Safe merge sequence

1. Recheck current main, all PR heads, ancestry, review and exact-head
   Tests/Native status before each guarded merge.
2. After each merge, validate current main and shared-path regressions.
3. Finish #366 and #371 native runtime proof before claiming UX parity.
4. Integrate #372/#373 only after fresh CI on their main-based heads and
   relevant interaction/security review; no force-push of live branches.
5. Keep #368 unmerged without the required delivered-frame evidence.
6. Keep physical Mint/IME/accessibility/multioutput/Flatpak/real-GPU release
   gates open until validated on hardware.

Previously closed nonmerged 13 November PRs are not active dependencies.

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

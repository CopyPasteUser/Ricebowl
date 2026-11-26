# SG1–SG7 — remaining, testable work packages

Snapshot: 26 November 2026, `main@97c79af`. Authority stays with
[issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417) and the
[evidence index](sg1-sg7-evidence-progress.md); this file only breaks the
**12 open checkpoints** into work packages (WPs) with a definition of done.
It closes nothing and changes no percentage. Open PRs at snapshot: #601 (SG1),
#596 (SG7).

**Where:** `L` = runnable locally in a disposable headless labwc session
(the `ricebowl` cloud environment: labwc 0.7.1, Mako 1.8, non-root `rbdev`,
helpers `rb-sync`/`rb-run`). `L!` = local, but blocked by WP0 first.
`CI` = needs exact-head/exact-main hosted Actions (not before December 2026).
`OWNER` = owner decision or review. Physical hardware is not an SG item.
**Model hint:** `S` = routine fix/test (Sonnet, medium), `O` = diagnosis,
races, protocol or security-sensitive design (Opus, high).

Formal closure of every SG still requires its CI evidence; local green is
the prerequisite, not the acceptance.

## Local baseline (measured 26 Nov 2026, non-root, headless labwc 0.7.1)

| Result | Checks |
| --- | --- |
| PASS | Python suite (1,949 passed via pytest; CI uses `unittest discover -s tests`), Rust `cargo test` (503), `smoke_sg1_sni_labwc`, `smoke_sg1_window_recovery_labwc`, `smoke_riceplate_windows --luna`, `smoke_riceplate_luna_autohide`, `smoke_riceplate_multioutput`, `smoke_luna_hotkeys`, `smoke_wayland_shared_rice_engine`, `smoke_luna_settings_labwc`, `smoke_creator_gui_labwc`, `smoke_wayland_session` |
| Not a gate (deferred) | `smoke_riceplate_desktop_focus` (opt-in diagnostic, not run by any workflow; WP0.4) |
| Fixed since snapshot | `smoke_riceplate_native` (WP0.1, 3/3 local passes), `smoke_riceplate_windows --xwayland`, `smoke_wayland_clipboard`, `smoke_luna_window_chrome` (WP0.2), `smoke_luna_atspi` with the CI-pinned labwc 0.7.2 (WP0.3) |

### Running checks locally (ricebowl environment)

```sh
rb-sync                                    # copy checkout to /home/rbdev (keeps target/)
rb-run env XDG_RUNTIME_DIR= dbus-run-session -- xvfb-run -a \
  python -m unittest discover -s tests     # CI-equivalent Python suite
rb-run sh -c 'cd components/riceplate-wayland && cargo test --locked'
rb-run env XDG_RUNTIME_DIR= dbus-run-session -- sh scripts/<smoke>.sh
RB_PATH_PREFIX=/opt/labwc-sg5 rb-run env XDG_RUNTIME_DIR= \
  dbus-run-session -- sh scripts/smoke_luna_atspi.sh   # SG5 IME needs labwc 0.7.2
```

Run compositor smokes one at a time: several use `pgrep -u` and timing
budgets. Release binaries must exist in the synced `target/` (build as root
in `/home/rbdev/Ricebowl/components/riceplate-wayland`, then `chown`).
| Environment limit | `smoke_wayland_portals`, `smoke_real_mako_111` (Mako 1.11 builds; no FUSE for the document portal, no running PipeWire) |

## WP0 — make the local baseline trustworthy (do first)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 0.1 | **DONE (harness):** after the active `wtype` keyboard disconnects, labwc 0.7.1 sends a new client `wl_keyboard.enter/modifiers` without a keymap and Fuzzel 1.9.2 segfaults in `xkb_state_update_mask`. The smoke now attaches a fresh self-expiring virtual keyboard before each re-open. No RicePlate change; 3/3 local full passes | Done | L | O |
| 0.2 | **DONE (environment):** the session had no locale (POSIX); xterm under XWayland exits immediately without one. CI runners use `C.UTF-8`; `rb-run` now sets it. All three XWayland smokes pass | Done | L | O |
| 0.3 | **DONE (environment):** the menu IME step needs input-method-v2, which stock labwc 0.7.1 lacks; CI builds a pinned private labwc 0.7.2 (`b41af54a`) for this step only. With that build the full smoke passes locally | Done | L | O |
| 0.4 | **Deferred:** `smoke_riceplate_desktop_focus` fails with `FOCUS_PROBE_FAIL bottom-pointer-event-missing`, but it is an opt-in diagnostic no workflow runs. Revisit with SG1.8 (focus/hotplug) | Green or retired with reason | L | S |
| 0.5 | Portal/Mako 1.11 without FUSE/PipeWire | Either an isolated opt-in variant without the document portal, or explicitly left to CI | L/CI | S |

## SG1 — shared shell (3/4): every advertised control × every state

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 1.1 | **DONE:** [inventory](sg1-control-state-inventory.md) (154 cells: 39 compositor, 40 unit-only, 36 gaps). Inventory every advertised shared control in both rices (XP Luna, Chrome) × {loading, empty, busy, unavailable/denied, error, focus loss, recovery} in the SG1 matrix | Complete table, each cell linked to a test or marked gap | L | S |
| 1.2 | Taskbar/window: two-rice minimize/maximize/close, transient loss/restart | Real labwc receipts in both rices | L! (0.2) | S |
| 1.3 | Desktop/files: multi-select, drag, permission denied, focus lost, both rices | Negative + recovery receipts | L | S |
| 1.4 | Launcher empty/error/busy in both rices | Real input; no stale action after empty/error | L! (0.1) | S |
| 1.5 | System controls and notifications: provider unavailable/denied/restart under labwc | Shared with SG2/SG3 fixtures; both rices | L | S |
| 1.6 | Luna clock tray: denied/unavailable provider, focus loss | End-to-end smoke | L | S |
| 1.7 | Remote SNI invalid secondary click on Chrome, end to end | Smoke receipt | L | S |
| 1.8 | Hotplug and scale change while menus are open; provider update during input | Deterministic smoke, no stale surfaces | L | O |
| 1.9 | Finish PR #601 | Local exact-head run, guarded self-merge per governance | L | S |
| 1.10 | Wire `smoke_sg1_window_recovery_labwc.sh` and `smoke_riceplate_windows.sh --chrome` into the native workflow (found unreferenced by WP1.1); integration-lane file | Workflow step exists | L (edit) / CI | S |
| 1.11 | Formal evidence | Exact-head + exact-main runs | CI | – |

## SG2 — RiceSpice (2/4)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 2.1 | **DONE:** [inventory](sg2-adapter-state-inventory.md) (186 cells: 93 covered, 14 partial, 35 gaps). Matrix per adapter (display, input, network, audio, Bluetooth, accessibility, power, time/NTP) × {verified readback, authorization denied, provider disconnected/unavailable, rollback}. A rough grep suggests input, Bluetooth, accessibility and NTP have the fewest co-located negative tests; verify | Table with test links and gaps | L | S |
| 2.2 | Fill the gaps with fake-provider unit tests plus disposable D-Bus tests | Every cell covered or explicitly unsupported in the UI | L | S |
| 2.3 | Check status of candidates #552 (NM post-write uncertainty) | Merged with evidence, or reworked | L | S |
| 2.4 | GUI pass per page in headless labwc showing denied/unavailable/busy visibly | Real GTK GUI under labwc, not CLI only | L | S |
| 2.5 | Whole matrix at one final `main` SHA | Exact-main run | CI | – |

## SG3 — RicePop (2/4)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 3.1 | Inbox/OSD live updates, keyboard and AT-SPI action semantics in both rices | Real Mako + labwc + AT-SPI receipts | L | S |
| 3.2 | Privacy (no unexpected persistence, bodies cleared), restart, localization and rendered-text matrix | Matrix with negative tests | L | S |
| 3.3 | Check status of candidate #553 (`ActionInvoked`) | Merged with evidence, or reworked | L | S |
| 3.4 | Real Mako 1.11 matrix | Local after 0.5, otherwise CI | L!/CI | S |

## SG4 — Creator/RicePack (2/4)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 4.1 | **DONE locally (26 Nov, `main@8f1398c`):** `scripts.verify_wayland_creator_handoff` produced 8 real labwc captures (Heritage/Orbit × 640×480, 1366×768 @1.0/@1.25, 1920×1080) and a manifest with `capture_is_interactive: false`, `visual_tolerances_approved: false`. Needs `target/release` on PATH, as in CI. Still requires CI archive (4.6) | Done (local) | L | S |
| 4.2 | GUI export→import, Creator exit→supervisor apply/restore, including killed Creator, interrupted journal, malformed config, relogin | Disposable-session tests for each case | L | O |
| 4.3 | Interactive pointer/keyboard/error/popup/AT checks on both imported rices | Real input receipts | L | S |
| 4.4 | Approved reference captures and geometry/clip/text/hit-target tolerances | Owner approves tolerances; then tests enforce them | OWNER + L | S |
| 4.5 | Rights audit of every asset (`rights_independently_verified` stays false until then) | Owner sign-off | OWNER | – |
| 4.6 | Exact-head native capture archive | CI run | CI | – |

## SG5 — text and input (2/4)

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 5.1 | IME v2→v3 for Rename; focus leave/re-enter; candidate selection; RTL flows | Protocol smoke per surface | L! (0.3) | O |
| 5.2 | Confirm menu IME (#600) and issue #595 in the final matrix | Ledger updated with local evidence | L | S |
| 5.3 | Cross-app clipboard on final source | `wl-copy`/`wl-paste` smoke green | L! (0.2) | S |
| 5.4 | Positive Hindi/CJK font coverage with measured glyph/caret positions (installable Noto fonts) | Rust + compositor pixel/metric tests | L | O |
| 5.5 | AT-SPI action invocation for Rename; dialog transitions | External AT-SPI client receipts | L | S |
| 5.6 | Fallback/missing-font matrix with an accessible client | Matrix complete; missing glyph never reported as success | L | S |

## SG7 — final software acceptance (1/4), last

| WP | Task | Done when | Where | Model |
| --- | --- | --- | --- | --- |
| 7.1 | Finish PR #596 (live-PR pinning, receipt IO) | Local tests + guarded merge | L | S |
| 7.2 | Longer headless resource/leak soak (idle PSS/CPU over time) | Documented local measurement; not a hardware benchmark | L | S |
| 7.3 | Unsupported/error states documented across components | Reviewed list | L | S |
| 7.4 | Exact final `main`: all workflows, strict portal, SG7 dossier | Only after SG1–SG5 merges | CI | – |

## Suggested order

WP0 → inventories 1.1 and 2.1 (cheap, make "done" measurable) → SG5 and SG1
(hardest, mostly `O`) → SG2/SG3 (mostly `S`) → SG4 (needs owner decisions
4.4/4.5) → SG7 (December, CI). One lane and one WP per session.
